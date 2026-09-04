"""SM-2 spaced repetition — pure functions, no I/O.

The student rates each card Again / Good / Easy, mapped to SM-2 qualities
2 / 3 / 5. A correct review grows the interval geometrically through an
easiness factor; a wrong answer resets the card to due-now (relearning);
Easy on a fresh card gets a 4-day head start so the rating means something
on the very first review instead of only differentiating later.

Pure so it is trivially testable and so the persistence layer owns the
single place that touches SQL.
"""

RATING_QUALITY = {"again": 2, "good": 3, "easy": 5}
MIN_EF = 1.3
MAX_EF = 2.5
DEFAULT_EF = 2.5


def _quality_delta(quality: int) -> float:
    """SM-2 easiness adjustment for a rating quality (0-5)."""
    return 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)


def clamp_ef(ef: float) -> float:
    return max(MIN_EF, min(MAX_EF, ef))


def review(ef: float, interval_days: float, repetitions: int,
           rating: str) -> tuple[int, float, float]:
    """Next (repetitions, interval_days, ease_factor) for one rating."""
    quality = RATING_QUALITY[rating]
    new_ef = clamp_ef(ef + _quality_delta(quality))

    if quality < 3:                    # Again — relearn from scratch
        return 0, 0.0, new_ef

    reps = repetitions + 1
    if reps == 1:
        interval = 1.0 if rating == "good" else 4.0
    elif reps == 2:
        interval = 6.0
    else:
        interval = max(1.0, round(interval_days * ef))
    return reps, float(interval), new_ef