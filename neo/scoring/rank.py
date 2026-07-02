from __future__ import annotations

from typing import Dict, List


def rank_by_distance(distances: Dict[str, float], tolerance: float) -> Dict[str, int]:
    """Competition ranking by scaled distance (ascending = better).

    Ties use cluster-min comparison (no relay): a player joins the current
    cluster only if their distance is within ``tolerance`` of the cluster's
    minimum distance, not the immediately preceding player.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")

    sorted_players = sorted(distances.items(), key=lambda item: item[1])
    ranks: Dict[str, int] = {}
    cluster_min: float | None = None

    for index, (player_id, distance) in enumerate(sorted_players):
        if cluster_min is None or distance - cluster_min > tolerance:
            cluster_min = distance
            current_rank = index + 1
        ranks[player_id] = current_rank

    return ranks


def assign_standings_ranks(
    entries: List[dict],
    tie_threshold: float,
) -> List[dict]:
    """Sort by rounds_survived desc, hp desc; assign competition ranks with HP ties."""
    entries.sort(key=lambda e: (-e["rounds_survived"], -e["hp"]))

    current_rank = 1
    for index, entry in enumerate(entries):
        if index > 0:
            prev = entries[index - 1]
            if (
                entry["rounds_survived"] != prev["rounds_survived"]
                or abs(entry["hp"] - prev["hp"]) >= tie_threshold
            ):
                current_rank = index + 1
        entry["rank"] = current_rank

    return entries


def assign_score_ranks(
    entries: List[dict],
    tie_threshold: float,
) -> List[dict]:
    """Sort by score desc; assign competition ranks with score ties."""
    entries.sort(key=lambda e: -e["score"])

    current_rank = 1
    for index, entry in enumerate(entries):
        if index > 0:
            prev = entries[index - 1]
            if abs(entry["score"] - prev["score"]) >= tie_threshold:
                current_rank = index + 1
        entry["rank"] = current_rank

    return entries
