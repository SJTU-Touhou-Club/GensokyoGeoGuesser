from __future__ import annotations

import queue
import threading
from typing import Dict, List

_event_queues: Dict[str, List[queue.Queue]] = {}
_lock = threading.Lock()


def subscribe(room_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=1)
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


def broadcast(room_id: str, event_name: str) -> None:
    with _lock:
        queues = list(_event_queues.get(room_id, []))
    for q in queues:
        try:
            q.put_nowait(event_name)
        except queue.Full:
            pass


def event_stream(q: queue.Queue, room_id: str | None = None):
    from neo.config import get_config

    interval = get_config().get("connection", {}).get("heartbeat_seconds", 1)
    try:
        yield "data: sync\n\n"
        while True:
            try:
                msg = q.get(timeout=interval)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield "event: ping\ndata: {}\n\n"
    finally:
        if room_id is not None:
            unsubscribe(room_id, q)
