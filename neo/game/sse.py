from __future__ import annotations

import queue
import threading
from typing import Dict, List

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


def broadcast(room_id: str, event_name: str) -> None:
    with _lock:
        queues = list(_event_queues.get(room_id, []))
    for q in queues:
        try:
            q.put(event_name)
        except Exception:
            pass


def event_stream(q: queue.Queue):
    while True:
        msg = q.get()
        yield f"data: {msg}\n\n"
