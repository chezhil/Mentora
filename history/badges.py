"""Achievement badges — pure catalog + evaluation.

No events, no pipeline: every badge is decided from the aggregates the
dashboard already computes (lessons finished, day streak, total card
ratings) plus two boolean history facts (a concept answered right after
being answered wrong, and a 100% lesson score). Titles and descriptions are
localized on the screen via ``badge.<id>.title`` / ``badge.<id>.how`` keys.

The catalog order is the progression: the first badge that is not yet
earned is the one shown as "next".
"""

CATALOG = [
    # (id, icon, metric|flag, target)
    {"id": "first_lesson", "icon": "🎓", "metric": "lessons", "target": 1},
    {"id": "scholar", "icon": "📚", "metric": "lessons", "target": 5},
    {"id": "veteran", "icon": "🏅", "metric": "lessons", "target": 10},
    {"id": "streak_3", "icon": "🔥", "metric": "streak", "target": 3},
    {"id": "streak_7", "icon": "🔥", "metric": "streak", "target": 7},
    {"id": "streak_30", "icon": "🔥", "metric": "streak", "target": 30},
    {"id": "cards_10", "icon": "🃏", "metric": "reviews", "target": 10},
    {"id": "cards_100", "icon": "🃏", "metric": "reviews", "target": 100},
    {"id": "comeback", "icon": "💪", "flag": "recovery"},
    {"id": "flawless", "icon": "🎯", "flag": "perfect"},
]


def _is_earned(badge: dict, stats: dict) -> bool:
    if "flag" in badge:
        return bool(stats.get(badge["flag"]))
    return int(stats.get(badge["metric"], 0)) >= int(badge["target"])


def evaluate(stats: dict) -> dict:
    """Split the catalog into earned/locked and name the next one.

    ``stats``: lessons, streak, reviews (ints) and recovery, perfect (bools).
    Returns {"earned": [...], "locked": [...], "next": {...}|None}; each badge
    carries id + icon, and locked ones also carry ``remaining`` (count left,
    None for boolean badges) and ``progress`` (0..1). Titles live in i18n.
    """
    earned, locked = [], []
    for badge in CATALOG:
        entry = {"id": badge["id"], "icon": badge["icon"]}
        if _is_earned(badge, stats):
            earned.append(entry)
            continue
        if "metric" in badge:
            value = int(stats.get(badge["metric"], 0))
            entry["remaining"] = max(1, int(badge["target"]) - value)
            entry["progress"] = min(1.0, value / float(badge["target"]))
            entry["value"] = value
            entry["target"] = int(badge["target"])
        else:
            entry["remaining"] = None
            entry["progress"] = 0.0
        locked.append(entry)
    return {"earned": earned, "locked": locked,
            "next": locked[0] if locked else None}
