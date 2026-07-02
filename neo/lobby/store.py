from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class LobbyStatus(str, Enum):
    WAITING = "WAITING"
    COUNTDOWN = "COUNTDOWN"
    STARTING = "STARTING"
    IN_GAME = "IN_GAME"


@dataclass
class LobbyPlayer:
    player_id: str
    connection_ids: Set[str] = field(default_factory=set)
    connected: bool = True
    joined_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "connection_ids": list(self.connection_ids),
            "connected": self.connected,
            "joined_at": self.joined_at,
        }


@dataclass
class LobbySpectator:
    player_id: str
    connection_ids: Set[str] = field(default_factory=set)
    last_heartbeat: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "connection_ids": list(self.connection_ids),
        }


@dataclass
class LobbyRoom:
    room_id: str
    status: LobbyStatus = LobbyStatus.WAITING
    host_id: str = ""
    min_players: int = 2
    max_players: int = 8
    countdown_deadline: Optional[float] = None
    players: List[LobbyPlayer] = field(default_factory=list)
    spectators: List[LobbySpectator] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def player_ids_ordered(self) -> List[str]:
        return [p.player_id for p in sorted(self.players, key=lambda p: p.joined_at)]

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "status": self.status.value,
            "host_id": self.host_id,
            "min_players": self.min_players,
            "max_players": self.max_players,
            "countdown_deadline": self.countdown_deadline,
            "players": [
                {
                    "player_id": p.player_id,
                    "is_host": p.player_id == self.host_id,
                    "connected": p.connected,
                }
                for p in self.players
            ],
            "spectators": [s.to_dict() for s in self.spectators],
            "created_at": self.created_at,
        }

    def countdown_remaining_seconds(self) -> Optional[int]:
        if self.countdown_deadline is None:
            return None
        return max(0, int(self.countdown_deadline - time.time()))


class LobbyStore:
    def get_room(self, room_id: str) -> Optional[LobbyRoom]:
        raise NotImplementedError

    def save_room(self, room: LobbyRoom) -> None:
        raise NotImplementedError

    def delete_room(self, room_id: str) -> None:
        raise NotImplementedError

    def get_player_room(self, player_id: str) -> Optional[str]:
        raise NotImplementedError

    def set_player_room(self, player_id: str, room_id: Optional[str], role: str) -> None:
        raise NotImplementedError

    def quick_pool_add(self, room_id: str) -> None:
        raise NotImplementedError

    def quick_pool_list(self) -> List[str]:
        raise NotImplementedError

    def quick_pool_remove(self, room_id: str) -> None:
        raise NotImplementedError

    def acquire_lock(self, room_id: str):
        raise NotImplementedError


class InMemoryLobbyStore(LobbyStore):
    def __init__(self):
        self._rooms: Dict[str, LobbyRoom] = {}
        self._player_index: Dict[str, tuple[str, str]] = {}
        self._quick_pool: Set[str] = set()
        self._locks: Dict[str, threading.RLock] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, room_id: str) -> threading.RLock:
        with self._global_lock:
            if room_id not in self._locks:
                self._locks[room_id] = threading.RLock()
            return self._locks[room_id]

    def acquire_lock(self, room_id: str):
        return self._get_lock(room_id)

    def get_room(self, room_id: str) -> Optional[LobbyRoom]:
        return self._rooms.get(room_id)

    def save_room(self, room: LobbyRoom) -> None:
        self._rooms[room.room_id] = room

    def delete_room(self, room_id: str) -> None:
        room = self._rooms.pop(room_id, None)
        if room:
            for p in room.players:
                self._player_index.pop(p.player_id, None)
            for s in room.spectators:
                self._player_index.pop(s.player_id, None)
        self._quick_pool.discard(room_id)

    def get_player_room(self, player_id: str) -> Optional[str]:
        entry = self._player_index.get(player_id)
        return entry[0] if entry else None

    def set_player_room(self, player_id: str, room_id: Optional[str], role: str) -> None:
        if room_id is None:
            self._player_index.pop(player_id, None)
        else:
            self._player_index[player_id] = (room_id, role)

    def quick_pool_add(self, room_id: str) -> None:
        self._quick_pool.add(room_id)

    def quick_pool_list(self) -> List[str]:
        return list(self._quick_pool)

    def quick_pool_remove(self, room_id: str) -> None:
        self._quick_pool.discard(room_id)


_store: Optional[InMemoryLobbyStore] = None


def get_lobby_store() -> InMemoryLobbyStore:
    global _store
    if _store is None:
        _store = InMemoryLobbyStore()
    return _store
