"""planner.quiz — final_quiz(): exam questions for a finished lesson plan."""

from __future__ import annotations

import argparse
import json

from shared.models import LessonPlan, Question
from prompts import FINAL_QUIZ_PROMPT, fill
import llm

KINDS = ("mcq", "short", "explain", "problem")


def final_quiz(plan: LessonPlan) -> list[Question]:
    if not isinstance(plan, LessonPlan):
        plan = LessonPlan.model_validate(plan)
    prompt = fill(FINAL_QUIZ_PROMPT, PLAN=plan.model_dump_json())
    data = llm.generate_json(prompt)
    ids = {c.id for c in plan.concepts}
    questions: list[Question] = []
    for i, raw in enumerate(data.get("questions") or []):
        concept_id = raw.get("concept_id")
        if concept_id not in ids:
            continue
        kind = raw.get("kind")
        if kind not in KINDS:
            kind = "short"
        questions.append(
            Question(
                id=f"q{i + 1}",
                concept_id=concept_id,
                kind=kind,
                prompt=str(raw.get("prompt", "")),
                options=[str(o) for o in raw.get("options") or []]
                or None,
                expected=str(raw.get("expected", "")),
            )
        )
    if not questions:
        raise llm.LLMError("final_quiz returned no questions.")
    return questions


def _main() -> None:
    parser = argparse.ArgumentParser(description="Generate a final quiz.")
    parser.add_argument("fixture", help="path to a JSON fixture")
    args = parser.parse_args()
    with open(args.fixture, encoding="utf-8") as f:
        data = json.load(f)
    plan = LessonPlan.model_validate(data["plan"])
    result = final_quiz(plan)
    print(json.dumps([q.model_dump() for q in result], indent=2))


if __name__ == "__main__":
    _main()