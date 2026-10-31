from __future__ import annotations

import json
import queue
import threading
import time
from typing import Callable, Dict, List, Optional

from neo.config import (
    default_scoring_mode,
    get_config,
    get_scoring_mode_config,
    list_scoring_modes,
    resolve_scoring_mode_name,
)
from neo.defs import (
    default_difficulty,
    default_rounds,
    exposed_difficulties,
    round_bounds,
)
from neo.game import database as game_db
from neo.lobby.store import (
    LobbyPlayer,
    LobbyRoom,
    LobbySpectator,
    LobbyStatus,
    get_lobby_store,
)

LobbyBroadcastFn = Callable[[str, str, Optional[dict]], None]
_broadcast: Optional[LobbyBroadcastFn] = None


def set_lobby_broadcast(fn: LobbyBroadcastFn) -> None:
    global _broadcast
    _broadcast = fn


def _emit(room_id: str, event: str, payload: Optional[dict] = None) -> None:
    if _broadcast:
        _broadcast(room_id, event, payload)


class LobbyError(Exception):
    def __init__(self, code: str, http_status: int = 400, message: str | None = None):
        self.code = code
        self.http_status = http_status
        self.message = message or code


def validate_player_id(player_id: str) -> bool:
    if not player_id:
        return False
    pid = player_id.strip()
    if not (1 <= len(pid) <= 32):
        return False
    return True


def _lobby_cfg() -> dict:
    return get_config()["lobby"]


def _players_cfg() -> dict:
    return get_config()["players"]


def player_limit_bounds() -> tuple[int, int]:
    colors = get_config().get("pin_colors") or []
    return 1, max(1, len(colors))


def player_limits_meta() -> dict:
    lo, hi = player_limit_bounds()
    return {"min": lo, "max": hi}


def game_settings_meta() -> dict:
    r_lo, r_hi = round_bounds()
    modes = list_scoring_modes()
    return {
        "rounds": {"min": r_lo, "max": r_hi, "default": default_rounds()},
        "difficulties": list(exposed_difficulties()),
        "default_difficulty": default_difficulty(),
        "scoring_strategies": modes,
        "default_scoring_strategy": default_scoring_mode(),
    }


def normalize_room_limits(
    min_players: int,
    max_players: int,
    *,
    current_players: int = 0,
) -> tuple[int, int]:
    lo, hi = player_limit_bounds()
    try:
        min_p = int(min_players)
        max_p = int(max_players)
    except (TypeError, ValueError):
        raise LobbyError("INVALID_PLAYER_LIMITS", 400)
    if not (lo <= min_p <= hi) or not (lo <= max_p <= hi):
        raise LobbyError("INVALID_PLAYER_LIMITS", 400)
    if max_p < min_p:
        raise LobbyError("INVALID_PLAYER_LIMITS", 400)
    if current_players > max_p:
        raise LobbyError("MAX_BELOW_PLAYER_COUNT", 400)
    return min_p, max_p


def normalize_rounds(rounds) -> int:
    lo, hi = round_bounds()
    try:
        value = int(rounds)
    except (TypeError, ValueError):
        raise LobbyError("INVALID_ROUNDS", 400)
    if not (lo <= value <= hi):
        raise LobbyError("INVALID_ROUNDS", 400)
    return value


def normalize_difficulty(difficulty) -> str:
    if difficulty is None:
        return default_difficulty()
    value = str(difficulty).strip().upper()
    if value not in exposed_difficulties():
        raise LobbyError("INVALID_DIFFICULTY", 400)
    return value


def normalize_scoring_strategy(strategy) -> str:
    if strategy is None:
        return default_scoring_mode()
    try:
        return resolve_scoring_mode_name(str(strategy).strip())
    except KeyError:
        raise LobbyError("INVALID_SCORING_STRATEGY", 400)


def _build_room_scoring_config(scoring_strategy: str) -> dict:
    """Snapshot the selected mode's full hyperparameter block onto the room."""
    return get_scoring_mode_config(scoring_strategy)


def _ensure_living_host(room: LobbyRoom) -> bool:
    """Reassign host_id if the current host is not among room.players.

    Returns True if host_id changed.
    """
    if not room.players:
        if room.host_id:
            room.host_id = ""
            return True
        return False
    living = {p.player_id for p in room.players}
    if room.host_id in living:
        return False
    room.host_id = room.player_ids_ordered()[0]
    return True


def _room_update_payload(room: LobbyRoom) -> dict:
    return {
        "revision": room.revision,
        "host_id": room.host_id,
        "players": room.to_dict()["players"],
        "spectators": room.to_dict()["spectators"],
        "status": room.status.value,
        "min_players": room.min_players,
        "max_players": room.max_players,
        "rounds": room.rounds,
        "difficulty": room.difficulty,
        "scoring_strategy": room.scoring_strategy,
        "countdown_deadline": room.countdown_deadline,
        "countdown_remaining_seconds": room.countdown_remaining_seconds(),
    }


def join(
    room_id: Optional[str],
    player_id: str,
    connection_id: str,
    min_players: Optional[int] = None,
    max_players: Optional[int] = None,
    rounds: Optional[int] = None,
    difficulty: Optional[str] = None,
    scoring_strategy: Optional[str] = None,
) -> dict:
    if not validate_player_id(player_id):
        raise LobbyError("INVALID_PLAYER_ID", 400)
    player_id = player_id.strip()
    store = get_lobby_store()
    cfg_min = _players_cfg()["min"]
    cfg_max = _players_cfg()["max"]
    min_p = min_players if min_players is not None else cfg_min
    max_p = max_players if max_players is not None else cfg_max
    min_p, max_p = normalize_room_limits(min_p, max_p)
    room_rounds = normalize_rounds(rounds if rounds is not None else default_rounds())
    room_difficulty = normalize_difficulty(
        difficulty if difficulty is not None else default_difficulty()
    )
    room_strategy = normalize_scoring_strategy(
        scoring_strategy if scoring_strategy is not None else None
    )

    existing = store.get_player_room(player_id)
    if existing:
        previous = store.get_room(existing)
        if previous:
            with store.acquire_lock(existing):
                _prune_stale_connections(previous, _lobby_cfg().get("reconnect_grace_seconds", 60))
        existing = store.get_player_room(player_id)
    if existing and not room_id:
        previous = store.get_room(existing)
        member = _find_player(previous, player_id) if previous else None
        if member and connection_id in member.connection_ids:
            room_id = existing
    if existing and existing != room_id:
        raise LobbyError("ALREADY_IN_ROOM", 409)

    if not room_id:
        room_id, is_quick = _find_or_create_quick_room(store, min_p, max_p)
    else:
        room_id = room_id.strip()
        is_quick = False

    with store.acquire_lock(room_id):
        room = store.get_room(room_id)
        if room is None:
            room = LobbyRoom(
                room_id=room_id,
                host_id=player_id,
                min_players=min_p,
                max_players=max_p,
                rounds=room_rounds,
                difficulty=room_difficulty,
                scoring_strategy=room_strategy,
            )
            store.save_room(room)
            if is_quick:
                store.quick_pool_add(room_id)

        if room.status == LobbyStatus.IN_GAME:
            player = _find_player(room, player_id)
            if player:
                return _reconnect_player(store, room, player, connection_id, player_id)
            raise LobbyError("ROOM_IN_GAME", 409)

        if len(room.players) >= room.max_players:
            existing_p = _find_player(room, player_id)
            if existing_p:
                return _reconnect_player(store, room, existing_p, connection_id, player_id)
            raise LobbyError("ROOM_FULL", 409)

        player = _find_player(room, player_id)
        if player is None:
            player = LobbyPlayer(player_id=player_id)
            room.players.append(player)
            _emit(room_id, "player_joined", {"player_id": player_id})
        player.connection_ids.add(connection_id)
        player.connected = True
        player.last_heartbeat = time.time()
        player.connection_seen[connection_id] = player.last_heartbeat
        store.set_player_room(player_id, room_id, "player")
        _ensure_living_host(room)
        store.save_room(room)

        _evaluate_waiting(room)
        store.save_room(room)
        _emit(room_id, "lobby_update", _room_update_payload(room))
        return _build_join_response(room, player_id, player_id == room.host_id)


def _find_or_create_quick_room(store, min_p: int, max_p: int) -> tuple[str, bool]:
    for rid in store.quick_pool_list():
        with store.acquire_lock(rid):
            room = store.get_room(rid)
            if (
                room
                and room.status in (LobbyStatus.WAITING, LobbyStatus.COUNTDOWN)
                and room.min_players == min_p
                and room.max_players == max_p
                and len(room.players) < room.max_players
            ):
                return rid, True
    import uuid

    new_id = f"room_{uuid.uuid4().hex[:12]}"
    return new_id, True


def _find_player(room: LobbyRoom, player_id: str) -> Optional[LobbyPlayer]:
    for p in room.players:
        if p.player_id == player_id:
            return p
    return None


def _reconnect_player(store, room: LobbyRoom, player: LobbyPlayer, connection_id: str, player_id: str) -> dict:
    player.connection_ids.add(connection_id)
    player.connected = True
    player.last_heartbeat = time.time()
    player.connection_seen[connection_id] = player.last_heartbeat
    store.set_player_room(player_id, room.room_id, "player")
    store.save_room(room)
    return _build_join_response(room, player_id, player_id == room.host_id)


def observe(room_id: str, player_id: str, connection_id: str) -> dict:
    if not validate_player_id(player_id):
        raise LobbyError("INVALID_PLAYER_ID", 400)
    if not room_id:
        raise LobbyError("ROOM_NOT_FOUND", 404)
    player_id = player_id.strip()
    room_id = room_id.strip()
    store = get_lobby_store()

    with store.acquire_lock(room_id):
        room = store.get_room(room_id)
        if room is None:
            raise LobbyError("ROOM_NOT_FOUND", 404)
        if room.status not in (LobbyStatus.WAITING, LobbyStatus.COUNTDOWN, LobbyStatus.IN_GAME):
            raise LobbyError("ROOM_IN_GAME", 409)

        spec = None
        for s in room.spectators:
            if s.player_id == player_id:
                spec = s
                break
        if spec is None:
            spec = LobbySpectator(player_id=player_id)
            room.spectators.append(spec)
        spec.connection_ids.add(connection_id)
        spec.last_heartbeat = time.time()
        spec.connection_seen[connection_id] = spec.last_heartbeat
        store.set_player_room(player_id, room_id, "spectator")
        store.save_room(room)
        _emit(room_id, "lobby_update", _room_update_payload(room))
        return _build_join_response(room, player_id, False, role="spectator")


def leave(room_id: str, player_id: str, connection_id: str) -> dict:
    store = get_lobby_store()
    with store.acquire_lock(room_id):
        room = store.get_room(room_id)
        if room is None:
            return {"ok": True}
        removed = False
        for p in list(room.players):
            if p.player_id == player_id:
                p.connection_ids.discard(connection_id)
                p.connection_seen.pop(connection_id, None)
                if not p.connection_ids:
                    room.players.remove(p)
                    store.set_player_room(player_id, None, "player")
                    removed = True
                    _emit(room_id, "player_left", {"player_id": player_id})
        for s in list(room.spectators):
            if s.player_id == player_id:
                s.connection_ids.discard(connection_id)
                s.connection_seen.pop(connection_id, None)
                if not s.connection_ids:
                    room.spectators.remove(s)
                    store.set_player_room(player_id, None, "spectator")
        if removed:
            _ensure_living_host(room)
            if room.status == LobbyStatus.COUNTDOWN:
                if len(room.players) < room.min_players:
                    room.status = LobbyStatus.WAITING
                    room.countdown_deadline = None
        store.save_room(room)
        if removed:
            _emit(room_id, "lobby_update", _room_update_payload(room))
        return {"ok": True}


def start(room_id: str, player_id: str) -> dict:
    store = get_lobby_store()
    with store.acquire_lock(room_id):
        room = store.get_room(room_id)
        if room is None:
            raise LobbyError("ROOM_NOT_FOUND", 404)
        if room.host_id != player_id:
            raise LobbyError("NOT_HOST", 403)
        if room.status == LobbyStatus.IN_GAME:
            return {"ok": True, "status": "IN_GAME", "room_id": room.room_id,
                    "game_url": f"/index.html?room={room.room_id}&player_id={player_id}"}
        if not room.players:
            raise LobbyError("ROOM_EMPTY", 400)
        _begin_starting(room)
        return {
            "ok": True,
            "status": "IN_GAME",
            "room_id": room.room_id,
            "game_url": f"/index.html?room={room.room_id}&player_id={player_id}",
        }


def update_room_settings(
    room_id: str,
    player_id: str,
    min_players: int,
    max_players: int,
    rounds=None,
    difficulty=None,
    scoring_strategy=None,
) -> dict:
    store = get_lobby_store()
    with store.acquire_lock(room_id):
        room = store.get_room(room_id)
        if room is None:
            raise LobbyError("ROOM_NOT_FOUND", 404)
        if room.host_id != player_id:
            raise LobbyError("NOT_HOST", 403)
        if room.status not in (LobbyStatus.WAITING, LobbyStatus.COUNTDOWN):
            raise LobbyError("ROOM_IN_GAME", 409)
        n = len(room.players)
        min_p, max_p = normalize_room_limits(
            min_players, max_players, current_players=n
        )
        room.min_players = min_p
        room.max_players = max_p
        if rounds is not None:
            room.rounds = normalize_rounds(rounds)
        if difficulty is not None:
            room.difficulty = normalize_difficulty(difficulty)
        if scoring_strategy is not None:
            room.scoring_strategy = normalize_scoring_strategy(scoring_strategy)
        if room.status == LobbyStatus.COUNTDOWN and n < min_p:
            room.status = LobbyStatus.WAITING
            room.countdown_deadline = None
        elif room.status == LobbyStatus.WAITING:
            _evaluate_waiting(room)
        store.save_room(room)
        _emit(room_id, "lobby_update", _room_update_payload(room))
        d = room.to_dict()
        d["countdown_remaining_seconds"] = room.countdown_remaining_seconds()
        return {
            "ok": True,
            "player_limits": player_limits_meta(),
            "game_settings": game_settings_meta(),
            "room": d,
        }


def heartbeat(room_id: str, player_id: str, connection_id: str) -> dict:
    store = get_lobby_store()
    timeout = _lobby_cfg().get("reconnect_grace_seconds", 60)
    with store.acquire_lock(room_id):
        room = store.get_room(room_id)
        if room is None:
            return {"ok": True, "present": False}
        now = time.time()
        for p in room.players:
            if p.player_id == player_id:
                p.connection_ids.add(connection_id)
                p.last_heartbeat = now
                p.connection_seen[connection_id] = now
        for s in room.spectators:
            if s.player_id == player_id:
                s.connection_ids.add(connection_id)
                s.last_heartbeat = now
                s.connection_seen[connection_id] = now
        _prune_stale_connections(room, timeout)
        _evaluate_countdown(room)
        store.save_room(room)
        return {
            "ok": True,
            "status": room.status.value,
            "room": room.to_dict(),
            "present": any(m.player_id == player_id for m in room.players + room.spectators),
            "countdown_deadline": room.countdown_deadline,
            "countdown_remaining_seconds": room.countdown_remaining_seconds(),
        }


def room_status(room_id: str) -> dict:
    store = get_lobby_store()
    room = store.get_room(room_id)
    if room is None:
        raise LobbyError("ROOM_NOT_FOUND", 404)
    d = room.to_dict()
    d["countdown_remaining_seconds"] = room.countdown_remaining_seconds()
    d["player_limits"] = player_limits_meta()
    d["game_settings"] = game_settings_meta()
    return d


def _prune_stale_connections(room: LobbyRoom, timeout: float) -> None:
    now = time.time()
    removed = False
    for members in (room.players, room.spectators):
        for member in list(members):
            for cid in list(member.connection_ids):
                if now - member.connection_seen.get(cid, member.last_heartbeat) > timeout:
                    member.connection_ids.discard(cid)
                    member.connection_seen.pop(cid, None)
            if not member.connection_ids:
                members.remove(member)
                if get_lobby_store().get_player_room(member.player_id) == room.room_id:
                    get_lobby_store().set_player_room(member.player_id, None, "player")
                removed = True
                _emit(room.room_id, "player_left", {"player_id": member.player_id})
    host_changed = _ensure_living_host(room) if removed else False
    if room.status == LobbyStatus.COUNTDOWN and len(room.players) < room.min_players:
        room.status = LobbyStatus.WAITING
        room.countdown_deadline = None
    if removed or host_changed:
        _emit(room.room_id, "lobby_update", _room_update_payload(room))


def _evaluate_waiting(room: LobbyRoom) -> None:
    n = len(room.players)
    if room.min_players == 1 and room.max_players == 1:
        return
    if n >= room.max_players:
        _begin_starting(room)
        return
    countdown_sec = _lobby_cfg()["countdown_seconds"]
    if n >= room.min_players and countdown_sec >= 0:
        if room.status == LobbyStatus.WAITING:
            room.status = LobbyStatus.COUNTDOWN
            room.countdown_deadline = time.time() + countdown_sec


def _evaluate_countdown(room: LobbyRoom) -> None:
    if room.status != LobbyStatus.COUNTDOWN:
        return
    if room.countdown_deadline and time.time() >= room.countdown_deadline:
        _begin_starting(room)
    if len(room.players) >= room.max_players:
        _begin_starting(room)


def _begin_starting(room: LobbyRoom) -> None:
    if room.status == LobbyStatus.IN_GAME:
        return
    room.status = LobbyStatus.STARTING
    store = get_lobby_store()
    player_ids = room.player_ids_ordered()
    room_config = {
        "min_players": room.min_players,
        "max_players": room.max_players,
        "rounds": room.rounds,
        "difficulty": room.difficulty,
        "scoring_strategy": room.scoring_strategy,
        "scoring": _build_room_scoring_config(room.scoring_strategy),
    }
    game_db.init_room(room.room_id, player_ids, room_config)
    room.status = LobbyStatus.IN_GAME
    store.quick_pool_remove(room.room_id)
    store.save_room(room)

    from neo.game import routes as game_routes

    for s in room.spectators:
        game_routes.register_spectator(room.room_id, s.player_id)

    _emit(
        room.room_id,
        "match_starting",
        {
            "room_id": room.room_id,
            "player_ids": player_ids,
        },
    )


def _build_join_response(
    room: LobbyRoom, player_id: str, is_host: bool, role: str = "player"
) -> dict:
    d = room.to_dict()
    d["countdown_remaining_seconds"] = room.countdown_remaining_seconds()
    return {
        "room_id": room.room_id,
        "role": role,
        "is_host": is_host,
        "player_limits": player_limits_meta(),
        "game_settings": game_settings_meta(),
        "sse_url": f"/events/lobby/{room.room_id}?player_id={player_id}",
        "room": d,
    }


def tick_all_rooms() -> None:
    store = get_lobby_store()
    for room_id in list(store._rooms.keys()):
        try:
            with store.acquire_lock(room_id):
                room = store.get_room(room_id)
                if room and room.status in (LobbyStatus.WAITING, LobbyStatus.COUNTDOWN):
                    _prune_stale_connections(room, _lobby_cfg().get("reconnect_grace_seconds", 60))
                if room and room.status == LobbyStatus.COUNTDOWN:
                    before = room.status
                    _evaluate_countdown(room)
                    if room.status != before:
                        store.save_room(room)
                        _emit(room_id, "lobby_update", _room_update_payload(room))
        except Exception:
            pass
