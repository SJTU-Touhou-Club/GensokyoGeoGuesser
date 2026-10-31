import pytest

from neo.config import load_config
from neo.settlement.damage.registry import ranking as hp_ranking_damage
from neo.settlement.points.registry import ffa as points_ffa
from neo.settlement.points.registry import ranking as points_ranking
from neo.scoring.rank import assign_score_ranks, assign_standings_ranks, rank_by_distance


def test_rank_by_distance_no_relay():
    """0.1, 0.2, 0.3 with tolerance 0.1: only first two tie; third stays rank 3."""
    distances = {"a": 0.1, "b": 0.2, "c": 0.3}
    ranks = rank_by_distance(distances, tolerance=0.1)
    assert ranks == {"a": 1, "b": 1, "c": 3}


def test_rank_by_distance_cluster_min_not_adjacent():
    """0.1, 0.15, 0.19 tie via cluster min; 0.35 starts new cluster at rank 4."""
    distances = {"a": 0.1, "b": 0.15, "c": 0.19, "d": 0.35}
    ranks = rank_by_distance(distances, tolerance=0.1)
    assert ranks == {"a": 1, "b": 1, "c": 1, "d": 4}


def test_rank_by_distance_competition_ranking():
    distances = {"a": 1.0, "b": 5.0, "c": 5.4}
    ranks = rank_by_distance(distances, tolerance=0.5)
    assert ranks == {"a": 1, "b": 2, "c": 2}


def test_assign_standings_ranks_hp_tie():
    entries = [
        {"player_id": "a", "rounds_survived": 10, "hp": 5.0},
        {"player_id": "b", "rounds_survived": 10, "hp": 5.05},
        {"player_id": "c", "rounds_survived": 8, "hp": 20.0},
    ]
    ranked = assign_standings_ranks(entries, tie_threshold=0.1)
    by_id = {e["player_id"]: e["rank"] for e in ranked}
    assert by_id == {"a": 1, "b": 1, "c": 3}


def test_assign_score_ranks():
    entries = [
        {"player_id": "a", "score": 100.0},
        {"player_id": "b", "score": 99.95},
        {"player_id": "c", "score": 50.0},
    ]
    ranked = assign_score_ranks(entries, tie_threshold=0.1)
    by_id = {e["player_id"]: e["rank"] for e in ranked}
    assert by_id == {"a": 1, "b": 1, "c": 3}


def test_hp_ranking_damage_plugin_with_player_scale():
    load_config()
    ctx = {
        "distances": {"alice": 1.0, "bob": 5.0, "carol": 9.0},
        "normalized_distances": {"alice": 0.02, "bob": 0.1, "carol": 0.18},
        "round_index": 0,
        "dmg_mult": 2.0,
        "config": {
            "scoring": {
                "mode": "hp",
                "damage_fn": "ranking",
                "rank_tolerance": 0.02,
                "ranking": {"hp_budget_factor": 0.22, "player_scale": True},
            }
        },
        "player_ids": ["alice", "bob", "carol"],
    }
    damages = hp_ranking_damage(ctx)
    assert damages["alice"] == 0.0
    assert damages["bob"] == pytest.approx(damages["carol"] / 2)
    assert damages["carol"] > damages["bob"] > 0


def test_hp_ranking_damage_tied_players_same_damage():
    load_config()
    ctx = {
        "distances": {"a": 1.0, "b": 1.05, "c": 10.0},
        "normalized_distances": {"a": 0.02, "b": 0.021, "c": 0.2},
        "round_index": 0,
        "dmg_mult": 1.0,
        "config": {
            "scoring": {
                "mode": "hp",
                "damage_fn": "ranking",
                "rank_tolerance": 0.02,
                "ranking": {"hp_budget_factor": 0.22, "player_scale": True},
            }
        },
        "player_ids": ["a", "b", "c"],
    }
    damages = hp_ranking_damage(ctx)
    assert damages["a"] == damages["b"] == 0.0


def test_points_ffa_scoring_scale_invariant_shape():
    load_config()
    raw = {"a": 0.2, "b": 0.8, "c": 1.2}
    base_cfg = {
        "mode": "points",
        "scoring_fn": "ffa",
        "score_cap_norm": 1.0,
        "rank_tolerance": 0.02,
    }
    scores_by_scale = {}
    for scale in (1.0, 50.0, 68.0):
        ctx = {
            "distances": {pid: d * scale for pid, d in raw.items()},
            "normalized_distances": raw,
            "round_index": 0,
            "dmg_mult": 2.0,
            "config": {"scoring": {**base_cfg, "distance_scale": scale}},
            "player_ids": ["a", "b", "c"],
        }
        scores = points_ffa(ctx)
        scores_by_scale[scale] = scores
        assert scores["a"] == pytest.approx(scale * 0.8 * 2.0)
        assert scores["b"] == pytest.approx(scale * 0.2 * 2.0)
        assert scores["c"] == 0.0

    # Relative ordering / proportions independent of scale.
    r1 = scores_by_scale[1.0]
    r50 = scores_by_scale[50.0]
    assert r1["a"] / r1["b"] == pytest.approx(r50["a"] / r50["b"])


def test_points_ranking_scoring():
    load_config()
    ctx = {
        "distances": {"a": 1.0, "b": 5.0, "c": 9.0, "d": 20.0},
        "normalized_distances": {"a": 0.01, "b": 0.05, "c": 0.09, "d": 0.2},
        "round_index": 0,
        "dmg_mult": 2.0,
        "config": {
            "scoring": {
                "mode": "points",
                "scoring_fn": "ranking",
                "rank_tolerance": 0.02,
            }
        },
        "player_ids": ["a", "b", "c", "d"],
    }
    scores = points_ranking(ctx)
    assert scores["a"] == pytest.approx(8.0)
    assert scores["d"] == pytest.approx(2.0)


def test_points_ranking_tied_same_score():
    load_config()
    ctx = {
        "distances": {"a": 1.0, "b": 1.05, "c": 10.0},
        "normalized_distances": {"a": 0.02, "b": 0.021, "c": 0.2},
        "round_index": 0,
        "dmg_mult": 1.0,
        "config": {
            "scoring": {
                "mode": "points",
                "scoring_fn": "ranking",
                "rank_tolerance": 0.02,
            }
        },
        "player_ids": ["a", "b", "c"],
    }
    scores = points_ranking(ctx)
    assert scores["a"] == scores["b"]


def test_points_ranking_solo_player_gets_first_place():
    load_config()
    ctx = {
        "distances": {"solo": 0.5},
        "normalized_distances": {"solo": 0.5},
        "round_index": 0,
        "dmg_mult": 1.5,
        "config": {
            "scoring": {
                "mode": "points",
                "scoring_fn": "ranking",
                "rank_tolerance": 0.02,
            }
        },
        "player_ids": ["solo"],
    }
    scores = points_ranking(ctx)
    assert scores["solo"] == pytest.approx(1.5)


def test_rank_tolerance_uses_normalized_distance():
    load_config()
    # Same raw geometry; different scale must not change who ties.
    raw = {"a": 0.02, "b": 0.035, "c": 0.2}
    ranks = []
    for scale in (1.0, 50.0):
        ctx = {
            "distances": {pid: d * scale for pid, d in raw.items()},
            "normalized_distances": raw,
            "round_index": 0,
            "dmg_mult": 1.0,
            "config": {
                "scoring": {
                    "mode": "points",
                    "scoring_fn": "ranking",
                    "distance_scale": scale,
                    "rank_tolerance": 0.02,
                }
            },
            "player_ids": ["a", "b", "c"],
        }
        scores = points_ranking(ctx)
        ranks.append(scores)
    assert ranks[0] == ranks[1]
    assert ranks[0]["a"] == ranks[0]["b"]
