"""Populate a demo classroom so the teacher view has something to show.

Everything written here is INVENTED. It exists so the classroom, the reteach
list and the per-student drill-down can be looked at without waiting for ten
students to sit ten lessons, and it is written through the same tables the
teaching engine writes, so the views need no special case for it.

    python seed_demo_class.py           # write the demo class
    python seed_demo_class.py --clear   # remove it again, exactly

--clear deletes only the usernames in ROSTER below, so real records sitting
in the same database are untouched. Run it before a real demo: a classroom
that mixes invented students with real ones is worse than either.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent / "mentora.db"

UNIT = "Electricity and Circuits"

CONCEPTS = [
    "What is electric charge?",
    "Voltage as potential difference",
    "Current as rate of flow",
    "Resistance and Ohm's law",
    "Series and parallel circuits",
    "Electrical power (P = V x I)",
]

TOPICS = [
    "Introduction to electric charge",
    "Voltage, current and resistance",
    "Ohm's law in practice",
    "Series and parallel circuits",
    "Electrical power and energy",
]

# The three the class shares. A reteach list is only interesting when more
# than one student holds the same wrong idea, so these are handed out on
# purpose rather than sampled.
SHARED = [
    "believes current is used up as it flows around a circuit",
    "confuses voltage with current",
    "thinks resistance increases when voltage increases",
]

PERSONAL = [
    "adds resistances in parallel as if they were in series",
    "does not convert milliamps to amps before using I = V/R",
    "reads a circuit diagram right to left",
    "treats the battery as a constant-current source",
    "forgets that power depends on both voltage and current",
    "believes a thicker wire has more resistance",
]

STRONG = [
    "Defining charge and its units",
    "Reading a circuit diagram",
    "Applying V = I x R",
    "Identifying series and parallel branches",
    "Calculating power from voltage and current",
]

# name, archetype, how many lessons. Archetypes shape the score curve, so the
# classroom shows the shapes a teacher actually has to act on.
ROSTER = [
    ("priya",   "strong",     4),
    ("arjun",   "improving",  4),
    ("sana",    "struggling", 3),
    ("marcus",  "improving",  3),
    ("ling",    "strong",     3),
    ("tomas",   "declining",  4),
    ("aisha",   "middling",   3),
    ("daniel",  "struggling", 4),
    ("yusuf",   "middling",   2),
    ("rin",     "strong",     2),
]

CURVES = {
    "strong":     [78, 85, 88, 92],
    "improving":  [41, 55, 70, 82],
    "struggling": [22, 31, 28, 38],
    "declining":  [80, 68, 55, 44],
    "middling":   [58, 62, 57, 65],
}


# Left behind by automated testing rather than by a person: no login owns
# them, and their "lessons" are things like a topic typed to check an error
# path. They make the classroom read like a bug report, so --tidy removes
# them. The real 'student' account is never touched here.
TEST_IDS = ["default_student", "e2e_check", "student_123", "test", "stress"]


def tidy(conn) -> int:
    marks = ",".join("?" * len(TEST_IDS))
    sessions = [r[0] for r in conn.execute(
        f"SELECT session_id FROM study_sessions WHERE student_id IN ({marks})",
        TEST_IDS)]
    removed = 0
    for table in ("reports", "answers", "study_sessions", "flashcards", "preferences"):
        removed += conn.execute(
            f"DELETE FROM {table} WHERE student_id IN ({marks})", TEST_IDS).rowcount
    if sessions:
        smarks = ",".join("?" * len(sessions))
        removed += conn.execute(
            f"DELETE FROM turns WHERE session_id IN ({smarks})", sessions).rowcount
    conn.commit()
    return removed


def _rows(conn, sql, args=()):
    return list(conn.execute(sql, args))


def clear(conn) -> int:
    names = [n for n, _, _ in ROSTER]
    marks = ",".join("?" * len(names))
    sessions = [r[0] for r in _rows(
        conn, f"SELECT session_id FROM study_sessions WHERE student_id IN ({marks})", names)]
    removed = 0
    for table, col in (("reports", "student_id"), ("answers", "student_id"),
                       ("study_sessions", "student_id"), ("flashcards", "student_id"),
                       ("preferences", "student_id")):
        cur = conn.execute(f"DELETE FROM {table} WHERE {col} IN ({marks})", names)
        removed += cur.rowcount
    if sessions:
        smarks = ",".join("?" * len(sessions))
        cur = conn.execute(f"DELETE FROM turns WHERE session_id IN ({smarks})", sessions)
        removed += cur.rowcount
    cur = conn.execute(f"DELETE FROM users WHERE username IN ({marks})", names)
    removed += cur.rowcount
    conn.commit()
    return removed


def seed(conn) -> None:
    rng = random.Random(20260905)          # same class every run
    now = datetime.now()

    # Accounts, so a teacher can sign in as one and see their side.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent / "web"))
    try:
        import auth
        auth.init_auth_db()
    except Exception:
        auth = None

    for i, (name, archetype, lessons) in enumerate(ROSTER):
        if auth is not None:
            try:
                auth.create_user(f"{name}@class.mentora.ai", name, "demo1234", "student")
            except Exception:
                pass                        # already there

        curve = CURVES[archetype]
        # Everyone shares at least one class-wide misconception; the shape of
        # the reteach list is the point of the demo.
        mine = [SHARED[i % len(SHARED)]]
        if archetype in ("struggling", "declining"):
            mine.append(SHARED[(i + 1) % len(SHARED)])
        mine.append(PERSONAL[i % len(PERSONAL)])

        for n in range(lessons):
            when = now - timedelta(days=(lessons - n) * 4 + rng.randint(0, 2),
                                   hours=rng.randint(0, 8))
            ended = when + timedelta(minutes=rng.randint(6, 22))
            score = float(min(100, max(0, curve[min(n, len(curve) - 1)]
                                       + rng.randint(-4, 4))))
            session_id = f"demo{i:02d}{n:02d}{rng.randint(1000, 9999)}"
            topic = TOPICS[(i + n) % len(TOPICS)]

            conn.execute("""
                INSERT OR REPLACE INTO study_sessions
                (session_id, student_id, topic, minutes_planned, started_at, ended_at, score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (session_id, name, topic, rng.choice([10, 15, 20]),
                  when.isoformat(), ended.isoformat(), score))

            weak = [c for c in CONCEPTS if rng.random() < (0.55 if score < 60 else 0.2)]
            strong_now = rng.sample(STRONG, k=2 if score >= 60 else 1)
            misc = mine[:2] if score < 70 else mine[:1]

            conn.execute("""
                INSERT OR REPLACE INTO reports
                (session_id, student_id, score, strong_json, weak_json,
                 misconceptions_json, revise_json, next_topic, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (session_id, name, score, json.dumps(strong_now),
                  json.dumps(weak), json.dumps(misc),
                  json.dumps(["Practise two more problems on " + topic.lower()]),
                  TOPICS[(i + n + 1) % len(TOPICS)], ended.isoformat()))

            # Per-question answers, so "hardest concepts" is counted rather
            # than asserted. Accuracy tracks the lesson score.
            for concept in rng.sample(CONCEPTS, k=rng.randint(3, 5)):
                for _ in range(rng.randint(1, 2)):
                    correct = 1 if rng.random() < (score / 100.0) else 0
                    conn.execute("""
                        INSERT INTO answers
                        (session_id, student_id, concept_id, concept_name,
                         question_kind, correct, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (session_id, name, f"c{CONCEPTS.index(concept) + 1}",
                          concept, rng.choice(["mcq", "short", "problem"]),
                          correct, ended.isoformat()))

            # A couple of turns, so the transcript link opens something.
            for role, text in (
                ("system", f"Session opened: {topic}, {UNIT}."),
                ("teacher", f"Let's look at {topic.lower()}. "
                            "Think about what the battery is actually doing."),
                ("student", "Is it pushing the electrons around?"),
                ("teacher", "That's the idea — the battery provides the push, "
                            "which we measure as voltage."),
            ):
                conn.execute("""
                    INSERT INTO turns (session_id, role, content, concept_id, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (session_id, role, text, "c1", ended.isoformat()))

        # A small deck each, some of it due.
        for k, concept in enumerate(rng.sample(CONCEPTS, k=3)):
            due = now - timedelta(days=rng.randint(0, 3)) if k == 0 else \
                  now + timedelta(days=rng.randint(1, 9))
            conn.execute("""
                INSERT OR REPLACE INTO flashcards
                (student_id, card_key, front, back, source, ease, ease_factor,
                 interval_days, repetitions, last_reviewed, next_review, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, f"concept:{name}:{k}", concept,
                  "See the lesson notes for the worked example.", "lesson",
                  rng.choice(["again", "good", "easy"]), 2.3,
                  float(rng.randint(0, 9)), rng.randint(0, 3),
                  (now - timedelta(days=4)).isoformat(), due.isoformat(),
                  now.isoformat()))

        conn.execute("""
            INSERT OR REPLACE INTO preferences
            (student_id, daily_goal, persona, language, difficulty, avatar,
             auto_quiz, teacher, pending_uploads, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, rng.choice([5, 10, 15]),
              rng.choice(["socratic", "strict", "friendly"]), "en",
              "beginner" if archetype == "struggling" else "intermediate",
              rng.choice(["f", "m"]), 1,
              rng.choice(["maya", "arjun", "sara", "noor", "omar", "kenji"]),
              "[]", now.isoformat()))

    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clear", action="store_true",
                    help="remove the demo class and exit")
    ap.add_argument("--tidy", action="store_true",
                    help="also drop records left by automated testing")
    ap.add_argument("--reset-student", action="store_true",
                    help="also wipe the 'student' account's own history "
                         "(its lessons, answers and cards) -- use before a "
                         "demo if that account was used for testing")
    args = ap.parse_args()

    if not DB.exists():
        print(f"No database at {DB}. Run the app once first.")
        return 1

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        removed = clear(conn)
        if args.tidy:
            gone = tidy(conn)
            print(f"Removed {gone} rows left by automated testing.")
        if args.reset_student:
            # Separate flag on purpose: this is a real account someone signs
            # in as, so emptying its history is a decision, not tidying.
            gone = 0
            sessions = [r[0] for r in conn.execute(
                "SELECT session_id FROM study_sessions WHERE student_id='student'")]
            for table in ("reports", "answers", "study_sessions", "flashcards"):
                gone += conn.execute(
                    f"DELETE FROM {table} WHERE student_id='student'").rowcount
            if sessions:
                marks = ",".join("?" * len(sessions))
                gone += conn.execute(
                    f"DELETE FROM turns WHERE session_id IN ({marks})", sessions).rowcount
            conn.commit()
            print(f"Cleared the 'student' account's history ({gone} rows). "
                  "The login itself is untouched.")
        if args.clear:
            print(f"Removed the demo class ({removed} rows).")
            return 0
        seed(conn)
        students = len(ROSTER)
        lessons = _rows(conn, "SELECT COUNT(*) FROM reports WHERE student_id IN "
                              "(%s)" % ",".join("?" * students),
                        [n for n, _, _ in ROSTER])[0][0]
        answers = _rows(conn, "SELECT COUNT(*) FROM answers WHERE student_id IN "
                              "(%s)" % ",".join("?" * students),
                        [n for n, _, _ in ROSTER])[0][0]
        print(f"Demo class written: {students} students, {lessons} lessons, "
              f"{answers} answered questions.")
        print("Sign in as teacher/teacher123 and open /teacher.")
        print("Each demo student's own login is <name>/demo1234.")
        print("Remove it with: python seed_demo_class.py --clear")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
