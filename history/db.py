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

    conn.commit()
    conn.close()


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
