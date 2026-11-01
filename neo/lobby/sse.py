from __future__ import annotations

import json
import queue
import threading
from typing import Dict, List, Optional

from neo.lobby import service as lobby_service
from neo.lobby.store import get_lobby_store

_event_queues: Dict[str, List[queue.Queue]] = {}
_lock = threading.Lock()


def subscribe(room_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=32)
    with _lock:
        _event_queues.setdefault(room_id, []).append(q)
    return q


def unsubscribe(room_id: str, q: queue.Queue) -> None:
    with _lock:
        queues = _event_queues.get(room_id, [])
        if q in queues:
            queues.remove(q)
        if not queues:
            _event_queues.pop(room_id, None)


def broadcast(room_id: str, event: str, payload: Optional[dict] = None) -> None:
    with _lock:
        queues = list(_event_queues.get(room_id, []))
    data = json.dumps(payload) if payload is not None else event
    for q in queues:
        try:
            if payload is not None:
                q.put_nowait(("event", event, data))
            else:
                q.put_nowait(("raw", event, None))
        except queue.Full:
            # Heartbeat snapshots recover a slow client without unbounded buffering.
            pass


def set_broadcast_hook() -> None:
    lobby_service.set_lobby_broadcast(broadcast)


def event_stream(
    room_id: str, q: queue.Queue,
    player_id: str | None = None, connection_id: str | None = None,
):
    from neo.config import get_config

    interval = get_config().get("connection", {}).get("heartbeat_seconds", 1)
    store = get_lobby_store()

    def membership_event():
        if connection_id is None:
            return None
        with store.acquire_lock(room_id):
            room = store.get_room(room_id)
            members = [m for m in room.players + room.spectators if m.player_id == player_id] if room else []
            if not members:
                return "event: membership_expired\ndata: {}\n\n"
            if not any(connection_id in m.connection_ids for m in members):
                return f"event: connection_replaced\ndata: {json.dumps({'player_id': player_id})}\n\n"
            return None
    try:
        with store.acquire_lock(room_id):
            initial_event = membership_event()
            room = store.get_room(room_id)
            snapshot = room.to_dict() if room else None
            if snapshot:
                snapshot["countdown_remaining_seconds"] = room.countdown_remaining_seconds()
        if initial_event:
            yield initial_event
            return
        if snapshot:
            yield f"event: lobby_snapshot\ndata: {json.dumps(snapshot)}\n\n"
        while True:
            try:
                kind, event, data = q.get(timeout=interval)
                if membership := membership_event():
                    yield membership
                    return
                if kind == "event":
                    yield f"event: {event}\ndata: {data}\n\n"
                else:
                    yield f"data: {event}\n\n"
            except queue.Empty:
                if membership := membership_event():
                    yield membership
                    return
                yield "event: ping\ndata: {}\n\n"
    finally:
        unsubscribe(room_id, q)
