from __future__ import annotations

from typing import Dict

from neo.config import get_scoring_mode_config
from neo.scoring.rank import rank_by_distance
from neo.settlement.context import SettlementContext


def _scoring_cfg(context: SettlementContext) -> dict:
    room_scoring = context.get("config", {}).get("scoring")
    if isinstance(room_scoring, dict) and (
        "scoring_fn" in room_scoring
        or "damage_fn" in room_scoring
        or "mode" in room_scoring
        or "distance_scale" in room_scoring
    ):
        return room_scoring
    return get_scoring_mode_config()


def _normalized(context: SettlementContext) -> Dict[str, float]:
    if "normalized_distances" in context and context["normalized_distances"]:
        return context["normalized_distances"]
    # Backward-compat: treat provided distances as already-normalized.
    return context["distances"]


def ffa(context: SettlementContext) -> Dict[str, float]:
    """Additive distance scoring, scale-invariant shape.

    round_score = distance_scale × max(score_cap_norm − raw_distance, 0) × dmg_mult

    ``score_cap_norm`` and ranking tolerances stay fixed when ``distance_scale``
    changes; only absolute score magnitude tracks the scale factor.
    """
    scoring = _scoring_cfg(context)
    score_cap_norm = float(scoring.get("score_cap_norm", 1.0))
    # Legacy configs used score_cap with scaled distances.
    if "score_cap_norm" not in scoring and "score_cap" in scoring:
        scale = float(scoring.get("distance_scale", 1.0)) or 1.0
        score_cap_norm = float(scoring["score_cap"]) / scale
    scale = float(scoring.get("distance_scale", 1.0))
    dmg_mult = context["dmg_mult"]
    raw = _normalized(context)

    return {
        pid: scale * max(score_cap_norm - dist, 0.0) * dmg_mult
        for pid, dist in raw.items()
    }


def ranking(context: SettlementContext) -> Dict[str, float]:
    scoring = _scoring_cfg(context)
    # rank_tolerance is defined in raw/normalized distance units.
    tolerance = float(scoring.get("rank_tolerance", 0.02))
    dmg_mult = context["dmg_mult"]
    n = len(context["player_ids"])
    raw = _normalized(context)

    ranks = rank_by_distance(raw, tolerance)

    return {
        pid: (n - ranks[pid] + 1) * dmg_mult
        for pid in context["player_ids"]
    }


_REGISTRY = {
    "ffa": ffa,
    "ranking": ranking,
    "distance": ffa,
}


def get_scoring_fn(name: str):
    if name not in _REGISTRY:
        raise ValueError(f"Unknown scoring_fn: {name}")
    return _REGISTRY[name]
