from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config.yaml"

_config: dict[str, Any] | None = None
DEBUG_MODE: bool = False


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
