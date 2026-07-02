#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from neo.static_assets import copy_static_assets


def main() -> int:
    try:
        copy_static_assets()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Copied data/dataset -> static/dataset")
    print("Copied data/media -> static/media")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
