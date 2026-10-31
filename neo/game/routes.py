from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from neo.config import is_debug
from neo.game import database as db
from neo.game import engine
from neo.game import sse as game_sse
from neo.game.database import Phase
from neo.game.engine import GameError, PhaseError
from neo.game.state_builder import build_state
from neo.lobby.store import get_lobby_store

bp = Blueprint("game", __name__)

_spectators: dict[str, set[str]] = {}


def register_spectator(room_id: str, player_id: str) -> None:
    _spectators.setdefault(room_id, set()).add(player_id)


def _error(message: str, code: str, status: int):
    return jsonify({"error": message, "code": code}), status


def _parse_query():
    room_id = request.args.get("room")
    player_id = request.args.get("player_id")
    if not room_id:
        return None, None, _error("Missing room id", "MISSING_ROOM", 400)
    if not player_id:
        return None, None, _error("Missing player id", "MISSING_PLAYER_ID", 400)
    return room_id, player_id, None


def _is_spectator(room_id: str, player_id: str) -> bool:
    return player_id in _spectators.get(room_id, set())


def _is_observe() -> bool:
    return request.args.get("observe") == "1"


def _get_state_response(room_id: str, player_id: str):
    if not db.room_exists(room_id):
        return _error("Room not found", "ROOM_NOT_FOUND", 404)
    observe = _is_observe() or _is_spectator(room_id, player_id)
    room = db.get_room(room_id)
    if not observe and player_id not in room.player_ids:
        if _is_spectator(room_id, player_id):
            observe = True
        else:
            return _error("Player not in room", "NOT_IN_ROOM", 403)
    engine.check_timeouts(room_id)
    state = build_state(room_id, player_id, observe_mode=observe)
    if room.phase == Phase.GAME_OVER:
        store = get_lobby_store()
        store.delete_room(room_id)
    return jsonify(state)


@bp.route("/api/state")
def get_state():
    room_id, player_id, err = _parse_query()
    if err:
        return err
    connection_id = request.args.get("connection_id")
    if connection_id and not _is_observe():
        try:
            engine.register_connection(room_id, player_id, connection_id)
        except KeyError:
            return _error("Room not found", "ROOM_NOT_FOUND", 404)
    return _get_state_response(room_id, player_id)


@bp.route("/api/place_guess", methods=["POST"])
def place_guess():
    room_id, player_id, err = _parse_query()
    if err:
        return err
    if _is_spectator(room_id, player_id) or _is_observe():
        return _error("Spectators cannot mutate state", "SPECTATOR_READONLY", 403)
    data = request.get_json(silent=True) or {}
    try:
        engine.check_timeouts(room_id)
        engine.place_guess(room_id, player_id, data.get("lat"), data.get("lon"))
    except KeyError:
        return _error("Room not found", "ROOM_NOT_FOUND", 404)
    except PhaseError as e:
        return _error(e.message or e.code, e.code, e.http_status)
    except GameError as e:
        return _error(e.message or e.code, e.code, e.http_status)
    return _get_state_response(room_id, player_id)


@bp.route("/api/submit", methods=["POST"])
def submit():
    room_id, player_id, err = _parse_query()
    if err:
        return err
    if _is_spectator(room_id, player_id) or _is_observe():
        return _error("Spectators cannot mutate state", "SPECTATOR_READONLY", 403)
    try:
        engine.check_timeouts(room_id)
        engine.submit(room_id, player_id)
    except KeyError:
        return _error("Room not found", "ROOM_NOT_FOUND", 404)
    except PhaseError as e:
        return _error(e.message or e.code, e.code, e.http_status)
    except GameError as e:
        return _error(e.message or e.code, e.code, e.http_status)
    return _get_state_response(room_id, player_id)


@bp.route("/api/agree_next", methods=["POST"])
def agree_next():
    room_id, player_id, err = _parse_query()
    if err:
        return err
    if _is_spectator(room_id, player_id) or _is_observe():
        return _error("Spectators cannot mutate state", "SPECTATOR_READONLY", 403)
    try:
        engine.check_timeouts(room_id)
        engine.agree_next(room_id, player_id)
    except KeyError:
        return _error("Room not found", "ROOM_NOT_FOUND", 404)
    except PhaseError as e:
        return _error(e.message or e.code, e.code, e.http_status)
    return _get_state_response(room_id, player_id)


@bp.route("/api/exit", methods=["POST"])
def exit_game():
    room_id, player_id, err = _parse_query()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    connection_id = data.get("connection_id") or request.args.get("connection_id")
    if not connection_id:
        return _error("Missing connection_id", "MISSING_PLAYER_ID", 400)
    try:
        engine.exit_connection(room_id, player_id, connection_id)
    except KeyError:
        return _error("Room not found", "ROOM_NOT_FOUND", 404)
    return jsonify({"ok": True})


@bp.route("/api/reveal", methods=["GET"])
def reveal():
    if not is_debug():
        return _error("Debug only", "WRONG_PHASE", 403)
    room_id, player_id, err = _parse_query()
    if err:
        return err
    try:
        engine.force_reveal(room_id)
    except KeyError:
        return _error("Room not found", "ROOM_NOT_FOUND", 404)
    except GameError as e:
        return _error(e.message or e.code, e.code, e.http_status)
    return _get_state_response(room_id, player_id)


@bp.route("/api/next_round", methods=["POST"])
def next_round():
    if not is_debug():
        return _error("Debug only", "WRONG_PHASE", 403)
    room_id, player_id, err = _parse_query()
    if err:
        return err
    try:
        engine.debug_next_round(room_id)
    except KeyError:
        return _error("Room not found", "ROOM_NOT_FOUND", 404)
    return _get_state_response(room_id, player_id)


@bp.route("/api/prev_round", methods=["POST"])
def prev_round():
    if not is_debug():
        return _error("Debug only", "WRONG_PHASE", 403)
    room_id, player_id, err = _parse_query()
    if err:
        return err
    try:
        engine.debug_prev_round(room_id)
    except KeyError:
        return _error("Room not found", "ROOM_NOT_FOUND", 404)
    return _get_state_response(room_id, player_id)


@bp.route("/events/<room_id>")
def events(room_id: str):
    q = game_sse.subscribe(room_id)
    response = Response(game_sse.event_stream(q), mimetype="text/event-stream")
    response.call_on_close(lambda: game_sse.unsubscribe(room_id, q))
    return response
