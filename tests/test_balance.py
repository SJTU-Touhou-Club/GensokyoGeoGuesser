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
        "round_index": 0,
        "dmg_mult": 2.0,
        "config": {},
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
        "round_index": 0,
        "dmg_mult": 1.0,
        "config": {},
        "player_ids": ["a", "b", "c"],
    }
    damages = hp_ranking_damage(ctx)
    assert damages["a"] == damages["b"] == 0.0


def test_points_ffa_scoring():
    load_config()
    ctx = {
        "distances": {"a": 10.0, "b": 40.0, "c": 60.0},
        "round_index": 0,
        "dmg_mult": 2.0,
        "config": {},
        "player_ids": ["a", "b", "c"],
    }
    scores = points_ffa(ctx)
    assert scores["a"] == pytest.approx(80.0)
    assert scores["b"] == pytest.approx(20.0)
    assert scores["c"] == 0.0


def test_points_ranking_scoring():
    load_config()
    ctx = {
        "distances": {"a": 1.0, "b": 5.0, "c": 9.0, "d": 20.0},
        "round_index": 0,
        "dmg_mult": 2.0,
        "config": {},
        "player_ids": ["a", "b", "c", "d"],
    }
    scores = points_ranking(ctx)
    assert scores["a"] == pytest.approx(8.0)
    assert scores["d"] == pytest.approx(2.0)


def test_points_ranking_tied_same_score():
    load_config()
    ctx = {
        "distances": {"a": 1.0, "b": 1.05, "c": 10.0},
        "round_index": 0,
        "dmg_mult": 1.0,
        "config": {},
        "player_ids": ["a", "b", "c"],
    }
    scores = points_ranking(ctx)
    assert scores["a"] == scores["b"]
