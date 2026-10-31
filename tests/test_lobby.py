import pytest

from neo.config import load_config
from neo.game import database as db
from neo.lobby import service as lobby_service
from neo.lobby.service import LobbyError
from neo.lobby.store import LobbyStatus, get_lobby_store


@pytest.fixture(autouse=True)
def reset_store():
    load_config()
    db.init_database()
    db.rooms.clear()
    store = get_lobby_store()
    store._rooms.clear()
    store._player_index.clear()
    store._quick_pool.clear()
    yield
    db.rooms.clear()
    from neo.lobby import sse as lobby_sse

    lobby_sse.set_broadcast_hook()


def test_join_creates_room():
    r = lobby_service.join(None, "alice", "c1")
    assert r["room_id"]
    assert r["is_host"] is True
    room = get_lobby_store().get_room(r["room_id"])
    assert room.status in (LobbyStatus.WAITING, LobbyStatus.COUNTDOWN)
    assert room.rounds == 6
    assert room.difficulty == "N"
    assert room.scoring_strategy == "ranking"
    assert r["game_settings"]["difficulties"] == ["N", "L"]
    assert r["game_settings"]["scoring_strategies"] == ["ranking", "distance"]
    assert r["game_settings"]["default_scoring_strategy"] == "ranking"


def test_second_player_joins_same_quick_room():
    r1 = lobby_service.join(None, "alice", "c1")
    r2 = lobby_service.join(None, "bob", "c2")
    assert r2["room_id"]


def test_force_start():
    r = lobby_service.join("private1", "alice", "c1", min_players=2, max_players=4)
    lobby_service.join("private1", "bob", "c2")
    result = lobby_service.start("private1", "alice")
    room = get_lobby_store().get_room("private1")
    assert room.status == LobbyStatus.IN_GAME
    assert result["game_url"]


def test_host_force_start_below_min():
    lobby_service.join("solo", "alice", "c1", min_players=2, max_players=4)
    result = lobby_service.start("solo", "alice")
    assert result["ok"] is True
    assert get_lobby_store().get_room("solo").status == LobbyStatus.IN_GAME


def test_non_host_cannot_start():
    lobby_service.join("r1", "alice", "c1")
    lobby_service.join("r1", "bob", "c2")
    with pytest.raises(LobbyError) as exc:
        lobby_service.start("r1", "bob")
    assert exc.value.code == "NOT_HOST"


def test_update_room_settings_broadcasts():
    events = []

    def capture(room_id, event, payload=None):
        if event == "lobby_update":
            events.append(payload)

    from neo.lobby import service as svc

    svc.set_lobby_broadcast(capture)
    lobby_service.join("settings", "alice", "c1", min_players=2, max_players=8)
    result = lobby_service.update_room_settings(
        "settings",
        "alice",
        3,
        6,
        rounds=6,
        difficulty="L",
        scoring_strategy="distance",
    )
    assert result["room"]["min_players"] == 3
    assert result["room"]["max_players"] == 6
    assert result["room"]["rounds"] == 6
    assert result["room"]["difficulty"] == "L"
    assert result["room"]["scoring_strategy"] == "distance"
    assert events[-1]["rounds"] == 6
    assert events[-1]["difficulty"] == "L"
    assert events[-1]["scoring_strategy"] == "distance"


def test_update_settings_rejects_max_below_min():
    lobby_service.join("bad", "alice", "c1")
    with pytest.raises(LobbyError) as exc:
        lobby_service.update_room_settings("bad", "alice", 5, 3)
    assert exc.value.code == "INVALID_PLAYER_LIMITS"


def test_update_settings_rejects_invalid_rounds():
    lobby_service.join("badrounds", "alice", "c1")
    with pytest.raises(LobbyError) as exc:
        lobby_service.update_room_settings(
            "badrounds", "alice", 2, 4, rounds=99
        )
    assert exc.value.code == "INVALID_ROUNDS"


def test_update_settings_rejects_invalid_difficulty():
    lobby_service.join("baddiff", "alice", "c1")
    with pytest.raises(LobbyError) as exc:
        lobby_service.update_room_settings(
            "baddiff", "alice", 2, 4, difficulty="E"
        )
    assert exc.value.code == "INVALID_DIFFICULTY"


def test_non_host_cannot_update_settings():
    lobby_service.join("hostonly", "alice", "c1")
    lobby_service.join("hostonly", "bob", "c2")
    with pytest.raises(LobbyError) as exc:
        lobby_service.update_room_settings(
            "hostonly", "bob", 2, 4, rounds=4
        )
    assert exc.value.code == "NOT_HOST"


def test_room_config_propagates_on_start():
    lobby_service.join(
        "cfg",
        "alice",
        "c1",
        min_players=1,
        max_players=4,
        rounds=6,
        difficulty="L",
        scoring_strategy="distance",
    )
    lobby_service.start("cfg", "alice")
    room = db.get_room("cfg")
    assert room.room_config["rounds"] == 6
    assert room.room_config["difficulty"] == "L"
    assert room.room_config["scoring_strategy"] == "distance"
    assert room.room_config["scoring"]["scoring_fn"] == "ffa"
    assert db.room_max_rounds(room) == 6


def test_update_settings_rejects_max_below_player_count():
    lobby_service.join("full", "alice", "c1")
    lobby_service.join("full", "bob", "c2")
    lobby_service.join("full", "carol", "c3")
    with pytest.raises(LobbyError) as exc:
        lobby_service.update_room_settings("full", "alice", 2, 2)
    assert exc.value.code == "MAX_BELOW_PLAYER_COUNT"


def test_normalize_respects_pin_color_cap():
    lo, hi = lobby_service.player_limit_bounds()
    assert lo == 1
    assert hi == 10
    with pytest.raises(LobbyError):
        lobby_service.normalize_room_limits(1, hi + 1)


def test_host_leave_transfers_to_next_player():
    events = []

    def capture(room_id, event, payload=None):
        if event == "lobby_update":
            events.append(payload)

    from neo.lobby import service as svc

    svc.set_lobby_broadcast(capture)
    lobby_service.join("succ", "alice", "c1", min_players=2, max_players=4)
    lobby_service.join("succ", "bob", "c2")
    lobby_service.join("succ", "carol", "c3")

    lobby_service.leave("succ", "alice", "c1")
    room = get_lobby_store().get_room("succ")
    assert room.host_id == "bob"
    assert events[-1]["host_id"] == "bob"

    result = lobby_service.update_room_settings("succ", "bob", 2, 4)
    assert result["ok"] is True
    started = lobby_service.start("succ", "bob")
    assert started["ok"] is True
    assert get_lobby_store().get_room("succ").status == LobbyStatus.IN_GAME


def test_host_leave_empties_room_clears_host():
    lobby_service.join("empty", "alice", "c1")
    lobby_service.leave("empty", "alice", "c1")
    room = get_lobby_store().get_room("empty")
    assert room.players == []
    assert room.host_id == ""


def test_quick_match_reuses_empty_room_assigns_host():
    r1 = lobby_service.join(None, "alice", "c1", min_players=2, max_players=4)
    room_id = r1["room_id"]
    lobby_service.leave(room_id, "alice", "c1")
    room = get_lobby_store().get_room(room_id)
    assert room.host_id == ""
    assert room_id in get_lobby_store().quick_pool_list()

    r2 = lobby_service.join(None, "bob", "c2", min_players=2, max_players=4)
    assert r2["room_id"] == room_id
    assert r2["is_host"] is True
    assert get_lobby_store().get_room(room_id).host_id == "bob"
    result = lobby_service.update_room_settings(room_id, "bob", 2, 4)
    assert result["ok"] is True


@pytest.mark.parametrize("scoring_strategy", ["ranking", "distance"])
def test_solo_room_uses_host_settings(scoring_strategy):
    result = lobby_service.join(
        "solo_config", "alice", "c1", min_players=1, max_players=1,
        rounds=3, difficulty="N", scoring_strategy=scoring_strategy,
    )
    room = get_lobby_store().get_room(result["room_id"])
    assert room.status == LobbyStatus.WAITING
    lobby_service.update_room_settings(
        room.room_id, "alice", 1, 1, rounds=4, difficulty="L",
        scoring_strategy=scoring_strategy,
    )
    assert room.status == LobbyStatus.WAITING
    lobby_service.start(room.room_id, "alice")
    game = db.get_room(room.room_id)
    assert game.player_ids == ["alice"]
    assert game.room_config["rounds"] == 4
    assert game.room_config["difficulty"] == "L"
    assert game.room_config["scoring_strategy"] == scoring_strategy


def test_solo_rooms_are_separate_from_each_other_and_multiplayer():
    multiplayer = lobby_service.join(None, "host", "c0")
    first = lobby_service.join(
        "solo_first", "solo-first", "c1", min_players=1, max_players=1,
    )
    second = lobby_service.join(
        "solo_second", "solo-second", "c2", min_players=1, max_players=1,
    )
    guest = lobby_service.join(None, "guest", "c3")
    assert guest["room_id"] == multiplayer["room_id"]
    assert len({multiplayer["room_id"], first["room_id"], second["room_id"]}) == 3
    for result in (first, second):
        room = get_lobby_store().get_room(result["room_id"])
        assert room.status == LobbyStatus.WAITING
        assert len(room.players) == 1
        with pytest.raises(LobbyError) as exc:
            lobby_service.join(room.room_id, "intruder", "c4")
        assert exc.value.code == "ROOM_FULL"
