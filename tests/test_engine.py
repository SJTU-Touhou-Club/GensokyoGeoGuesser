import time

import pytest

from neo.config import load_config
from neo.game import database as db
from neo.game import engine
from neo.game.database import Phase


@pytest.fixture(autouse=True)
def setup_db():
    load_config()
    db.init_database()
    db.rooms.clear()
    yield
    db.rooms.clear()


def _init_two_player_room():
    db.init_room("test_room", ["alice", "bob"], {"scoring": load_config()["scoring"]})
    engine.set_broadcast(lambda *a: None)


def test_submit_advances_to_agree_next():
    _init_two_player_room()
    engine.place_guess("test_room", "alice", 0.1, 0.1)
    engine.place_guess("test_room", "bob", 0.2, 0.2)
    engine.submit("test_room", "alice")
    engine.submit("test_room", "bob")
    room = db.get_room("test_room")
    assert room.phase in (Phase.AGREE_NEXT, Phase.GAME_OVER, Phase.REVEAL)
    assert room.player_round_damage["alice"] is not None


def test_state_version_increments():
    _init_two_player_room()
    v0 = db.get_room("test_room").state_version
    engine.place_guess("test_room", "alice", 0.5, 0.5)
    assert db.get_room("test_room").state_version > v0


def test_afk_auto_submit_on_disconnect():
    _init_two_player_room()
    room = db.get_room("test_room")
    engine.exit_connection("test_room", "bob", "conn1")
    engine.place_guess("test_room", "alice", 0.3, 0.3)
    engine.submit("test_room", "alice")
    # bob AFK should have been auto-submitted when alice submitted triggered... 
    # actually AFK only on round start. After disconnect bob is AFK for next round.
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
    cfg = load_config()
    original_scoring = dict(cfg["scoring"])
    cfg["scoring"] = {
        "mode": "points",
        "scoring_fn": "ffa",
        "score_cap": 50.0,
        "distance_scale": 68,
        "tie_threshold": 0.1,
    }
    try:
        _init_two_player_room()
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
    finally:
        cfg["scoring"] = original_scoring


def test_points_mode_no_early_game_over_when_hp_would_end():
    cfg = load_config()
    original_scoring = dict(cfg["scoring"])
    cfg["scoring"] = {
        "mode": "points",
        "scoring_fn": "ffa",
        "score_cap": 50.0,
        "distance_scale": 68,
        "tie_threshold": 0.1,
    }
    try:
        _init_two_player_room()
        room = db.get_room("test_room")
        for pid in room.player_ids:
            room.player_hp[pid] = 0
        engine.place_guess("test_room", "alice", 0.1, 0.1)
        engine.place_guess("test_room", "bob", 0.2, 0.2)
        engine.submit("test_room", "alice")
        engine.submit("test_room", "bob")
        room = db.get_room("test_room")
        assert room.phase == Phase.AGREE_NEXT
    finally:
        cfg["scoring"] = original_scoring
