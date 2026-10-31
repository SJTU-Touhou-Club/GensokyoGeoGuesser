import pytest

from neo.config import get_scoring_mode_config, load_config
from neo.game import database as db
from neo.game import engine
from neo.game.state_builder import build_state


@pytest.fixture(autouse=True)
def setup():
    load_config()
    db.init_database()
    db.rooms.clear()
    engine.set_broadcast(lambda *a: None)
    yield
    db.rooms.clear()


def _cfg():
    return {
        "rounds": 6,
        "difficulty": "L",
        "scoring_strategy": "ranking",
        "scoring": get_scoring_mode_config("ranking"),
    }


def test_coord_hidden_until_reveal():
    db.init_room("r1", ["alice", "bob"], _cfg())
    engine.place_guess("r1", "alice", 0.1, 0.2)
    state = build_state("r1", "alice")
    assert "alice" in state["coords"]
    assert "bob" not in state["coords"]
    assert state["answer_coord"] is None


def test_state_version_in_response():
    db.init_room("r1", ["alice", "bob"], _cfg())
    state = build_state("r1", "alice")
    assert state["state_version"] == 1
    assert state["total_rounds"] == 6
    assert state["difficulty"] == "L"


@pytest.fixture
def client():
    from app import app
    return app.test_client()


def _action(client, action, action_id, sequence, round_number=1, **body):
    return client.post(
        f"/api/{action}?room=r1&player_id=alice",
        json={"action_id": action_id, "connection_id": "c1", "sequence": sequence,
              "round": round_number, **body},
    )


def test_action_retry_returns_ack_without_reapplying(client):
    db.init_room("r1", ["alice"], _cfg())
    first = _action(client, "place_guess", "guess", 1, lat=0.2, lon=0.3)
    version = db.get_room("r1").state_version
    second = _action(client, "place_guess", "guess", 1, lat=0.2, lon=0.3)
    assert first.status_code == second.status_code == 200
    assert first.json["ack"] == second.json["ack"]
    assert second.json["ack"]["action_id"] == "guess"
    assert db.get_room("r1").state_version == version


def test_out_of_order_and_old_round_actions_are_rejected(client):
    db.init_room("r1", ["alice"], _cfg())
    assert _action(client, "place_guess", "new", 2, lat=0.2, lon=0.3).status_code == 200
    assert _action(client, "place_guess", "old", 1, lat=0.8, lon=0.9).json["code"] == "STALE_ACTION"
    assert _action(client, "place_guess", "future", 3, 2, lat=0.8, lon=0.9).json["code"] == "STALE_ROUND"
    assert db.get_room("r1").player_coord["alice"] == (0.2, 0.3)


def test_action_id_cannot_be_reused_with_different_payload(client):
    db.init_room("r1", ["alice"], _cfg())
    _action(client, "place_guess", "same", 1, lat=0.2, lon=0.3)
    result = _action(client, "place_guess", "same", 1, lat=0.7, lon=0.8)
    assert result.status_code == 409
    assert result.json["code"] == "ACTION_CONFLICT"


def test_next_retry_after_round_advance_does_not_advance_again(client):
    db.init_room("r1", ["alice"], _cfg())
    _action(client, "place_guess", "guess", 1, lat=0.2, lon=0.3)
    _action(client, "submit", "submit", 2)
    result = _action(client, "agree_next", "next", 3)
    assert result.status_code == 200
    assert result.json["round"] == 2
    retry = _action(client, "agree_next", "next", 3)
    assert retry.status_code == 200
    assert retry.json["round"] == 2
    assert retry.json["ack"]["round"] == 1
    assert db.get_room("r1").round_index == 1


def test_state_endpoint_is_not_cacheable_and_renews_presence(client):
    room = db.init_room("r1", ["alice"], _cfg())
    result = client.get("/api/state?room=r1&player_id=alice&connection_id=c1")
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert "c1" in room.connection_seen["alice"]


def test_game_stream_initial_sync_heartbeat_and_cleanup(monkeypatch):
    import queue
    from neo.game import sse
    q = sse.subscribe("stream_test")
    stream = sse.event_stream(q, "stream_test")
    assert next(stream) == "data: sync\n\n"
    def empty(timeout):
        assert timeout == 1
        raise queue.Empty
    monkeypatch.setattr(q, "get", empty)
    assert next(stream) == "event: ping\ndata: {}\n\n"
    stream.close()
    assert "stream_test" not in sse._event_queues


def test_game_notifications_are_bounded():
    from neo.game import sse
    q = sse.subscribe("bounded")
    try:
        for _ in range(100):
            sse.broadcast("bounded", "update")
        assert q.qsize() == 1
    finally:
        sse.unsubscribe("bounded", q)
