from __future__ import annotations

from typing import Dict, List, TypedDict


class SettlementContext(TypedDict, total=False):
    # Scaled distances: raw * distance_scale (used by legacy HP FFA).
    distances: Dict[str, float]
    # Raw Euclidean distances in map unit space (scale-invariant).
    normalized_distances: Dict[str, float]
    round_index: int
    dmg_mult: float
    config: dict
    player_ids: List[str]
