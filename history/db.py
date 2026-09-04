"""
U4: SQLite history persistence module.
Stores turns and lesson reports in mentora.db.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List

from shared.models import Turn, LessonReport

DB_PATH = Path(__file__).resolve().parent.parent / "mentora.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    conn = _get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        concept_id TEXT,
        timestamp TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        student_id TEXT NOT NULL DEFAULT 'default_student',
        score REAL NOT NULL,
        strong_json TEXT NOT NULL,
        weak_json TEXT NOT NULL,
        misconceptions_json TEXT NOT NULL,
        revise_json TEXT NOT NULL,
        next_topic TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # One row per answered question (mid-lesson and quiz) — the raw material
    # for per-concept mastery and accuracy trends.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        student_id TEXT NOT NULL DEFAULT 'default_student',
        concept_id TEXT,
        concept_name TEXT,
        question_kind TEXT,
        correct INTEGER NOT NULL DEFAULT 0,
        timestamp TEXT NOT NULL
    )
    """)

    # Flashcard SRS state. `ease` is the student's last self-rating
    # (again / good / easy); ease_factor + interval_days drive SM-2 growth
    # (history/srs.py); next_review is ISO when the card is due again.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS flashcards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL DEFAULT 'default_student',
        card_key TEXT NOT NULL,
        front TEXT NOT NULL,
        back TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'lesson',
        ease TEXT NOT NULL DEFAULT 'good',
        ease_factor REAL NOT NULL DEFAULT 2.5,
        interval_days REAL NOT NULL DEFAULT 0.0,
        repetitions INTEGER NOT NULL DEFAULT 0,
        last_reviewed TEXT,
        next_review TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(student_id, card_key)
    )
    """)

    # One row per review — the per-card history the scheduler grows from.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS flashcard_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL DEFAULT 'default_student',
        card_key TEXT NOT NULL,
        rating TEXT NOT NULL,
        interval_days REAL NOT NULL DEFAULT 0.0,
        ease_factor REAL NOT NULL DEFAULT 2.5,
        reviewed_at TEXT NOT NULL
    )
    """)

    conn.commit()
    # Tables created before this migration exist without the SM-2 columns.
    _ensure_column(conn, "flashcards", "ease_factor",
                   "ease_factor REAL NOT NULL DEFAULT 2.5")
    _ensure_column(conn, "flashcards", "interval_days",
                   "interval_days REAL NOT NULL DEFAULT 0.0")

    # Per-student preferences — the daily review goal, plus the sticky
    # 'ever scored 100%' flag that flawless reads (see save_report).
    cur.execute("""
    CREATE TABLE IF NOT EXISTS preferences (
        student_id TEXT PRIMARY KEY,
        daily_goal INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        perfect_lesson INTEGER NOT NULL DEFAULT 0
    )
    """)
    _ensure_column(conn, "preferences", "perfect_lesson",
                   "perfect_lesson INTEGER NOT NULL DEFAULT 0")

    # One row per lesson session, so we can show time studied and streaks.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS study_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        student_id TEXT NOT NULL DEFAULT 'default_student',
        topic TEXT NOT NULL DEFAULT '',
        minutes_planned INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        score REAL
    )
    """)

    conn.commit()
    conn.close()


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """Add a column to an existing table if it is missing."""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def save_turn(session_id: str, turn: Turn) -> None:
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()

    ts_str = turn.timestamp.isoformat() if isinstance(turn.timestamp, datetime) else str(turn.timestamp)
    cur.execute("""
    INSERT INTO turns (session_id, role, content, concept_id, timestamp)
    VALUES (?, ?, ?, ?, ?)
    """, (session_id, turn.role, turn.content, turn.concept_id, ts_str))

    conn.commit()
    conn.close()


def load_turns(session_id: str) -> List[Turn]:
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT role, content, concept_id, timestamp
    FROM turns
    WHERE session_id = ?
    ORDER BY id ASC
    """, (session_id,))

    rows = cur.fetchall()
    conn.close()

    turns: List[Turn] = []
    for r in rows:
        ts = datetime.fromisoformat(r["timestamp"])
        turns.append(
            Turn(
                role=r["role"],
                content=r["content"],
                concept_id=r["concept_id"],
                timestamp=ts
            )
        )
    return turns


def save_report(session_id: str, report: LessonReport, student_id: str = "default_student") -> None:
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()

    now_str = datetime.now().isoformat()
    cur.execute("""
    INSERT INTO reports (session_id, student_id, score, strong_json, weak_json, misconceptions_json, revise_json, next_topic, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(session_id) DO UPDATE SET
        score=excluded.score,
        strong_json=excluded.strong_json,
        weak_json=excluded.weak_json,
        misconceptions_json=excluded.misconceptions_json,
        revise_json=excluded.revise_json,
        next_topic=excluded.next_topic,
        created_at=excluded.created_at
    """, (
        session_id,
        student_id,
        report.score,
        json.dumps(report.strong),
        json.dumps(report.weak),
        json.dumps(report.misconceptions),
        json.dumps(report.revise),
        report.next_topic,
        now_str
    ))

    # Record the perfect fact the moment it happens. A later report for the
    # same session (the quiz submission, or a retake) overwrites the row
    # above, so reading reports alone would let a worse attempt un-earn
    # flawless; this flag is never cleared.
    if report.score >= 99.95:
        cur.execute("""
        INSERT INTO preferences (student_id, daily_goal, updated_at,
                                 perfect_lesson)
        VALUES (?, 0, ?, 1)
        ON CONFLICT(student_id) DO UPDATE SET
            perfect_lesson = 1,
            updated_at = excluded.updated_at
        """, (student_id, now_str))

    conn.commit()
    conn.close()


def load_history(student_id: str = "default_student") -> List[LessonReport]:
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT score, strong_json, weak_json, misconceptions_json, revise_json, next_topic
    FROM reports
    WHERE student_id = ?
    ORDER BY id ASC
    """, (student_id,))

    rows = cur.fetchall()
    conn.close()

    reports: List[LessonReport] = []
    for r in rows:
        reports.append(
            LessonReport(
                score=r["score"],
                strong=json.loads(r["strong_json"]),
                weak=json.loads(r["weak_json"]),
                misconceptions=json.loads(r["misconceptions_json"]),
                revise=json.loads(r["revise_json"]),
                next_topic=r["next_topic"]
            )
        )
    return reports


def record_answer(session_id: str, student_id: str, concept_id: str | None,
                  question_kind: str, correct: bool,
                  concept_name: str | None = None) -> None:
    """Record one answered question for the progress dashboard."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO answers (session_id, student_id, concept_id, concept_name,
                         question_kind, correct, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session_id, student_id, concept_id, concept_name, question_kind,
          int(bool(correct)), datetime.now().isoformat()))
    conn.commit()
    conn.close()


from . import srs


def save_flashcard_review(student_id: str, card_key: str, front: str, back: str,
                          source: str, ease: str) -> float:
    """Run SM-2 on one rating and schedule the card's next review.

    Returns the new interval in days (0 = due again now), so the UI can say
    "next review in N days" right where the rating happened.
    """
    ease = ease if ease in srs.RATING_QUALITY else "good"
    now = datetime.now()
    from datetime import timedelta

    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT ease_factor, interval_days, repetitions
    FROM flashcards WHERE student_id = ? AND card_key = ?
    """, (student_id, card_key))
    row = cur.fetchone()
    ef = float(row["ease_factor"]) if row else srs.DEFAULT_EF
    interval = float(row["interval_days"]) if row else 0.0
    reps = int(row["repetitions"]) if row else 0

    new_reps, new_interval, new_ef = srs.review(ef, interval, reps, ease)
    next_review = now + timedelta(days=new_interval)

    cur.execute("""
    INSERT INTO flashcards (student_id, card_key, front, back, source, ease,
                            ease_factor, interval_days, repetitions,
                            last_reviewed, next_review, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(student_id, card_key) DO UPDATE SET
        front=excluded.front,
        back=excluded.back,
        source=excluded.source,
        ease=excluded.ease,
        ease_factor=excluded.ease_factor,
        interval_days=excluded.interval_days,
        repetitions=excluded.repetitions,
        last_reviewed=excluded.last_reviewed,
        next_review=excluded.next_review,
        updated_at=excluded.updated_at
    """, (student_id, card_key, front, back, source, ease, new_ef,
          new_interval, new_reps, now.isoformat(), next_review.isoformat(),
          now.isoformat()))

    cur.execute("""
    INSERT INTO flashcard_reviews (student_id, card_key, rating,
                                   interval_days, ease_factor, reviewed_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (student_id, card_key, ease, new_interval, new_ef, now.isoformat()))
    conn.commit()
    conn.close()
    return new_interval


def due_flashcards(student_id: str, limit: int = 200) -> list[dict]:
    """Cards whose next_review has arrived, oldest-due first."""
    now = datetime.now().isoformat()
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT card_key, front, back, source, ease, repetitions,
           interval_days, next_review
    FROM flashcards
    WHERE student_id = ? AND next_review <= ?
    ORDER BY next_review ASC
    LIMIT ?
    """, (student_id, now, limit))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_goal(student_id: str) -> int:
    """The student's daily review target; 0 when never set."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT daily_goal FROM preferences WHERE student_id = ?",
                (student_id,))
    row = cur.fetchone()
    conn.close()
    return int(row["daily_goal"]) if row else 0


def set_daily_goal(student_id: str, goal: int) -> None:
    """Persist the daily review target (goal 0 clears it)."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO preferences (student_id, daily_goal, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(student_id) DO UPDATE SET
        daily_goal = excluded.daily_goal,
        updated_at = excluded.updated_at
    """, (student_id, max(0, int(goal)), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def review_summary(student_id: str) -> dict:
    """All review counts from the append-only log in a single query.

    Returns {"today": int, "daily": [int x 7], "all_time": int}.
    ``daily`` is oldest-first for the last 7 calendar days (zero for empty
    days); ``today`` is the count for the current calendar date; ``all_time``
    is the total number of rating events ever logged.
    """
    from datetime import date, timedelta
    today_str = date.today().isoformat()
    week_start = (date.today() - timedelta(days=6)).isoformat()
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    # One query: total count + per-day counts for the last 7 days.
    cur.execute("""
    SELECT
        COUNT(*) AS all_time,
        SUM(CASE WHEN substr(reviewed_at, 1, 10) = ? THEN 1 ELSE 0 END) AS today,
        substr(reviewed_at, 1, 10) AS day,
        COUNT(*) AS day_n
    FROM flashcard_reviews
    WHERE student_id = ?
    GROUP BY day
    HAVING day >= ?
    """, (today_str, student_id, week_start))
    rows = cur.fetchall()
    conn.close()
    all_time = int(rows[0]["all_time"]) if rows else 0
    today_count = int(rows[0]["today"]) if rows else 0
    day_map = {r["day"]: int(r["day_n"]) for r in rows}
    daily = [day_map.get((date.today() - timedelta(days=i)).isoformat(), 0)
             for i in range(6, -1, -1)]
    return {"today": today_count, "daily": daily, "all_time": all_time}


def had_recovery(student_id: str) -> bool:
    """True once any concept was answered wrong and, later, answered right —
    the 'comeback' badge."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT 1 FROM answers a
    JOIN answers b
      ON a.student_id = b.student_id
     AND a.concept_name = b.concept_name
    WHERE a.student_id = ?
      AND a.correct = 0 AND b.correct = 1
      AND b.timestamp > a.timestamp
      AND a.concept_name IS NOT NULL
    LIMIT 1
    """, (student_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def has_perfect_score(student_id: str) -> bool:
    """True once a report scored 100% — the 'flawless' badge.

    The flag is set by save_report the moment a perfect report is written
    and never cleared, so a later quiz submission or retake that overwrites
    the session's report row cannot un-earn it. The reports-table read below
    is only a backstop for databases written before the flag existed.
    """
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT perfect_lesson FROM preferences WHERE student_id = ?",
                (student_id,))
    row = cur.fetchone()
    if row and row["perfect_lesson"]:
        conn.close()
        return True
    cur.execute("""
    SELECT 1 FROM reports WHERE student_id = ? AND score >= 99.95 LIMIT 1
    """, (student_id,))
    found = cur.fetchone() is not None
    conn.close()
    return found


def list_flashcards(student_id: str) -> list[dict]:
    """Every card the student has, newest first — the browse view's source."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT card_key, front, back, source, ease, ease_factor, interval_days,
           repetitions, last_reviewed, next_review, updated_at
    FROM flashcards
    WHERE student_id = ?
    ORDER BY updated_at DESC
    """, (student_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def flashcard_signature(student_id: str) -> tuple:
    """Fingerprint of the student's cards. Changes on any write or delete, so
    a screen holding an in-memory deck can tell an external edit happened
    (dashboard rating, browse edit, a lesson miss) and drop the stale deck."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT card_key, updated_at FROM flashcards
    WHERE student_id = ? ORDER BY card_key
    """, (student_id,))
    rows = tuple((r["card_key"], r["updated_at"]) for r in cur.fetchall())
    conn.close()
    return rows


def update_flashcard(student_id: str, card_key: str, front: str,
                     back: str) -> bool:
    """Edit a card's front/back in place; scheduling state is untouched."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE flashcards SET front = ?, back = ?, updated_at = ?
    WHERE student_id = ? AND card_key = ?
    """, (front, back, datetime.now().isoformat(), student_id, card_key))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def delete_flashcard(student_id: str, card_key: str) -> bool:
    """Remove a card and its whole review history."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM flashcard_reviews WHERE student_id = ? AND card_key = ?",
                (student_id, card_key))
    cur.execute("DELETE FROM flashcards WHERE student_id = ? AND card_key = ?",
                (student_id, card_key))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def review_stats(student_id: str) -> dict:
    """Totals for the dashboard: cards seen, ratings, due now, learned."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(SUM(repetitions), 0) FROM flashcards WHERE student_id = ?",
                (student_id,))
    seen, total_reps = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM flashcards WHERE student_id = ? AND next_review <= ?",
                (student_id, datetime.now().isoformat()))
    due = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM flashcards WHERE student_id = ? AND interval_days >= 21",
                (student_id,))
    learned = cur.fetchone()[0]
    conn.close()
    return {"cards_seen": int(seen or 0), "reviews": int(total_reps or 0),
            "due_now": int(due or 0), "learned": int(learned or 0)}


def record_study_start(session_id: str, student_id: str, topic: str,
                       minutes_planned: int) -> None:
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO study_sessions (session_id, student_id, topic,
                                minutes_planned, started_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(session_id) DO NOTHING
    """, (session_id, student_id, topic, minutes_planned,
          datetime.now().isoformat()))
    conn.commit()
    conn.close()


def record_study_end(session_id: str, score: float | None) -> None:
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE study_sessions SET ended_at = ?, score = ? WHERE session_id = ?",
                (datetime.now().isoformat(), score, session_id))
    conn.commit()
    conn.close()


def _activity_dates(student_id: str) -> set[str]:
    """Every calendar day this student did something, as YYYY-MM-DD."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    dates: set[str] = set()
    for sql in (
        "SELECT timestamp FROM answers WHERE student_id = ?",
        "SELECT created_at FROM reports WHERE student_id = ?",
        "SELECT started_at FROM study_sessions WHERE student_id = ?",
        "SELECT last_reviewed FROM flashcards WHERE student_id = ?",
    ):
        try:
            cur.execute(sql, (student_id,))
            for row in cur.fetchall():
                stamp = row[0]
                if stamp:
                    dates.add(str(stamp)[:10])
        except Exception:
            pass
    conn.close()
    return dates


def study_streak(student_id: str) -> int:
    """Consecutive active days, counting backwards from today (or yesterday
    if today has no activity yet, so a streak survives the night)."""
    from datetime import date, timedelta
    dates = _activity_dates(student_id)
    if not dates:
        return 0
    today = date.today()
    cursor = today if str(today) in dates else today - timedelta(days=1)
    streak = 0
    while str(cursor) in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def concept_mastery(student_id: str) -> list[dict]:
    """Per-concept accuracy across every answered question."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT COALESCE(NULLIF(concept_name, ''), concept_id) AS label,
           COUNT(*) AS n, SUM(correct) AS ok
    FROM answers
    WHERE student_id = ? AND concept_id IS NOT NULL AND concept_id != ''
    GROUP BY label
    ORDER BY n DESC
    """, (student_id,))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        n, ok = int(r["n"]), int(r["ok"] or 0)
        out.append({"concept": r["label"], "total": n,
                    "correct": ok, "accuracy": 100.0 * ok / n if n else 0.0})
    return out


def score_history(student_id: str) -> list[dict]:
    """Finished lessons with their score and date, oldest first."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT topic, started_at, score
    FROM study_sessions
    WHERE student_id = ? AND score IS NOT NULL
    ORDER BY started_at ASC
    """, (student_id,))
    rows = cur.fetchall()
    conn.close()
    return [{"date": str(r["started_at"])[:10], "topic": r["topic"],
             "score": float(r["score"])} for r in rows]


def daily_activity(student_id: str, days: int = 28) -> list[dict]:
    """Activity per day for the last `days` days (oldest first)."""
    from datetime import date, timedelta
    dates = _activity_dates(student_id)
    today = date.today()
    out = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        out.append({"date": str(day), "active": str(day) in dates})
    return out


def xp_earned(student_id: str) -> int:
    """Gamified total: correct answers, reviews, and finished lessons."""
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    xp = 0
    try:
        cur.execute("SELECT COUNT(*) FROM answers WHERE student_id = ? AND correct = 1",
                    (student_id,))
        xp += 10 * int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM flashcards WHERE student_id = ? AND ease != 'again'",
                    (student_id,))
        xp += 5 * int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*), COALESCE(AVG(score), 0) FROM reports WHERE student_id = ?",
                    (student_id,))
        n, avg = cur.fetchone()
        xp += 25 * int(n or 0) + int(avg or 0)
    except Exception:
        pass
    conn.close()
    return xp


def class_summary() -> list[dict]:
    """One row per student, for the teacher's classroom view.

    Reads across every student rather than one, which load_history cannot do.
    Returns [{student_id, lessons, average, latest_topic, weak}] newest first,
    where `weak` is the concepts that student got wrong most often.
    """
    _init_db()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT student_id, score, weak_json, misconceptions_json, next_topic,
           created_at
    FROM reports
    ORDER BY id DESC
    """)
    rows = cur.fetchall()
    conn.close()

    by_student: dict[str, dict] = {}
    for r in rows:
        entry = by_student.setdefault(r["student_id"], {
            "student_id": r["student_id"],
            "lessons": 0,
            "scores": [],
            "weak": [],
            "misconceptions": [],
            "next_topic": r["next_topic"],
            "last_seen": r["created_at"],
        })
        entry["lessons"] += 1
        entry["scores"].append(float(r["score"]))
        try:
            entry["weak"].extend(json.loads(r["weak_json"]))
            entry["misconceptions"].extend(json.loads(r["misconceptions_json"]))
        except Exception:
            pass

    out = []
    for entry in by_student.values():
        scores = entry.pop("scores")
        entry["average"] = sum(scores) / len(scores) if scores else 0.0
        # Keep the order they were first seen in, without duplicates.
        entry["weak"] = list(dict.fromkeys(entry["weak"]))
        entry["misconceptions"] = list(dict.fromkeys(entry["misconceptions"]))
        out.append(entry)
    return sorted(out, key=lambda e: e["last_seen"], reverse=True)
