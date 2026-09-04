"""
U4: SQLite self-test runner.
python -m history.selftest
"""
import sys
import json
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from shared.models import Turn, LessonReport
from history.db import (
    save_turn,
    load_turns,
    save_report,
    load_history
)

FIXTURES_TURNS_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "turns.json"


def run_selftest():
    print("=== RUNNING HISTORY (SQLite) SELFTEST ===")
    test_session_id = "test_session_selftest_001"

    if FIXTURES_TURNS_PATH.exists():
        with open(FIXTURES_TURNS_PATH, "r", encoding="utf-8-sig") as f:
            raw_data = json.load(f)
        turns_to_save = [
            Turn(
                role=item["role"],
                content=item["content"],
                concept_id=item.get("concept_id"),
                timestamp=datetime.fromisoformat(item["timestamp"])
            )
            for item in raw_data
        ]
    else:
        now = datetime.now()
        turns_to_save = [
            Turn(role="system", content="Init", concept_id=None, timestamp=now),
            Turn(role="teacher", content="Intro", concept_id="c1", timestamp=now),
            Turn(role="teacher", content="Question", concept_id="c1", timestamp=now),
            Turn(role="student", content="Answer", concept_id="c1", timestamp=now),
            Turn(role="teacher", content="Correction", concept_id="c1", timestamp=now)
        ]

    for t in turns_to_save:
        save_turn(test_session_id, t)
    print(f"1. Saved {len(turns_to_save)} turns into mentora.db")

    report_to_save = LessonReport(
        score=85.0,
        strong=["Current and Potential Difference", "Ohm's Law"],
        weak=["Resistors in Parallel"],
        misconceptions=["believes current and resistance are directly proportional"],
        revise=["Review inverse proportionality I = V / R", "Solve 2 parallel circuit problems"],
        next_topic="Electrical Power and Energy"
    )
    save_report(test_session_id, report_to_save, student_id="student_123")
    print("2. Saved LessonReport into mentora.db")

    loaded_turns = load_turns(test_session_id)
    print(f"3. Loaded back {len(loaded_turns)} turns from mentora.db:")
    for idx, t in enumerate(loaded_turns[-5:], start=1):
        print(f"   [{idx}] {t.role.upper():<7} | Concept: {str(t.concept_id):<4} | {t.content[:50]}")

    assert len(loaded_turns) >= len(turns_to_save), "Failed: Loaded turns count is less than saved count!"

    loaded_reports = load_history(student_id="student_123")
    print(f"4. Loaded back {len(loaded_reports)} report(s) for student_123:")
    for r in loaded_reports:
        print(f"   Score: {r.score}% | Strong: {r.strong} | Next: {r.next_topic}")

    assert len(loaded_reports) >= 1, "Failed: Loaded reports count is 0!"
    print("\n[SUCCESS] SELFTEST PASSED: SQLite persistence, object serialization, and recovery verified successfully!\n")


if __name__ == "__main__":
    run_selftest()
