from __future__ import annotations

from typing import Optional

from neo.config import get_scoring_mode_config, is_scoring_mode_body


def _resolved_scoring(room_config: Optional[dict] = None) -> dict:
    """Return the room's scoring snapshot, or the default config mode."""
    if room_config:
        scoring = room_config.get("scoring")
        if is_scoring_mode_body(scoring):
            return scoring
        strategy = room_config.get("scoring_strategy")
        if strategy:
            try:
                return get_scoring_mode_config(strategy)
            except KeyError:
                pass
    return get_scoring_mode_config()


def get_game_mode(room_config: Optional[dict] = None) -> str:
    """Return ``hp`` or ``points``."""
    scoring = _resolved_scoring(room_config)
    mode = scoring.get("mode", "points")
    if mode in ("hp", "points"):
        return mode
    if mode in ("ffa_hp", "ranking"):
        return "hp"
    return "points"


def get_damage_fn_name(room_config: Optional[dict] = None) -> str:
    scoring = _resolved_scoring(room_config)
    name = scoring.get("damage_fn") or scoring.get("scoring_fn", "ffa")
    if name == "ffa_hp":
        return "ffa"
    if name == "distance":
        return "ffa"
    return name


def get_scoring_fn_name(room_config: Optional[dict] = None) -> str:
    scoring = _resolved_scoring(room_config)
    name = scoring.get("scoring_fn", "ffa")
    if name == "distance":
        return "ffa"
    return name
