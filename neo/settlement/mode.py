from __future__ import annotations

from neo.config import get_config


def get_game_mode() -> str:
    """Return ``hp`` or ``points``."""
    scoring = get_config()["scoring"]
    mode = scoring.get("mode", "hp")
    if mode in ("hp", "points"):
        return mode
    if mode in ("ffa_hp", "ranking"):
        return "hp"
    return "hp"


def get_damage_fn_name() -> str:
    scoring = get_config()["scoring"]
    name = scoring.get("damage_fn", "ffa")
    if name == "ffa_hp":
        return "ffa"
    return name


def get_scoring_fn_name() -> str:
    return get_config()["scoring"].get("scoring_fn", "ffa")
