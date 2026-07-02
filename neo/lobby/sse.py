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
    q: queue.Queue = queue.Queue()
    with _lock:
        _event_queues.setdefault(room_id, []).append(q)
    return q


def unsubscribe(room_id: str, q: queue.Queue) -> None:
    with _lock:
        queues = _event_queues.get(room_id, [])
        if q in queues:
            queues.remove(q)


def broadcast(room_id: str, event: str, payload: Optional[dict] = None) -> None:
    with _lock:
        queues = list(_event_queues.get(room_id, []))
    data = json.dumps(payload) if payload is not None else event
    for q in queues:
        try:
            if payload is not None:
                q.put(("event", event, data))
            else:
                q.put(("raw", event, None))
        except Exception:
            pass


def set_broadcast_hook() -> None:
    lobby_service.set_lobby_broadcast(broadcast)


def event_stream(room_id: str, q: queue.Queue):
    store = get_lobby_store()
    room = store.get_room(room_id)
    if room:
        snapshot = room.to_dict()
        snapshot["countdown_remaining_seconds"] = room.countdown_remaining_seconds()
        yield f"event: lobby_snapshot\ndata: {json.dumps(snapshot)}\n\n"

    while True:
        item = q.get()
        kind, event, data = item
        if kind == "event":
            yield f"event: {event}\ndata: {data}\n\n"
        else:
            yield f"data: {event}\n\n"
