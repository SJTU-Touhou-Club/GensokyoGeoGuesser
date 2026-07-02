from __future__ import annotations

import random
from typing import Callable, Iterable, Optional, Tuple

from pydantic import BaseModel

from neo.config import get_config

Coord = Tuple[float, float]
Loc = str
Category = str


class Question(BaseModel):
    image_path: str
    location: Loc
    category: Category
    comment: Optional[str] = None


def room_seed(room_id: str) -> int:
    return sum(ord(c) for c in room_id)


def get_category_sampler(seed: int, max_rounds: int | None = None) -> Iterable[Category]:
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
