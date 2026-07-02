import pytest

from neo.calc import compute_scaled_damage, distance
from neo.config import load_config


def test_distance_same_point():
    assert distance((0.5, 0.5), (0.5, 0.5)) == 0.0


def test_scaled_damage():
    load_config()
    d = compute_scaled_damage((0.0, 0.0), (0.1, 0.0), 2.0)
    expected = 0.1 * load_config()["scoring"]["distance_scale"] * 2.0
    assert abs(d - expected) < 0.001
