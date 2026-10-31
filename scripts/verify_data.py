#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from neo.config import data_dir, load_config
from neo.static_assets import dataset_dir


def _load_locations(path: Path) -> set[str]:
    locations: set[str] = set()
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            locations.add(line.split(",")[0].strip())
    return locations


def _load_questions(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            rows.append(
                {
                    "id": parts[0],
                    "image": parts[1],
                    "location": parts[2],
                }
            )
    return rows


def verify_data() -> list[str]:
    load_config()
    cfg = load_config().get("data_files", {})
    loc_path = data_dir() / cfg.get("locations", "locations.csv")
    que_path = data_dir() / cfg.get("questions", "questions.csv")

    if not loc_path.is_file():
        return [f"Locations file not found: {loc_path}"]
    if not que_path.is_file():
        return [f"Questions file not found: {que_path}"]
    if not dataset_dir().is_dir():
        return [f"Dataset directory not found: {dataset_dir()}"]

    locations = _load_locations(loc_path)
    questions = _load_questions(que_path)
    errors: list[str] = []

    for question in questions:
        qid = question["id"]
        image_path = dataset_dir() / question["image"]
        if not image_path.is_file():
            errors.append(f"Q{qid}: missing image {question['image']}")
        if question["location"] not in locations:
            errors.append(f"Q{qid}: location not in {loc_path.name}: {question['location']}")

    return errors


def main() -> int:
    errors = verify_data()
    if errors:
        print("Data verification failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    load_config()
    cfg = load_config().get("data_files", {})
    que_path = data_dir() / cfg.get("questions", "questions.csv")
    loc_path = data_dir() / cfg.get("locations", "locations.csv")
    question_count = len(_load_questions(que_path))
    location_count = len(_load_locations(loc_path))
    print(
        f"OK: {question_count} questions checked against "
        f"{location_count} locations and {dataset_dir()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
