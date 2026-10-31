import pytest

from neo.config import get_scoring_mode_config, load_config
from neo.defs import DIFFICULTY_ORDER, difficulty_at_most
from neo.game import database as db


@pytest.fixture(autouse=True)
def setup_db():
    load_config()
    db.init_database()
    db.rooms.clear()
    yield
    db.rooms.clear()


def test_questions_v3_loads_without_header_as_ids():
    assert len(db.que_db) >= 100
    assert all(isinstance(qid, int) for qid in db.que_db)
    categories = {q.category for q in db.que_db.values()}
    assert categories <= set(DIFFICULTY_ORDER)
    assert "N" in categories
    assert "L" in categories


def test_difficulty_pool_n_is_subset_of_l():
    n_pool = set(db.questions_for_difficulty("N"))
    l_pool = set(db.questions_for_difficulty("L"))
    assert n_pool
    assert l_pool
    assert n_pool.issubset(l_pool)
    assert len(l_pool) > len(n_pool)
    for idx in n_pool:
        assert db.que_db[idx].category in ("E", "N")
    for idx in l_pool - n_pool:
        assert not difficulty_at_most(db.que_db[idx].category, "N")


def test_sample_question_respects_max_difficulty():
    db.init_room(
        "diff_n",
        ["alice"],
        {
            "rounds": 6,
            "difficulty": "N",
            "scoring_strategy": "ranking",
            "scoring": get_scoring_mode_config("ranking"),
        },
    )
    for _ in range(6):
        qid = db.get_room("diff_n").que_history[-1]
        assert difficulty_at_most(db.que_db[qid].category, "N")
        if len(db.get_room("diff_n").que_history) < 6:
            db.sample_question("diff_n")


def test_init_room_fails_when_pool_too_small(monkeypatch):
    only = {
        qid: q
        for qid, q in list(db.que_db.items())
        if q.category == "N"
    }
    keep = dict(list(only.items())[:2])
    monkeypatch.setattr(db, "que_db", keep)
    with pytest.raises(RuntimeError, match="Question pool"):
        db.init_room(
            "tiny",
            ["alice"],
            {
                "rounds": 6,
                "difficulty": "N",
                "scoring_strategy": "ranking",
                "scoring": get_scoring_mode_config("ranking"),
            },
        )


def test_prefetch_does_not_change_round_and_next_round_uses_same_image():
    from neo.game import engine
    from neo.game.state_builder import build_state
    room = db.init_room(
        "prefetch", ["alice"], {"rounds": 3, "difficulty": "L", "scoring_strategy": "distance"},
    )
    current = db.get_current_question("prefetch").image_path
    state = build_state("prefetch", "alice")
    upcoming = state["prefetch_question_img"]
    assert upcoming and upcoming != current
    assert room.round_index == 0
    assert len(room.que_history) == 2
    assert build_state("prefetch", "alice")["prefetch_question_img"] == upcoming
    assert len(room.que_history) == 2
    engine.place_guess("prefetch", "alice", 0.2, 0.3)
    engine.submit("prefetch", "alice")
    engine.agree_next("prefetch", "alice")
    assert db.get_current_question("prefetch").image_path == upcoming
    assert room.round_index == 1
    assert len(room.que_history) == 2
    room.round_index = 2
    assert db.next_question_image("prefetch") is None
