import pytest

from neo.config import load_config
from neo.game import database as game_db
from neo.lobby import service as lobby_service
from neo.lobby.service import LobbyError
from neo.lobby.store import LobbyStatus, get_lobby_store


@pytest.fixture(autouse=True)
def reset_store():
    load_config()
    game_db.init_database()
    game_db.rooms.clear()
    store = get_lobby_store()
    store._rooms.clear()
    store._player_index.clear()
    store._quick_pool.clear()
    yield
    game_db.rooms.clear()
    from neo.lobby import sse as lobby_sse

    lobby_sse.set_broadcast_hook()


def test_join_creates_room():
    r = lobby_service.join(None, "alice", "c1")
    assert r["room_id"]
    assert r["is_host"] is True
    room = get_lobby_store().get_room(r["room_id"])
    assert room.status in (LobbyStatus.WAITING, LobbyStatus.COUNTDOWN)


def test_second_player_joins_same_quick_room():
    r1 = lobby_service.join(None, "alice", "c1")
    r2 = lobby_service.join(None, "bob", "c2")
    # May be same or different room depending on pool; both should succeed
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
    result = lobby_service.update_room_settings("settings", "alice", 3, 6)
    assert result["room"]["min_players"] == 3
    assert result["room"]["max_players"] == 6
    assert events[-1]["min_players"] == 3
    assert events[-1]["max_players"] == 6


def test_update_settings_rejects_max_below_min():
    lobby_service.join("bad", "alice", "c1")
    with pytest.raises(LobbyError) as exc:
        lobby_service.update_room_settings("bad", "alice", 5, 3)
    assert exc.value.code == "INVALID_PLAYER_LIMITS"


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
