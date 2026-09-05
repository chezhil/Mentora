"""planner.report — build_report(): the report card at the end of a session.

The score is computed deterministically from evaluations (correct/total).
The narrative parts (strong, weak, misconceptions, revise, next_topic) are
written by the model from the session history.
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
    try:
        data = llm.generate_json(prompt)
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}

    def _lines(key: str) -> list[str]:
        """The list for `key`, whatever the model actually sent.

        `[str(x) for x in data.get(key) or []]` iterates a bare string into
        its characters and raises TypeError on a number — and this is the
        call that produces the report card at the end of a finished lesson,
        so there is no worse place to raise. A JSON `null` response also made
        data None, and the .get below it then raised AttributeError outside
        the try that was meant to cover exactly this.
        """
        value = data.get(key)
        if value is None or isinstance(value, (int, float, bool)):
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        # str(None) is "None", so a null inside the list would be printed on
        # the report card as a strength called "None".
        return [str(x).strip() for x in value
                if x is not None and str(x).strip()]

    strong = _lines("strong")
    weak = _lines("weak")
    misconceptions = _lines("misconceptions")
    revise = _lines("revise")
    next_topic = str(data.get("next_topic") or "").strip()

    # Fallback to evaluations if LLM returned empty or failed
    if not strong and any(e.correct for e in evals):
        strong = [c.name for c in session.plan.concepts[:max(1, len(evals))]]
    if not misconceptions:
        misconceptions = [e.misconception for e in evals if e.misconception]
    if not weak and misconceptions:
        weak = [f"Concepts needing review: {', '.join(misconceptions[:2])}"]
    if not next_topic and session.plan.concepts:
        next_topic = f"Advanced applications of {session.plan.topic}"

    return LessonReport(
        score=score,
        strong=strong,
        weak=weak,
        misconceptions=misconceptions,
        revise=revise,
        next_topic=next_topic,
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