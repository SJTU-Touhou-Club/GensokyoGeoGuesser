from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from neo.lobby import service as lobby_service
from neo.lobby import sse as lobby_sse
from neo.lobby.service import LobbyError

bp = Blueprint("lobby", __name__)


def _err(e: LobbyError):
    return jsonify({"error": e.message, "code": e.code}), e.http_status


@bp.route("/api/lobby/join", methods=["POST"])
def join():
    data = request.get_json(silent=True) or {}
    try:
        result = lobby_service.join(
            room_id=data.get("room_id"),
            player_id=data.get("player_id", ""),
            connection_id=data.get("connection_id", ""),
            min_players=data.get("min_players"),
            max_players=data.get("max_players"),
            rounds=data.get("rounds"),
            difficulty=data.get("difficulty"),
            scoring_strategy=data.get("scoring_strategy"),
        )
        return jsonify(result)
    except LobbyError as e:
        return _err(e)


@bp.route("/api/lobby/observe", methods=["POST"])
def observe():
    data = request.get_json(silent=True) or {}
    try:
        result = lobby_service.observe(
            room_id=data.get("room_id", ""),
            player_id=data.get("player_id", ""),
            connection_id=data.get("connection_id", ""),
        )
        return jsonify(result)
    except LobbyError as e:
        return _err(e)


@bp.route("/api/lobby/leave", methods=["POST"])
def leave():
    data = request.get_json(silent=True) or {}
    return jsonify(
        lobby_service.leave(
            data.get("room_id", ""),
            data.get("player_id", ""),
            data.get("connection_id", ""),
        )
    )


@bp.route("/api/lobby/start", methods=["POST"])
def start():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            lobby_service.start(
                data.get("room_id", ""), data.get("player_id", ""), data.get("connection_id"),
            )
        )
    except LobbyError as e:
        return _err(e)


@bp.route("/api/lobby/update_settings", methods=["POST"])
def update_settings():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            lobby_service.update_room_settings(
                data.get("room_id", ""),
                data.get("player_id", ""),
                data.get("min_players"),
                data.get("max_players"),
                rounds=data.get("rounds"),
                difficulty=data.get("difficulty"),
                scoring_strategy=data.get("scoring_strategy"),
                connection_id=data.get("connection_id"),
            )
        )
    except LobbyError as e:
        return _err(e)


@bp.route("/api/lobby/room_status")
def room_status():
    room_id = request.args.get("room_id")
    if not room_id:
        return jsonify({"error": "Missing room_id", "code": "MISSING_ROOM"}), 400
    try:
        return jsonify(lobby_service.room_status(room_id))
    except LobbyError as e:
        return _err(e)


@bp.route("/api/lobby/heartbeat", methods=["POST"])
def heartbeat():
    data = request.get_json(silent=True) or {}
    return jsonify(
        lobby_service.heartbeat(
            data.get("room_id", ""),
            data.get("player_id", ""),
            data.get("connection_id", ""),
        )
    )


@bp.route("/events/lobby/<room_id>")
def events(room_id: str):
    q = lobby_sse.subscribe(room_id)
    response = Response(
        lobby_sse.event_stream(
            room_id, q, request.args.get("player_id"), request.args.get("connection_id"),
        ),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache, no-store"
    response.headers["X-Accel-Buffering"] = "no"
    response.call_on_close(lambda: lobby_sse.unsubscribe(room_id, q))
    return response
