import pytest

from neo.config import load_config
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


def test_coord_hidden_until_reveal():
    db.init_room("r1", ["alice", "bob"], {"scoring": load_config()["scoring"]})
    engine.place_guess("r1", "alice", 0.1, 0.2)
    state = build_state("r1", "alice")
    assert "alice" in state["coords"]
    assert "bob" not in state["coords"]
    assert state["answer_coord"] is None


def test_state_version_in_response():
    db.init_room("r1", ["alice", "bob"], {"scoring": load_config()["scoring"]})
    state = build_state("r1", "alice")
    assert state["state_version"] == 1
