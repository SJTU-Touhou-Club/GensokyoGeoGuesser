from __future__ import annotations

import random
from typing import Callable, Iterable, Optional, Sequence, Tuple

from pydantic import BaseModel

from neo.config import get_config

Coord = Tuple[float, float]
Loc = str
Category = str

# Touhou-style difficulty order: Easy < Normal < Hard < Lunatic.
DIFFICULTY_ORDER: Tuple[str, ...] = ("E", "N", "H", "L")
DIFFICULTY_RANK = {cat: i for i, cat in enumerate(DIFFICULTY_ORDER)}


class Question(BaseModel):
    image_path: str
    location: Loc
    category: Category
    comment: Optional[str] = None


def room_seed(room_id: str) -> int:
    return sum(ord(c) for c in room_id)


def difficulty_rank(category: str) -> int:
    """Return ordered rank, or -1 for unknown codes."""
    return DIFFICULTY_RANK.get(category, -1)


def difficulty_at_most(question_cat: str, max_cat: str) -> bool:
    """True when question tier is known and ≤ selected max difficulty."""
    q_rank = difficulty_rank(question_cat)
    max_rank = difficulty_rank(max_cat)
    if q_rank < 0 or max_rank < 0:
        return False
    return q_rank <= max_rank


def known_difficulty(category: str) -> bool:
    return category in DIFFICULTY_RANK


def exposed_difficulties() -> Sequence[str]:
    cfg = get_config().get("difficulty", {})
    choices = cfg.get("choices") or list(DIFFICULTY_ORDER)
    return [c for c in choices if c in DIFFICULTY_RANK]


def default_difficulty() -> str:
    cfg = get_config().get("difficulty", {})
    default = cfg.get("default", "N")
    exposed = exposed_difficulties()
    if default in exposed:
        return default
    if exposed:
        return exposed[0]
    return "N"


def round_bounds() -> tuple[int, int]:
    cfg = get_config().get("rounds", {})
    return int(cfg.get("min", 1)), int(cfg.get("max", 20))


def default_rounds() -> int:
    cfg = get_config().get("rounds", {})
    lo, hi = round_bounds()
    value = int(cfg.get("default", cfg.get("max_rounds", 5)))
    return max(lo, min(hi, value))


def get_category_sampler(seed: int, max_rounds: int | None = None) -> Iterable[Category]:
    """Legacy per-round category stream (unused by cumulative difficulty filter)."""
    rounds = max_rounds or get_config()["rounds"]["max_rounds"]
    categories = ["E"] * rounds
    return iter(categories)


def get_question_sampler(seed: int) -> Iterable[int]:
    rng = random.Random(seed)

    def sampler():
        while True:
            yield rng.randint(0, 1_000_000)

    return sampler()


def get_dmg_mult_selector(seed: int) -> Callable[[int], float]:
    schedule = get_config()["dmg_mult_schedule"]
    mults: list[float] = []
    for entry in schedule:
        mults.extend([float(entry["mult"])] * int(entry["rounds"]))
    return lambda idx: mults[idx] if idx < len(mults) else mults[-1]
