"""Standalone offline check: runs every Pair B function against its fixture
using a fake LLM, so the plumbing can be verified with no API key.

    python check_offline.py

After the fixture files live in the repo, Pair A / the team can also run
each piece exactly like the contract says:

    python -m teacher.evaluate fixtures/wrong_answer.json
    python -m planner.plan fixtures/plan_topic.json
"""

from __future__ import annotations

import json
import sys

import llm
from tests.fixtures_data import (
    report_session,
    reexplain_plan,
    segment_chunks,
    segment_plan,
    segment_state,
    wrong_answer,
    wrong_question,
)
from tests.test_pair_b import fake_llm

RESULTS = []


def check(name: str, fn, *args, **kwargs) -> object:
    result = fn(*args, **kwargs)
    RESULTS.append(name)
    print(f"[ok]  {name}")
    return result


def main() -> int:
    llm.set_handler(fake_llm)

    from planner.plan import plan
    from planner.path import learning_path
    from planner.quiz import final_quiz
    from planner.report import build_report
    from teacher.evaluate import evaluate
    from teacher.reexplain import reexplain
    from teacher.segment import next_segment

    with open("fixtures/plan_topic.json", encoding="utf-8") as f:
        plan_topic = json.load(f)
    with open("fixtures/plan_document.json", encoding="utf-8") as f:
        plan_doc = json.load(f)
    with open("fixtures/segment_input.json", encoding="utf-8") as f:
        segment_fx = json.load(f)
    with open("fixtures/quiz_plan.json", encoding="utf-8") as f:
        quiz_fx = json.load(f)
    with open("fixtures/report_session.json", encoding="utf-8") as f:
        report_fx = json.load(f)
    with open("fixtures/path_topic.json", encoding="utf-8") as f:
        path_fx = json.load(f)

    p1 = check("planner.plan (topic only)", plan,
               plan_topic["topic"], plan_topic["profile"])
    p2 = check("planner.plan (with document)", plan,
               plan_doc["topic"], plan_doc["profile"], plan_doc["doc_id"])
    tot = sum(c.minutes for c in p1.concepts)
    assert abs(tot - p1.total_minutes) < 1e-9, (tot, p1.total_minutes)
    print(f"    -> concepts={len(p1.concepts)} "
          f"sum={tot:.1f} == budget {p1.total_minutes}")

    quiz = check("planner.quiz (final_quiz)",
                 final_quiz, quiz_fx["plan"])
    print(f"    -> {len(quiz)} questions")

    report = check("planner.report (build_report)",
                   build_report, report_session)
    print(f"    -> score={report.score} strong={report.strong}")

    steps = check("planner.path (learning_path)", learning_path, path_fx["topic"])
    print(f"    -> {len(steps)} steps")

    from planner.plan import plan as _plan  # noqa: F401
    from shared.models import LearnerProfile, StudentResponse

    seg = check("teacher.segment (next_segment)", next_segment,
                segment_plan, segment_state, segment_chunks)
    print(f"    -> script_lang={seg.script[:14]!r} "
          f"citations={len(seg.citations)}")

    ev = check("teacher.evaluate (evaluate)", evaluate,
               wrong_question, wrong_answer)
    print(f"    -> correct={ev.correct} "
          f"misconception={ev.misconception!r}")

    analogies = []
    for attempt in (1, 2, 3):
        seg = check(f"teacher.reexplain (attempt {attempt})", reexplain,
                    "c3", "believes current and resistance are directly "
                    "proportional", attempt, plan=reexplain_plan)
        analogies.append(seg.script)
    assert len(set(analogies)) == 3, "scripts repeated across attempts"
    print("    -> analogies differ across attempts")

    print(f"\nAll {len(RESULTS)} checks passed (offline, fake LLM).")
    return 0


if __name__ == "__main__":
    sys.exit(main())