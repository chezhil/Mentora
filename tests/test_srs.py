"""SM-2 scheduler tests — pure function checks on history/srs.py."""

import pytest

from history import srs


def test_again_resets_and_punishes_ease():
    reps, interval, ef = srs.review(2.5, 13.0, 3, "again")
    assert reps == 0
    assert interval == 0.0                     # due again right away
    assert ef == pytest.approx(2.18)           # 2.5 - 0.32


def test_good_grows_geometrically():
    reps, interval, ef = srs.review(2.5, 0.0, 0, "good")
    assert (reps, interval) == (1, 1.0)
    assert ef == pytest.approx(2.36)
    reps, interval, ef = srs.review(ef, interval, reps, "good")
    assert (reps, interval) == (2, 6.0)
    reps, interval, _ = srs.review(ef, interval, reps, "good")
    assert (reps, interval) == (3, 13.0)       # round(6 * 2.22)


def test_easy_head_starts_new_card_and_keeps_max_ease():
    reps, interval, ef = srs.review(2.5, 0.0, 0, "easy")
    assert (reps, interval) == (1, 4.0)
    assert ef == 2.5                            # clamped from 2.6


def test_ef_clamps_at_floor():
    ef = 2.5
    for _ in range(10):
        _, _, ef = srs.review(ef, 0.0, 0, "again")
    assert ef == 1.3