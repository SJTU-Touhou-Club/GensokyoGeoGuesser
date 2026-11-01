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


def test_expired_lobby_membership_allows_rejoin(monkeypatch):
    result = lobby_service.join(None, "alice", "c1")
    room = get_lobby_store().get_room(result["room_id"])
    now = room.players[0].last_heartbeat
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 61)
    lobby_service._prune_stale_connections(room, 60)
    assert not room.players
    assert lobby_service.join(None, "alice", "c2")["is_host"] is True


def test_lobby_lease_tracks_each_connection(monkeypatch):
    result = lobby_service.join("lease", "alice", "old")
    room = get_lobby_store().get_room(result["room_id"])
    now = room.players[0].last_heartbeat
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 30)
    lobby_service.join("lease", "alice", "new")
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 61)
    heartbeat = lobby_service.heartbeat("lease", "alice", "new")
    assert heartbeat["present"] is True
    assert room.players[0].connection_ids == {"new"}


def test_lost_quick_join_response_can_be_retried():
    first = lobby_service.join(None, "alice", "same-tab")
    second = lobby_service.join(None, "alice", "same-tab")
    assert first["room_id"] == second["room_id"]
    assert len(get_lobby_store().get_room(first["room_id"]).players) == 1


def test_lobby_heartbeat_recovers_missed_game_start():
    lobby_service.join("recover", "alice", "c1")
    lobby_service.start("recover", "alice")
    result = lobby_service.heartbeat("recover", "alice", "c1")
    assert result["room"]["status"] == "IN_GAME"
    assert result["present"] is True
    assert lobby_service.start("recover", "alice")["status"] == "IN_GAME"


def test_lobby_snapshots_have_monotonic_revisions():
    first = lobby_service.join("revision", "alice", "c1")
    second = lobby_service.update_room_settings("revision", "alice", 2, 4, rounds=3)
    heartbeat = lobby_service.heartbeat("revision", "alice", "c1")
    assert first["room"]["revision"] < second["room"]["revision"] < heartbeat["room"]["revision"]


def test_same_identity_can_join_multiple_rooms_and_observe_independently():
    lobby_service.join("first", "alice", "first-tab")
    lobby_service.join("second", "alice", "second-tab")
    lobby_service.join("watch", "bob", "host")
    lobby_service.observe("watch", "alice", "watch-tab")
    lobby_service.leave("first", "alice", "first-tab")
    store = get_lobby_store()
    store.delete_room("watch")
    assert lobby_service.heartbeat("second", "alice", "second-tab")["present"]
    assert store.get_room("second").host_id == "alice"


@pytest.mark.parametrize("quick", [False, True])
def test_rejoin_replaces_connection_preserving_seat_and_settings(quick):
    result = lobby_service.join(None if quick else "replace", "alice", "old", rounds=4)
    room = get_lobby_store().get_room(result["room_id"])
    player = room.players[0]
    lobby_service.join(room.room_id, "bob", "other")
    deadline = room.countdown_deadline
    joined = player.joined_at
    new = lobby_service.join(None if quick else room.room_id, "alice", "new")
    assert new["room_id"] == room.room_id
    assert room.host_id == "alice"
    assert room.rounds == 4
    assert room.countdown_deadline == deadline
    assert room.players[0] is player and player.joined_at == joined
    assert player.connection_ids == {"new"}
    assert set(player.connection_seen) == {"new"}
    old = lobby_service.heartbeat(room.room_id, "alice", "old")
    assert old["replaced"] and not old["present"]
    lobby_service.leave(room.room_id, "alice", "old")
    assert lobby_service.heartbeat(room.room_id, "alice", "new")["present"]


def test_quick_rejoin_prioritizes_own_waiting_room():
    first = lobby_service.join(None, "alice", "old", min_players=3, max_players=5)
    lobby_service.join(None, "bob", "other", min_players=2, max_players=4)
    again = lobby_service.join(None, "alice", "new", min_players=2, max_players=4)
    assert again["room_id"] == first["room_id"]
    assert again["room"]["min_players"] == 3


@pytest.mark.parametrize("connection", ["old", "new"])
def test_started_room_rejects_all_lobby_rejoins(connection):
    lobby_service.join("started", "alice", "old")
    lobby_service.start("started", "alice")
    with pytest.raises(LobbyError) as exc:
        lobby_service.join("started", "alice", connection)
    assert exc.value.code == "ROOM_IN_GAME"
    assert get_lobby_store().get_room("started").players[0].connection_ids == {"old"}
    assert lobby_service.heartbeat("started", "alice", "old")["present"]


def test_quick_join_after_game_start_enters_another_room():
    first = lobby_service.join(None, "alice", "old")
    lobby_service.start(first["room_id"], "alice")
    second = lobby_service.join(None, "alice", "new")
    assert first["room_id"] != second["room_id"]


def test_replaced_tab_cannot_start_or_configure_room():
    lobby_service.join("replace", "alice", "old")
    lobby_service.join("replace", "alice", "new")
    for action in (
        lambda: lobby_service.start("replace", "alice", "old"),
        lambda: lobby_service.update_room_settings("replace", "alice", 2, 4, connection_id="old"),
    ):
        with pytest.raises(LobbyError) as exc:
            action()
        assert exc.value.code == "CONNECTION_REPLACED"
    assert lobby_service.start("replace", "alice", "new")["ok"]


def test_timeout_prunes_before_late_heartbeat_and_bumps_revision(monkeypatch):
    lobby_service.join("expire", "alice", "c1")
    room = get_lobby_store().get_room("expire")
    now = room.players[0].last_heartbeat
    revision = room.revision
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 60)
    result = lobby_service.heartbeat("expire", "alice", "c1")
    assert not result["present"]
    assert room.players == [] and room.host_id == ""
    assert room.revision > revision


def test_matching_tick_expires_host_cancels_countdown_and_can_restart(monkeypatch):
    now = lobby_service.time.time()
    monkeypatch.setattr(lobby_service.time, "time", lambda: now)
    lobby_service.join("countdown", "alice", "old-host")
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 40)
    lobby_service.join("countdown", "bob", "guest")
    room = get_lobby_store().get_room("countdown")
    assert room.status == LobbyStatus.COUNTDOWN
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 60)
    lobby_service.tick_all_rooms()
    assert room.host_id == "bob"
    assert room.status == LobbyStatus.WAITING and room.countdown_deadline is None
    assert "countdown" not in db.rooms
    lobby_service.join("countdown", "carol", "new-guest")
    assert room.status == LobbyStatus.COUNTDOWN
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 75)
    lobby_service.heartbeat("countdown", "bob", "guest")
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 90)
    lobby_service.tick_all_rooms()
    assert db.get_room("countdown").player_ids == ["bob", "carol"]


def test_expired_guest_never_starts_when_countdown_deadline_also_passed(monkeypatch):
    lobby_service.join("stale", "alice", "c1")
    lobby_service.join("stale", "bob", "c2")
    room = get_lobby_store().get_room("stale")
    now = max(p.last_heartbeat for p in room.players)
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 61)
    lobby_service.tick_all_rooms()
    assert room.status == LobbyStatus.WAITING
    assert not room.players and "stale" not in db.rooms


def test_stale_players_do_not_fill_a_quick_match_before_tick(monkeypatch):
    result = lobby_service.join(None, "alice", "old", min_players=2, max_players=2)
    room = get_lobby_store().get_room(result["room_id"])
    now = room.players[0].last_heartbeat
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 61)
    new = lobby_service.join(None, "bob", "new", min_players=2, max_players=2)
    assert new["room_id"] == room.room_id
    assert room.status == LobbyStatus.WAITING
    assert [p.player_id for p in room.players] == ["bob"]


def test_concurrent_quick_rejoins_keep_one_seat_and_one_connection():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: lobby_service.join(None, "alice", f"c{n}"), range(12)))
    assert len({r["room_id"] for r in results}) == 1
    room = get_lobby_store().get_room(results[0]["room_id"])
    assert len(room.players) == len(room.players[0].connection_ids) == 1


@pytest.mark.parametrize("late_subscribe", [False, True])
def test_replaced_stream_closes_before_match_start(late_subscribe):
    from neo.lobby import sse
    sse.set_broadcast_hook()
    lobby_service.join("streams", "alice", "old")
    q = sse.subscribe("streams")
    stream = sse.event_stream("streams", q, "alice", "old")
    if not late_subscribe:
        assert "lobby_snapshot" in next(stream)
    lobby_service.join("streams", "alice", "new")
    lobby_service.start("streams", "alice", "new")
    assert "connection_replaced" in next(stream)
    with pytest.raises(StopIteration):
        next(stream)
    assert "streams" not in sse._event_queues


def test_expired_stream_does_not_receive_a_later_match_start(monkeypatch):
    from neo.lobby import sse
    sse.set_broadcast_hook()
    lobby_service.join("expired-stream", "alice", "old")
    room = get_lobby_store().get_room("expired-stream")
    q = sse.subscribe(room.room_id)
    stream = sse.event_stream(room.room_id, q, "alice", "old")
    assert "lobby_snapshot" in next(stream)
    now = room.players[0].last_heartbeat
    monkeypatch.setattr(lobby_service.time, "time", lambda: now + 61)
    lobby_service.tick_all_rooms()
    assert "membership_expired" in next(stream)
    stream.close()
