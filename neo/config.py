from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config.yaml"

_config: dict[str, Any] | None = None
DEBUG_MODE: bool = False

# Keys that identify a resolved scoring-mode body (vs a map of named modes).
_SCORING_BODY_MARKERS = (
    "mode",
    "scoring_fn",
    "damage_fn",
    "distance_scale",
    "rank_tolerance",
    "score_cap_norm",
    "score_cap",
    "tie_threshold",
    "end_on_hp_zero",
    "ranking",
)


def load_config(path: Path | None = None) -> dict[str, Any]:
    global _config
    if _config is not None and path is None:
        return _config
    cfg_path = path or _CONFIG_PATH
    with open(cfg_path, encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    return _config


def get_config() -> dict[str, Any]:
    if _config is None:
        return load_config()
    return _config


def set_debug_mode(enabled: bool) -> None:
    global DEBUG_MODE
    DEBUG_MODE = enabled
    cfg = get_config()
    if enabled:
        cfg.setdefault("debug", {})["enabled"] = True


def is_debug() -> bool:
    cfg = get_config()
    return DEBUG_MODE or bool(cfg.get("debug", {}).get("enabled", False))


def project_root() -> Path:
    return _ROOT


def data_dir() -> Path:
    return _ROOT / "data"


def static_dir() -> Path:
    return _ROOT / "static"


def is_scoring_mode_body(value: Any) -> bool:
    """True when ``value`` looks like a single mode's hyperparameters."""
    if not isinstance(value, dict):
        return False
    return any(k in value for k in _SCORING_BODY_MARKERS)


def list_scoring_modes() -> List[str]:
    """Return host-selectable scoring mode names in config order.

    Under the multi-mode schema, each dict-valued top-level key of ``scoring``
    is a mode. A legacy flat ``scoring`` body yields a single synthetic mode
    named ``default``.
    """
    scoring = get_config().get("scoring") or {}
    if not isinstance(scoring, dict):
        return []
    names = [name for name, body in scoring.items() if is_scoring_mode_body(body)]
    if names:
        return names
    if is_scoring_mode_body(scoring):
        return ["default"]
    return []


def default_scoring_mode() -> str:
    modes = list_scoring_modes()
    if not modes:
        raise KeyError("No scoring modes defined in config.scoring")
    return modes[0]


def get_scoring_mode_config(mode: Optional[str] = None) -> Dict[str, Any]:
    """Return a copy of the hyperparameters for a named scoring mode.

    ``mode`` defaults to the first defined mode. Preserves case of mode names
    as written in config; matching is case-sensitive first, then case-insensitive.
    """
    scoring = get_config().get("scoring") or {}
    if not isinstance(scoring, dict):
        raise KeyError("config.scoring must be a mapping")

    modes = {
        name: body
        for name, body in scoring.items()
        if is_scoring_mode_body(body)
    }

    # Legacy flat block (no nested modes).
    if not modes and is_scoring_mode_body(scoring):
        if mode is not None and mode not in (None, "default"):
            raise KeyError(f"Unknown scoring mode: {mode}")
        return dict(scoring)

    if not modes:
        raise KeyError("No scoring modes defined in config.scoring")

    if mode is None:
        name = next(iter(modes))
        return dict(modes[name])

    if mode in modes:
        return dict(modes[mode])

    lowered = {k.lower(): k for k in modes}
    key = lowered.get(str(mode).lower())
    if key is not None:
        return dict(modes[key])

    raise KeyError(f"Unknown scoring mode: {mode}")


def resolve_scoring_mode_name(mode: Optional[str] = None) -> str:
    """Normalize a mode request to the canonical key from config."""
    modes = list_scoring_modes()
    if not modes:
        raise KeyError("No scoring modes defined in config.scoring")
    if mode is None:
        return modes[0]
    if mode in modes:
        return mode
    for name in modes:
        if name.lower() == str(mode).lower():
            return name
    raise KeyError(f"Unknown scoring mode: {mode}")
