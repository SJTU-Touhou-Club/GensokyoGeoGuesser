from __future__ import annotations

import shutil
from pathlib import Path

from neo.config import data_dir, project_root


def copy_static_assets(root: Path | None = None) -> None:
    """Copy data/dataset and data/media into static/ for deployment."""
    base = root or project_root()
    static_root = base / "static"
    copies = {
        static_root / "dataset": base / "data" / "dataset",
        static_root / "media": base / "data" / "media",
    }

    for dest, src in copies.items():
        if not src.is_dir():
            raise FileNotFoundError(f"Missing asset directory: {src}")

        if dest.is_symlink():
            dest.unlink()
        elif dest.exists():
            shutil.rmtree(dest)

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)


def dataset_dir() -> Path:
    return data_dir() / "dataset"


def media_dir() -> Path:
    return data_dir() / "media"
