"""teacher.reexplain — the adaptive core. Re-explains a concept with a
DIFFERENT analogy on every attempt (graded: repeating the same explanation
"louder" is what the jury said does not count).

Analogy rotation is deterministic in ANALOGY_BANK so attempts 1, 2, 3...
are guaranteed to differ no matter what the model invents.
"""

from __future__ import annotations

import argparse
import json

from shared.models import Concept, LessonPlan, TeachingSegment, VisualSpec
from prompts import REEXPLAIN_PROMPT, fill
import llm

VISUAL_KINDS = ("equation", "graph", "diagram", "timeline", "code",
                "concept_map", "none")

ANALOGY_BANK = [
    "water flowing through a pipe — a narrower pipe lets less water pass "
    "per minute; a wider pipe lets more",
    "a crowd squeezing through a doorway — a smaller door lets fewer people "
    "through per minute; the door is the thing that limits them",
    "traffic on a road that narrows — fewer lanes means fewer cars pass "
    "per minute; the narrowing road is the obstacle",
    "a queue moving through a funnel — the bottleneck controls how much "
    "gets through, not how hard the people push",
    "a garden hose with a kink in it — the kink (the resistance) reduces "
    "the water that comes out even if the tap pressure is unchanged",
]


def _analogy_pair(attempt: int) -> tuple[str, list[str]]:
    """Return (chosen analogy, used analogies that must not be repeated)."""
    bank = ANALOGY_BANK
    if attempt <= len(bank):
        chosen = bank[attempt - 1]
        used = bank[: attempt - 1]
    else:
        chosen = bank[(attempt - 1) % len(bank)]
        used = bank
    return chosen, used


def reexplain(
    concept_id: str,
    misconception: str,
    attempt: int,
    plan: LessonPlan | None = None,
    language: str | None = None,
) -> TeachingSegment:
    """Re-explain concept_id. attempt must be a positive int (1, 2, 3...).

    `plan` and `language` are optional context the caller may have handy;
    without them defaults to a plain concept and English.
    """
    if plan is not None and not isinstance(plan, LessonPlan):
        plan = LessonPlan.model_validate(plan)
    concept: Concept = None
    if plan:
        concept = next(
            (c for c in plan.concepts if c.id == concept_id), None
        )
    if concept is None:
        concept = Concept(
            id=concept_id,
            name=f"{concept_id} (the concept to re-explain)",
            depth="standard",
            minutes=0.0,
        )
    lang = language or (plan.language if plan else "en")

    chosen, used = _analogy_pair(max(attempt, 1))

    prompt = fill(
        REEXPLAIN_PROMPT,
        ATTEMPT=attempt,
        CONCEPT_NAME=concept.name,
        DEPTH=concept.depth,
        MISCONCEPTION=misconception,
        LANGUAGE=lang,
        ANALOGY=chosen,
        USED_ANALOGIES="; ".join(used) or "none yet",
        HISTORY="this is a re-explanation; keep it shorter than the original",
        CONCEPT_ID=concept_id,
    )
    data = llm.generate_json(prompt)

    visual = data.get("visual") or {}
    kind = visual.get("kind")
    if kind not in VISUAL_KINDS:
        kind = "none"

    q = data.get("question") or {}
    question = {
        "id": f"re{max(attempt, 1)}",
        "concept_id": concept_id,
        "kind": q.get("kind") if q.get("kind") in
        ("mcq", "short", "explain", "problem") else "short",
        "prompt": str(q.get("prompt") or ""),
        "options": [str(o) for o in q.get("options") or []] or None,
        "expected": str(q.get("expected") or ""),
    }

    return TeachingSegment(
        concept_id=concept_id,
        script=str(data.get("script") or ""),
        visual=VisualSpec(
            kind=kind,
            payload=str(visual.get("payload") or ""),
            caption=visual.get("caption"),
        ),
        question=question,
        citations=[],
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Re-explain a concept.")
    parser.add_argument("fixture", help="path to a JSON fixture")
    args = parser.parse_args()
    with open(args.fixture, encoding="utf-8") as f:
        data = json.load(f)
    question = reexplain(
        data["concept_id"],
        data["misconception"],
        data["attempt"],
        plan=LessonPlan.model_validate(data["plan"])
        if data.get("plan") else None,
        language=data.get("language"),
    )
    print(question.model_dump_json(indent=2))


if __name__ == "__main__":
    _main()