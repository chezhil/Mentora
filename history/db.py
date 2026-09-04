"""
U4: SQLite history persistence module.
Stores turns and lesson reports in mentora.db.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from shared.models import LessonReport, Turn

DB_PATH = Path(__file__).resolve().parent.parent / "mentora.db"

# _init_db() used to run at the top of EVERY call. Saving one turn therefore
# opened a connection, issued two CREATE TABLE IF NOT EXISTS, committed and
# closed — and then opened a second connection to do the actual insert. The
# orchestrator logs several turns per segment, so that was the hot path.
# The schema cannot change under us mid-run, so do it once.
_SCHEMA_LOCK = threading.Lock()
_schema_ready = False


@contextmanager
def _connect():
    """A connection that is always closed, and a schema that exists.

    The old code called conn.close() as a plain statement after the work, so
    any exception in between — a locked database, bad JSON — leaked the handle.
    """
    _ensure_schema()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _SCHEMA_LOCK:
        if _schema_ready:
            return
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                concept_id TEXT,
                timestamp TEXT NOT NULL
            );

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
            );

            -- Every read filters on one of these, and both tables grow for as
            -- long as the app is used.
            CREATE INDEX IF NOT EXISTS idx_turns_session
                ON turns (session_id, id);
            CREATE INDEX IF NOT EXISTS idx_reports_student
                ON reports (student_id, id);
            """)
            conn.commit()
        finally:
            conn.close()
        _schema_ready = True


def save_turn(session_id: str, turn: Turn) -> None:
    ts_str = (turn.timestamp.isoformat()
              if isinstance(turn.timestamp, datetime) else str(turn.timestamp))
    with _connect() as conn:
        conn.execute("""
        INSERT INTO turns (session_id, role, content, concept_id, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """, (session_id, turn.role, turn.content, turn.concept_id, ts_str))
        conn.commit()


def load_turns(session_id: str) -> list[Turn]:
    with _connect() as conn:
        rows = conn.execute("""
        SELECT role, content, concept_id, timestamp
        FROM turns
        WHERE session_id = ?
        ORDER BY id ASC
        """, (session_id,)).fetchall()

    return [
        Turn(
            role=r["role"],
            content=r["content"],
            concept_id=r["concept_id"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
        )
        for r in rows
    ]


def save_report(session_id: str, report: LessonReport,
                student_id: str = "default_student") -> None:
    now_str = datetime.now().isoformat()
    with _connect() as conn:
        conn.execute("""
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
            now_str,
        ))
        conn.commit()


def load_history(student_id: str = "default_student") -> list[LessonReport]:
    with _connect() as conn:
        rows = conn.execute("""
        SELECT score, strong_json, weak_json, misconceptions_json, revise_json,
               next_topic
        FROM reports
        WHERE student_id = ?
        ORDER BY id ASC
        """, (student_id,)).fetchall()

    return [
        LessonReport(
            score=r["score"],
            strong=json.loads(r["strong_json"]),
            weak=json.loads(r["weak_json"]),
            misconceptions=json.loads(r["misconceptions_json"]),
            revise=json.loads(r["revise_json"]),
            next_topic=r["next_topic"],
        )
        for r in rows
    ]


def class_summary() -> list[dict]:
    """One row per student, for the teacher's classroom view.

    Reads across every student rather than one, which load_history cannot do.
    Returns [{student_id, lessons, average, weak, misconceptions, next_topic,
    last_seen}] newest first. (It said `latest_topic`; the key has always been
    `next_topic`, which is what screens/classroom.py reads.)
    """
    with _connect() as conn:
        rows = conn.execute("""
        SELECT student_id, score, weak_json, misconceptions_json, next_topic,
               created_at
        FROM reports
        ORDER BY id DESC
        """).fetchall()

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
