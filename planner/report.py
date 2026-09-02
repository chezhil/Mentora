"""planner.report — build_report(): the report card at the end of a session.

The score is computed deterministically from evaluations (correct/total).
The narrative parts (strong, weak, misconceptions, revise, next_topic) are
written by Gemini from the session history.
"""

from __future__ import annotations

import argparse
import json

from shared.models import LessonReport, SessionState
from prompts import REPORT_PROMPT, fill
import llm


def build_report(session: SessionState) -> LessonReport:
    if not isinstance(session, SessionState):
        session = SessionState.model_validate(session)
    evals = session.evaluations
    if evals:
        score = round(100.0 * sum(e.correct for e in evals) / len(evals), 1)
    else:
        score = 0.0

    turns = "\n".join(
        f"- {t.role}: {t.content[:300]}" for t in session.turns
    )
    evals_text = "\n".join(
        f"- {e.feedback} (correct={e.correct}, "
        f"misconception={e.misconception}, action={e.action})"
        for e in evals
    ) or "no questions were evaluated"

    prompt = fill(
        REPORT_PROMPT,
        PLAN=session.plan.model_dump_json(),
        TURNS=turns,
        EVALUATIONS=evals_text,
    )
    data = llm.generate_json(prompt)

    return LessonReport(
        score=score,
        strong=[str(x) for x in data.get("strong") or []],
        weak=[str(x) for x in data.get("weak") or []],
        misconceptions=[str(x) for x in data.get("misconceptions") or []],
        revise=[str(x) for x in data.get("revise") or []],
        next_topic=str(data.get("next_topic") or ""),
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build a lesson report.")
    parser.add_argument("fixture", help="path to a JSON fixture")
    args = parser.parse_args()
    with open(args.fixture, encoding="utf-8") as f:
        data = json.load(f)
    session = SessionState.model_validate(data["session"])
    result = build_report(session)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    _main()