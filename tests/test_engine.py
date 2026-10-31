import time

import pytest

from neo.config import get_scoring_mode_config, load_config
from neo.game import database as db
from neo.game import engine
from neo.game.database import Phase
from neo.game.state_builder import build_state


@pytest.fixture(autouse=True)
def setup_db():
    load_config()
    db.init_database()
    db.rooms.clear()
    yield
    db.rooms.clear()


def _room_config(**overrides):
    strategy = overrides.get("scoring_strategy", "ranking")
    scoring = overrides.get("scoring")
    if scoring is None:
        scoring = get_scoring_mode_config(strategy)
    base = {
        "rounds": 6,
        "difficulty": "L",
        "scoring_strategy": strategy,
        "scoring": scoring,
    }
    base.update(overrides)
    if "scoring" not in overrides and "scoring_strategy" in overrides:
        base["scoring"] = get_scoring_mode_config(base["scoring_strategy"])
    return base


def _init_two_player_room(**overrides):
    db.init_room("test_room", ["alice", "bob"], _room_config(**overrides))
    engine.set_broadcast(lambda *a: None)


def test_submit_advances_to_agree_next():
    _init_two_player_room()
    engine.place_guess("test_room", "alice", 0.1, 0.1)
    engine.place_guess("test_room", "bob", 0.2, 0.2)
    engine.submit("test_room", "alice")
    engine.submit("test_room", "bob")
    room = db.get_room("test_room")
    assert room.phase in (Phase.AGREE_NEXT, Phase.GAME_OVER, Phase.REVEAL)
    assert room.player_round_score["alice"] is not None


def test_state_version_increments():
    _init_two_player_room()
    v0 = db.get_room("test_room").state_version
    engine.place_guess("test_room", "alice", 0.5, 0.5)
    assert db.get_room("test_room").state_version > v0


def test_disconnect_grace_then_expiry(monkeypatch):
    _init_two_player_room()
    room = db.get_room("test_room")
    engine.exit_connection("test_room", "bob", "conn1")
    engine.place_guess("test_room", "alice", 0.3, 0.3)
    engine.submit("test_room", "alice")
    assert room.player_connected["bob"] is True
    disconnected_at = room.disconnect_since["bob"]
    monkeypatch.setattr(engine.time, "time", lambda: disconnected_at + 61)
    engine.prune_connections("test_room")
    assert room.player_connected["bob"] is False


def _reach_agree_next():
    _init_two_player_room()
    engine.place_guess("test_room", "alice", 0.1, 0.1)
    engine.place_guess("test_room", "bob", 0.2, 0.2)
    engine.submit("test_room", "alice")
    engine.submit("test_room", "bob")
    room = db.get_room("test_room")
    assert room.phase == Phase.AGREE_NEXT


def test_agree_next_timeout_broadcasts_next_round():
    _reach_agree_next()
    events = []
    engine.set_broadcast(lambda _rid, ev: events.append(ev))
    room = db.get_room("test_room")
    round_before = room.round_index
    room.phase_started_at = time.time() - 999
    engine.check_timeouts("test_room")
    assert room.round_index == round_before + 1
    assert room.phase == Phase.GUESS
    assert "next_round" in events


def test_agree_next_timeout_via_tick():
    _reach_agree_next()
    events = []
    engine.set_broadcast(lambda _rid, ev: events.append(ev))
    room = db.get_room("test_room")
    room.phase_started_at = time.time() - 999
    engine.tick_all_rooms()
    assert room.phase == Phase.GUESS
    assert "next_round" in events


def test_points_mode_accumulates_score_without_hp_loss():
    _init_two_player_room(
        scoring_strategy="distance",
        scoring=get_scoring_mode_config("distance"),
    )
    room = db.get_room("test_room")
    hp_before = dict(room.player_hp)
    engine.place_guess("test_room", "alice", 0.1, 0.1)
    engine.place_guess("test_room", "bob", 0.9, 0.9)
    engine.submit("test_room", "alice")
    engine.submit("test_room", "bob")
    room = db.get_room("test_room")
    assert room.phase == Phase.AGREE_NEXT
    assert room.player_hp == hp_before
    assert room.player_score["alice"] > 0
    assert room.player_round_score["alice"] is not None
    assert room.player_round_damage["alice"] is None


def test_points_mode_no_early_game_over_when_hp_would_end():
    _init_two_player_room(
        scoring_strategy="distance",
        scoring=get_scoring_mode_config("distance"),
    )
    room = db.get_room("test_room")
    for pid in room.player_ids:
        room.player_hp[pid] = 0
    engine.place_guess("test_room", "alice", 0.1, 0.1)
    engine.place_guess("test_room", "bob", 0.2, 0.2)
    engine.submit("test_room", "alice")
    engine.submit("test_room", "bob")
    room = db.get_room("test_room")
    assert room.phase == Phase.AGREE_NEXT


def test_room_rounds_limit_is_honored():
    _init_two_player_room(rounds=2)
    room = db.get_room("test_room")
    state = build_state("test_room", "alice")
    assert state["total_rounds"] == 2

    engine.place_guess("test_room", "alice", 0.1, 0.1)
    engine.place_guess("test_room", "bob", 0.2, 0.2)
    engine.submit("test_room", "alice")
    engine.submit("test_room", "bob")
    engine.agree_next("test_room", "alice")
    engine.agree_next("test_room", "bob")
    room = db.get_room("test_room")
    assert room.round_index == 1
    assert db.has_next_round("test_room") is False

    engine.place_guess("test_room", "alice", 0.1, 0.1)
    engine.place_guess("test_room", "bob", 0.2, 0.2)
    engine.submit("test_room", "alice")
    engine.submit("test_room", "bob")
    engine.agree_next("test_room", "alice")
    engine.agree_next("test_room", "bob")
    room = db.get_room("test_room")
    assert room.phase == Phase.GAME_OVER
    assert room.player_score["alice"] > 0


def test_solo_ranking_earns_score_and_shows_on_leaderboard():
    db.init_room(
        "solo",
        ["alice"],
        _room_config(rounds=1, scoring_strategy="ranking"),
    )
    engine.set_broadcast(lambda *a: None)
    engine.place_guess("solo", "alice", 0.2, 0.2)
    engine.submit("solo", "alice")
    room = db.get_room("solo")
    assert room.player_round_score["alice"] == pytest.approx(1.0)
    assert room.player_score["alice"] == pytest.approx(1.0)
    state = build_state("solo", "alice")
    assert state["scoring_strategy"] == "ranking"
    assert state["players"][0]["score"] == pytest.approx(1.0)
    assert state["players"][0]["round_score"] == pytest.approx(1.0)


def test_distance_scoring_scales_with_distance_scale():
    for scale in (1.0, 50.0):
        db.rooms.clear()
        scoring = get_scoring_mode_config("distance")
        scoring["distance_scale"] = scale
        db.init_room(
            "scale",
            ["alice"],
            _room_config(
                rounds=1,
                scoring_strategy="distance",
                scoring=scoring,
            ),
        )
        engine.set_broadcast(lambda *a: None)
        question = db.get_current_question("scale")
        answer = db.loc_db[question.location]
        engine.place_guess("scale", "alice", answer[0], answer[1])
        engine.submit("scale", "alice")
        room = db.get_room("scale")
        assert room.player_round_score["alice"] == pytest.approx(scale * 1.0)


def test_connection_return_during_grace_restores_lease(monkeypatch):
    _init_two_player_room()
    room = db.get_room("test_room")
    engine.register_connection("test_room", "alice", "c1")
    now = engine.time.time()
    engine.exit_connection("test_room", "alice", "c1")
    monkeypatch.setattr(engine.time, "time", lambda: now + 30)
    engine.register_connection("test_room", "alice", "c1")
    monkeypatch.setattr(engine.time, "time", lambda: now + 61)
    engine.prune_connections("test_room")
    assert room.player_connected["alice"] is True
    monkeypatch.setattr(engine.time, "time", lambda: now + 91)
    engine.prune_connections("test_room")
    assert room.player_connected["alice"] is False
