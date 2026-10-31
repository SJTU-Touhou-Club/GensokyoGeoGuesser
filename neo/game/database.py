from __future__ import annotations

import functools
import inspect
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from neo.config import data_dir, get_config, get_scoring_mode_config, is_scoring_mode_body
from neo.defs import (
    Coord,
    Question,
    difficulty_at_most,
    get_category_sampler,
    get_dmg_mult_selector,
    get_question_sampler,
    known_difficulty,
    room_seed,
)

que_image_dir = "dataset/"

loc_db: Dict[str, Coord] = {}
que_db: Dict[int, Question] = {}
rooms: Dict[str, "RoomState"] = {}


class Phase(str, Enum):
    GUESS = "guess"
    REVEAL = "reveal"
    AGREE_NEXT = "agree_next"
    GAME_OVER = "game_over"


@dataclass
class RoomState:
    room_id: str
    room_config: dict
    player_ids: List[str] = field(default_factory=list)
    round_index: int = 0
    phase: Phase = Phase.GUESS
    phase_started_at: float = field(default_factory=time.time)
    que_history: List[int] = field(default_factory=list)
    player_hp: Dict[str, float] = field(default_factory=dict)
    player_coord: Dict[str, Optional[Coord]] = field(default_factory=dict)
    player_answered: Dict[str, bool] = field(default_factory=dict)
    player_ready_next: Dict[str, bool] = field(default_factory=dict)
    player_round_damage: Dict[str, Optional[float]] = field(default_factory=dict)
    player_score: Dict[str, float] = field(default_factory=dict)
    player_round_score: Dict[str, Optional[float]] = field(default_factory=dict)
    player_slot: Dict[str, int] = field(default_factory=dict)
    player_connected: Dict[str, bool] = field(default_factory=dict)
    player_connections: Dict[str, Set[str]] = field(default_factory=dict)
    rounds_survived: Dict[str, int] = field(default_factory=dict)
    last_damage_applied_round: Optional[int] = None
    last_timeout_applied: Optional[tuple] = None
    state_version: int = 0
    rankings: Optional[List[dict]] = None
    debug_log: List[dict] = field(default_factory=list)
    category_sampler: object = None
    question_sampler: object = None
    dmg_mult_selector: object = None
    connection_seen: dict[str, dict[str, float]] = field(default_factory=dict)
    disconnect_since: dict[str, float] = field(default_factory=dict)
    action_acks: dict[tuple[str, str, str], dict] = field(default_factory=dict)
    action_sequences: dict[tuple[str, str, int], int] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def bump_version(self) -> None:
        self.state_version += 1

    def reset_round_fields(self) -> None:
        for pid in self.player_ids:
            self.player_coord[pid] = None
            self.player_answered[pid] = False
            self.player_ready_next[pid] = False
            self.player_round_damage[pid] = None
            self.player_round_score[pid] = None
        self.phase_started_at = time.time()


def room_lock_guard(func):
    sig = inspect.signature(func)
    param_names = list(sig.parameters.keys())
    room_idx = param_names.index("room_id") if "room_id" in param_names else 0

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        room_id = kwargs.get("room_id")
        if room_id is None and room_idx < len(args):
            room_id = args[room_idx]
        room = get_room(room_id)
        with room.lock:
            return func(*args, **kwargs)

    return wrapper


def get_room(room_id: str) -> RoomState:
    if room_id not in rooms:
        raise KeyError(f"Room not found: {room_id}")
    return rooms[room_id]


def room_exists(room_id: str) -> bool:
    return room_id in rooms


def delete_room(room_id: str) -> None:
    rooms.pop(room_id, None)


def _data_sheet_paths() -> tuple[str, str]:
    cfg = get_config().get("data_files", {})
    loc_name = cfg.get("locations", "locations.csv")
    que_name = cfg.get("questions", "questions.csv")
    return str(data_dir() / loc_name), str(data_dir() / que_name)


def room_max_rounds(room: RoomState) -> int:
    rounds = room.room_config.get("rounds")
    if rounds is not None:
        return int(rounds)
    return int(get_config()["rounds"]["max_rounds"])


def room_difficulty(room: RoomState) -> str:
    return str(room.room_config.get("difficulty") or get_config().get("difficulty", {}).get("default", "N"))


def room_scoring_config(room: RoomState) -> dict:
    scoring = room.room_config.get("scoring")
    if is_scoring_mode_body(scoring):
        return scoring
    strategy = room.room_config.get("scoring_strategy")
    try:
        return get_scoring_mode_config(strategy)
    except KeyError:
        return get_scoring_mode_config()


def init_database() -> None:
    loc_db.clear()
    que_db.clear()
    loc_sheet_path, que_sheet_path = _data_sheet_paths()
    with open(loc_sheet_path, encoding="utf-8-sig") as loc_file:
        for line in loc_file:
            line = line.strip()
            if not line:
                continue
            loc, lat_str, lon_str = line.split(",")
            loc_db[loc] = (float(lat_str), float(lon_str))

    with open(que_sheet_path, encoding="utf-8-sig") as que_file:
        for line in que_file:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            id_str, image_filename, loc, category = parts[:4]
            try:
                qid = int(id_str)
            except ValueError:
                # Skip header rows (e.g. ID,图片名称,...).
                continue
            if not known_difficulty(category):
                continue
            comment = parts[4] if len(parts) >= 5 and parts[4] else None
            image_path = os.path.join(que_image_dir, image_filename)
            que_db[qid] = Question(
                image_path=image_path,
                location=loc,
                category=category,
                comment=comment,
            )


def questions_for_difficulty(max_cat: str) -> List[int]:
    return [
        idx
        for idx, q in que_db.items()
        if difficulty_at_most(q.category, max_cat)
    ]


def init_room(room_id: str, player_ids: List[str], room_config: dict) -> RoomState:
    cfg = get_config()
    seed = room_seed(room_id)
    max_rounds = int(room_config.get("rounds") or cfg["rounds"]["max_rounds"])
    max_hp = cfg["rounds"]["max_hp"]
    difficulty = str(room_config.get("difficulty") or cfg.get("difficulty", {}).get("default", "N"))
    room_config = dict(room_config)
    room_config.setdefault("rounds", max_rounds)
    room_config.setdefault("difficulty", difficulty)
    strategy = room_config.get("scoring_strategy")
    if not is_scoring_mode_body(room_config.get("scoring")):
        try:
            from neo.config import resolve_scoring_mode_name

            strategy = resolve_scoring_mode_name(strategy)
        except KeyError:
            from neo.config import default_scoring_mode

            strategy = default_scoring_mode()
        room_config["scoring_strategy"] = strategy
        room_config["scoring"] = get_scoring_mode_config(strategy)
    else:
        room_config.setdefault(
            "scoring_strategy", strategy or "default"
        )

    pool = questions_for_difficulty(difficulty)
    if not pool:
        raise RuntimeError(
            f"No questions available for difficulty <= {difficulty}."
        )
    if len(pool) < max_rounds:
        raise RuntimeError(
            f"Question pool ({len(pool)}) smaller than rounds ({max_rounds}) "
            f"for difficulty <= {difficulty}."
        )

    room = RoomState(
        room_id=room_id,
        room_config=room_config,
        player_ids=list(player_ids),
        category_sampler=get_category_sampler(seed, max_rounds),
        question_sampler=get_question_sampler(seed),
        dmg_mult_selector=get_dmg_mult_selector(seed),
    )
    for i, pid in enumerate(player_ids):
        room.player_hp[pid] = max_hp
        room.player_slot[pid] = i
        room.player_connected[pid] = True
        room.player_connections[pid] = set()
        room.rounds_survived[pid] = 0
        room.player_coord[pid] = None
        room.player_answered[pid] = False
        room.player_ready_next[pid] = False
        room.player_round_damage[pid] = None
        room.player_score[pid] = 0.0
        room.player_round_score[pid] = None

    room.round_index = 0
    room.phase = Phase.GUESS
    room.phase_started_at = time.time()
    room.state_version = 1
    rooms[room_id] = room
    sample_question(room_id)
    return room


@room_lock_guard
def sample_question(room_id: str) -> Question:
    room = get_room(room_id)
    try:
        max_cat = room_difficulty(room)
        valid_ques = [
            idx
            for idx, q in que_db.items()
            if difficulty_at_most(q.category, max_cat)
            and idx not in room.que_history
        ]
        if not valid_ques:
            raise RuntimeError(
                f"No more valid questions for difficulty <= {max_cat}."
            )
        idx = next(room.question_sampler) % len(valid_ques)
        idx = valid_ques[idx]
        room.que_history.append(idx)
        return que_db[idx]
    except StopIteration:
        raise StopIteration


@room_lock_guard
def get_question_at(target_index: int, room_id: str) -> Question:
    max_rounds = room_max_rounds(get_room(room_id))
    assert 0 <= target_index < max_rounds
    room = get_room(room_id)
    while len(room.que_history) <= target_index:
        try:
            sample_question(room_id)
        except StopIteration:
            raise RuntimeError("No more questions can be sampled.")
    room.round_index = target_index
    return que_db[room.que_history[target_index]]


def get_current_question(room_id: str) -> Question:
    room = get_room(room_id)
    return get_question_at(room.round_index, room_id)


def get_dmg_mult(room_id: str) -> float:
    room = get_room(room_id)
    return room.dmg_mult_selector(room.round_index)


def has_next_round(room_id: str) -> bool:
    room = get_room(room_id)
    return room.round_index + 1 < room_max_rounds(room)


def has_prev_round(room_id: str) -> bool:
    return get_room(room_id).round_index > 0


def add_debug_log(room_id: str, level: str, message: str) -> None:
    room = get_room(room_id)
    entry = {"time": time.time(), "level": level, "message": message}
    room.debug_log.append(entry)
    if len(room.debug_log) > 200:
        room.debug_log = room.debug_log[-200:]


@room_lock_guard
def next_question_image(room_id: str) -> str | None:
    room = get_room(room_id)
    if room.phase == Phase.GAME_OVER or not has_next_round(room_id):
        return None
    target = room.round_index + 1
    while len(room.que_history) <= target:
        sample_question(room_id)
    return que_db[room.que_history[target]].image_path
