from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from neo import calc
from neo.config import get_config, is_debug
from neo.settlement.context import SettlementContext
from neo.settlement.damage.registry import get_damage_fn
from neo.settlement.mode import get_damage_fn_name, get_game_mode, get_scoring_fn_name
from neo.settlement.points.registry import get_scoring_fn
from neo.scoring.rank import assign_score_ranks, assign_standings_ranks
from neo.game import database as db
from neo.game.database import Phase, RoomState, room_lock_guard

BroadcastFn = Callable[[str, str], None]
_broadcast: Optional[BroadcastFn] = None


def set_broadcast(fn: BroadcastFn) -> None:
    global _broadcast
    _broadcast = fn


def _emit(room_id: str, event: str) -> None:
    if _broadcast:
        _broadcast(room_id, event)


def _cfg_timeouts() -> dict:
    return get_config()["timeouts"]


def _scoring() -> dict:
    from neo.config import get_scoring_mode_config

    return get_scoring_mode_config()


def _room_scoring(room: RoomState) -> dict:
    return db.room_scoring_config(room)


@room_lock_guard
def check_timeouts(room_id: str) -> None:
    room = db.get_room(room_id)
    if room.phase == Phase.GAME_OVER:
        return
    if room.phase == Phase.REVEAL:
        _advance_from_reveal(room_id)
        return
    now = time.time()
    elapsed = now - room.phase_started_at
    if room.phase == Phase.GUESS:
        if elapsed >= _cfg_timeouts()["place_guess"]:
            _apply_guess_timeout(room_id)
    elif room.phase == Phase.AGREE_NEXT:
        if elapsed >= _cfg_timeouts()["agree_next"]:
            _apply_agree_timeout(room_id)


def tick_all_rooms() -> None:
    for room_id in list(db.rooms.keys()):
        try:
            prune_connections(room_id)
            check_timeouts(room_id)
        except Exception:
            pass


def _advance_from_reveal(room_id: str) -> None:
    room = db.get_room(room_id)
    if room.phase != Phase.REVEAL:
        return
    if _should_end_game(room):
        _enter_game_over(room_id)
    else:
        room.phase = Phase.AGREE_NEXT
        room.phase_started_at = time.time()
        room.bump_version()


@room_lock_guard
def place_guess(room_id: str, player_id: str, lat: float, lon: float) -> None:
    room = db.get_room(room_id)
    _validate_player(room, player_id)
    if room.phase != Phase.GUESS:
        raise PhaseError("WRONG_PHASE")
    if room.player_answered.get(player_id):
        return
    room.player_coord[player_id] = (lat, lon)
    room.bump_version()
    db.add_debug_log(room_id, "info", f"{player_id} placed guess ({lat:.3f}, {lon:.3f})")


@room_lock_guard
def submit(room_id: str, player_id: str) -> None:
    room = db.get_room(room_id)
    _validate_player(room, player_id)
    if room.phase != Phase.GUESS:
        raise PhaseError("WRONG_PHASE")
    if room.player_answered.get(player_id):
        return
    if room.player_coord.get(player_id) is None:
        raise GameError("NO_GUESS", 400)
    room.player_answered[player_id] = True
    room.bump_version()
    _emit(room_id, "player_submitted")
    db.add_debug_log(room_id, "info", f"{player_id} submitted")
    if all(room.player_answered[pid] for pid in room.player_ids):
        _enter_reveal(room_id)


@room_lock_guard
def agree_next(room_id: str, player_id: str) -> None:
    room = db.get_room(room_id)
    _validate_player(room, player_id)
    if room.phase != Phase.AGREE_NEXT:
        raise PhaseError("WRONG_PHASE")
    if room.player_ready_next.get(player_id):
        return
    room.player_ready_next[player_id] = True
    room.bump_version()
    if all(room.player_ready_next[pid] for pid in room.player_ids):
        _advance_round(room_id)


@room_lock_guard
def register_connection(room_id: str, player_id: str, connection_id: str) -> None:
    room = db.get_room(room_id)
    if player_id not in room.player_ids:
        return
    room.player_connections.setdefault(player_id, set()).add(connection_id)
    room.connection_seen.setdefault(player_id, {})[connection_id] = time.time()
    room.disconnect_since.pop(player_id, None)
    if not room.player_connected.get(player_id):
        room.player_connected[player_id] = True
        room.bump_version()
        _emit(room_id, "player_status")


@room_lock_guard
def exit_connection(room_id: str, player_id: str, connection_id: str) -> None:
    room = db.get_room(room_id)
    if player_id not in room.player_ids:
        return
    conns = room.player_connections.get(player_id, set())
    conns.discard(connection_id)
    room.player_connections[player_id] = conns
    room.connection_seen.setdefault(player_id, {}).pop(connection_id, None)
    if not conns:
        room.disconnect_since.setdefault(player_id, time.time())


@room_lock_guard
def prune_connections(room_id: str) -> None:
    room = db.get_room(room_id)
    now = time.time()
    grace = get_config().get("connection", {}).get("reconnect_grace_seconds", 60)
    for player_id in room.player_ids:
        seen = room.connection_seen.setdefault(player_id, {})
        last_activity = max(seen.values(), default=now)
        for cid, timestamp in list(seen.items()):
            if now - timestamp > grace:
                seen.pop(cid, None)
                room.player_connections.setdefault(player_id, set()).discard(cid)
        conns = room.player_connections.get(player_id, set())
        if conns:
            continue
        since = room.disconnect_since.setdefault(player_id, last_activity)
        # A lease that expired already includes the full grace period.
        expired = room.player_connected.get(player_id) and now - since >= grace
        if expired:
            room.player_connected[player_id] = False
            room.bump_version()
            _emit(room_id, "player_status")


def _apply_guess_timeout(room_id: str) -> None:
    room = db.get_room(room_id)
    key = (room.round_index, Phase.GUESS.value)
    if room.last_timeout_applied == key:
        return
    room.last_timeout_applied = key
    for pid in room.player_ids:
        if not room.player_answered.get(pid):
            if room.player_coord.get(pid) is None:
                room.player_coord[pid] = (0.5, 0.5)
            room.player_answered[pid] = True
    room.bump_version()
    _enter_reveal(room_id)


def _apply_agree_timeout(room_id: str) -> None:
    room = db.get_room(room_id)
    key = (room.round_index, Phase.AGREE_NEXT.value)
    if room.last_timeout_applied == key:
        return
    room.last_timeout_applied = key
    for pid in room.player_ids:
        if not room.player_ready_next.get(pid):
            room.player_ready_next[pid] = True
    room.bump_version()
    _advance_round(room_id)


def _enter_reveal(room_id: str) -> None:
    room = db.get_room(room_id)
    if room.phase not in (Phase.GUESS, Phase.REVEAL):
        return
    if room.last_damage_applied_round == room.round_index and room.phase == Phase.REVEAL:
        return

    room.phase = Phase.REVEAL
    question = db.get_current_question(room_id)
    answer_coord = db.loc_db.get(question.location)
    if answer_coord is None:
        answer_coord = (0.5, 0.5)

    distances: Dict[str, float] = {}
    normalized_distances: Dict[str, float] = {}
    distance_scale = float(db.room_scoring_config(room).get("distance_scale", 1.0))
    for pid in room.player_ids:
        coord = room.player_coord.get(pid)
        if coord is not None:
            raw = calc.distance(coord, answer_coord)
            normalized_distances[pid] = raw
            distances[pid] = raw * distance_scale
        else:
            normalized_distances[pid] = 0.0
            distances[pid] = 0.0

    dmg_mult = db.get_dmg_mult(room_id)
    ctx: SettlementContext = {
        "distances": distances,
        "normalized_distances": normalized_distances,
        "round_index": room.round_index,
        "dmg_mult": dmg_mult,
        "config": room.room_config,
        "player_ids": list(room.player_ids),
    }

    game_mode = get_game_mode(room.room_config)
    if game_mode == "points":
        scoring_fn = get_scoring_fn(get_scoring_fn_name(room.room_config))
        round_scores = scoring_fn(ctx)
        for pid in room.player_ids:
            pts = round_scores.get(pid, 0.0)
            room.player_round_score[pid] = pts
            room.player_score[pid] = room.player_score.get(pid, 0) + pts
        db.add_debug_log(
            room_id, "info", f"Reveal round {room.round_index + 1}: {round_scores}"
        )
    else:
        damage_fn = get_damage_fn(get_damage_fn_name(room.room_config))
        damages = damage_fn(ctx)
        for pid in room.player_ids:
            dmg = damages.get(pid, 0.0)
            room.player_round_damage[pid] = dmg
            room.player_hp[pid] = room.player_hp.get(pid, 0) - dmg
        for pid in room.player_ids:
            if room.player_hp.get(pid, 0) > 0:
                room.rounds_survived[pid] = room.rounds_survived.get(pid, 0) + 1
        db.add_debug_log(
            room_id, "info", f"Reveal round {room.round_index + 1}: {damages}"
        )

    room.last_damage_applied_round = room.round_index
    room.bump_version()
    _emit(room_id, "reveal")
    _advance_from_reveal(room_id)


def _advance_round(room_id: str) -> None:
    room = db.get_room(room_id)
    if not db.has_next_round(room_id):
        _enter_game_over(room_id)
        return
    if _should_end_game(room):
        _enter_game_over(room_id)
        return

    room.round_index += 1
    room.reset_round_fields()
    room.phase = Phase.GUESS
    room.last_timeout_applied = None
    try:
        db.get_current_question(room_id)
    except StopIteration:
        _enter_game_over(room_id)
        return
    _afk_auto_guess(room)
    if all(room.player_answered.get(pid) for pid in room.player_ids):
        _enter_reveal(room_id)
        return
    room.bump_version()
    _emit(room_id, "next_round")


def _afk_auto_guess(room: RoomState) -> None:
    for pid in room.player_ids:
        if not room.player_connected.get(pid, True):
            room.player_coord[pid] = (0.5, 0.5)
            room.player_answered[pid] = True


def _should_end_game(room: RoomState) -> bool:
    if get_game_mode(room.room_config) == "points":
        return False
    cfg = _room_scoring(room)
    if cfg.get("end_on_hp_zero", True):
        if any(room.player_hp.get(pid, 0) <= 0 for pid in room.player_ids):
            return True
    alive = [pid for pid in room.player_ids if room.player_hp.get(pid, 0) > 0]
    if len(alive) <= 1 and len(room.player_ids) > 1:
        return True
    return False


def _enter_game_over(room_id: str) -> None:
    room = db.get_room(room_id)
    if room.phase == Phase.GAME_OVER:
        return
    room.phase = Phase.GAME_OVER
    room.rankings = _compute_rankings(room)
    room.bump_version()
    _emit(room_id, "game_over")
    db.add_debug_log(room_id, "info", "Game over")


def _compute_rankings(room: RoomState) -> List[dict]:
    tie_threshold = _room_scoring(room).get("tie_threshold", 0.1)
    if get_game_mode(room.room_config) == "points":
        entries = []
        for pid in room.player_ids:
            entries.append(
                {
                    "player_id": pid,
                    "score": room.player_score.get(pid, 0),
                }
            )
        return assign_score_ranks(entries, tie_threshold)

    entries = []
    for pid in room.player_ids:
        entries.append(
            {
                "player_id": pid,
                "hp": room.player_hp.get(pid, 0),
                "rounds_survived": room.rounds_survived.get(pid, 0),
            }
        )
    return assign_standings_ranks(entries, tie_threshold)


def _validate_player(room: RoomState, player_id: str) -> None:
    if player_id not in room.player_ids:
        raise GameError("NOT_IN_ROOM", 403)


@room_lock_guard
def force_reveal(room_id: str) -> None:
    if not is_debug():
        raise GameError("WRONG_PHASE", 409)
    room = db.get_room(room_id)
    for pid in room.player_ids:
        if room.player_coord.get(pid) is None:
            room.player_coord[pid] = (0.5, 0.5)
        room.player_answered[pid] = True
    _enter_reveal(room_id)


@room_lock_guard
def debug_next_round(room_id: str) -> None:
    if not is_debug():
        raise GameError("WRONG_PHASE", 409)
    room = db.get_room(room_id)
    if db.has_next_round(room_id):
        room.round_index += 1
        room.reset_round_fields()
        room.phase = Phase.GUESS
        db.get_current_question(room_id)
        _afk_auto_guess(room)
        room.bump_version()
        _emit(room_id, "next_round")


@room_lock_guard
def debug_prev_round(room_id: str) -> None:
    if not is_debug():
        raise GameError("WRONG_PHASE", 409)
    room = db.get_room(room_id)
    if db.has_prev_round(room_id):
        room.round_index -= 1
        room.reset_round_fields()
        room.phase = Phase.GUESS
        room.last_damage_applied_round = None
        room.bump_version()


class GameError(Exception):
    def __init__(self, code: str, http_status: int = 400, message: str | None = None):
        self.code = code
        self.http_status = http_status
        self.message = message or code


class PhaseError(GameError):
    def __init__(self, code: str = "WRONG_PHASE"):
        super().__init__(code, 409)
