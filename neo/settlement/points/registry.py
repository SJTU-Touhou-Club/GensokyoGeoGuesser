from __future__ import annotations

from typing import Dict

from neo.config import get_config
from neo.scoring.rank import rank_by_distance
from neo.settlement.context import SettlementContext


def ffa(context: SettlementContext) -> Dict[str, float]:
    cfg = get_config()
    scoring = cfg["scoring"]
    score_cap = float(scoring.get("score_cap", 50.0))
    dmg_mult = context["dmg_mult"]

    return {
        pid: max(score_cap - dist, 0.0) * dmg_mult
        for pid, dist in context["distances"].items()
    }


def ranking(context: SettlementContext) -> Dict[str, float]:
    cfg = get_config()
    scoring = cfg["scoring"]
    tolerance = float(scoring.get("rank_tolerance", 3.0))
    dmg_mult = context["dmg_mult"]

    n = len(context["player_ids"])
    if n <= 1:
        return {pid: 0.0 for pid in context["player_ids"]}

    ranks = rank_by_distance(context["distances"], tolerance)

    return {
        pid: (n - ranks[pid] + 1) * dmg_mult
        for pid in context["player_ids"]
    }


_REGISTRY = {
    "ffa": ffa,
    "ranking": ranking,
}


def get_scoring_fn(name: str):
    if name not in _REGISTRY:
        raise ValueError(f"Unknown scoring_fn: {name}")
    return _REGISTRY[name]
