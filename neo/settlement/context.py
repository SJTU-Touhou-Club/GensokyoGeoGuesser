from __future__ import annotations

from typing import Dict, List, TypedDict


class SettlementContext(TypedDict):
    distances: Dict[str, float]
    round_index: int
    dmg_mult: float
    config: dict
    player_ids: List[str]
