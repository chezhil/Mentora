"""teacher.evaluate — the 20-mark core. Marks a student answer and NAMES the
misconception that produced it (never just "wrong")."""

from __future__ import annotations

import argparse
import json

from shared.models import Evaluation, Question, StudentResponse
from prompts import EVALUATE_PROMPT, fill
import llm

ACTIONS = ("continue", "reexplain", "simplify", "harden", "example")


def _normalise(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def evaluate(question: Question, response: StudentResponse) -> Evaluation:
    # Deterministic shortcut: exact match is always correct.
    exact = question.expected and (
        _normalise(response.answer) == _normalise(question.expected)
        or (question.options
            and any(
                _normalise(response.answer) == _normalise(o)
                for o in question.options
            ))
    )

    if exact:
        return Evaluation(
            correct=True,
            misconception=None,
            action="continue",
            feedback="Correct! Well done.",
        )

    prompt = fill(
        EVALUATE_PROMPT,
        PROMPT=question.prompt,
        KIND=question.kind,
        OPTIONS=", ".join(question.options) if question.options else "none",
        EXPECTED=question.expected,
        ANSWER=response.answer,
    )
    data = llm.generate_json(prompt)

    correct = bool(data.get("correct")) if not exact else True
    action = data.get("action")
    if action not in ACTIONS:
        action = "continue" if correct else "reexplain"
    misconception = data.get("misconception")
    if correct:
        misconception = None
    return Evaluation(
        correct=correct,
        misconception=(str(misconception) if misconception else None),
        action=action,
        feedback=str(data.get("feedback") or ""),
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a student answer.")
    parser.add_argument("fixture", help="path to a JSON fixture")
    args = parser.parse_args()
    with open(args.fixture, encoding="utf-8") as f:
        data = json.load(f)
    question = Question.model_validate(data["question"])
    response = StudentResponse.model_validate(data["response"])
    result = evaluate(question, response)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    _main()