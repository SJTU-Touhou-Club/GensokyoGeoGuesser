from __future__ import annotations

from neo.defs import Coord
from neo.config import get_scoring_mode_config


def distance(xy1: Coord, xy2: Coord) -> float:
    x1, y1 = xy1
    x2, y2 = xy2
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def compute_scaled_distance(xy1: Coord, xy2: Coord) -> float:
    scale = get_scoring_mode_config()["distance_scale"]
    return distance(xy1, xy2) * scale


def compute_scaled_damage(xy1: Coord, xy2: Coord, mult: float) -> float:
    return compute_scaled_distance(xy1, xy2) * mult
