from __future__ import annotations

from typing import Dict

from neo.config import get_config
from neo.scoring.rank import rank_by_distance
from neo.settlement.context import SettlementContext


def ffa(context: SettlementContext) -> Dict[str, float]:
    dmg_mult = context["dmg_mult"]
    return {
        pid: dist * dmg_mult
        for pid, dist in context["distances"].items()
    }


def ranking(context: SettlementContext) -> Dict[str, float]:
    cfg = get_config()
    scoring = cfg["scoring"]
    ranking_cfg = scoring.get("ranking", {})

    tolerance = float(scoring.get("rank_tolerance", 3.0))
    max_hp = float(cfg["rounds"]["max_hp"])
    max_rounds = int(cfg["rounds"]["max_rounds"])
    hp_budget_factor = float(ranking_cfg.get("hp_budget_factor", 0.22))
    player_scale = bool(ranking_cfg.get("player_scale", True))
    dmg_mult = context["dmg_mult"]

    n = len(context["player_ids"])
    if n <= 1:
        return {pid: 0.0 for pid in context["player_ids"]}

    hp_budget = max_hp / max(hp_budget_factor * max_rounds, 1.0)
    if player_scale:
        hp_budget *= 2.0 / n

    ranks = rank_by_distance(context["distances"], tolerance)

    damages: Dict[str, float] = {}
    for pid in context["player_ids"]:
        rank = ranks[pid]
        weight = (rank - 1) / max(n - 1, 1)
        damages[pid] = hp_budget * weight * dmg_mult

    return damages


_REGISTRY = {
    "ffa": ffa,
    "ranking": ranking,
    "ffa_hp": ffa,
}


def get_damage_fn(name: str):
    if name not in _REGISTRY:
        raise ValueError(f"Unknown damage_fn: {name}")
    return _REGISTRY[name]
