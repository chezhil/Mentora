"""teacher.segment — next_segment(): the live teaching step.

Walks the plan one concept at a time. Produces the spoken script (in the
session's current language), a visual spec for Pair C to draw, an optional
question, and citations for the source chunks actually used.
"""

from __future__ import annotations

import argparse
import json

from shared.models import (
    LessonPlan,
    SessionState,
    SourceChunk,
    TeachingSegment,
    VisualSpec,
)
from prompts import SEGMENT_PROMPT, fill
import llm
from teacher.adaptive import difficulty_of, recent_history, should_ask

VISUAL_KINDS = ("equation", "graph", "diagram", "timeline", "code",
                "concept_map", "none")
Q_KINDS = ("mcq", "short", "explain", "problem")


def _clean_visual(raw: dict) -> VisualSpec:
    kind = raw.get("kind")
    if kind not in VISUAL_KINDS:
        kind = "none"
    return VisualSpec(
        kind=kind,
        payload=str(raw.get("payload") or ""),
        caption=raw.get("caption"),
    )


def _clean_question(raw: dict | None, concept_id: str, qid: str) -> dict | None:
    if not raw:
        return None
    kind = raw.get("kind")
    if kind not in Q_KINDS:
        kind = "short"
    options = [str(o) for o in raw.get("options") or []] or None
    return {
        "id": qid,
        "concept_id": concept_id,
        "kind": kind,
        "prompt": str(raw.get("prompt") or ""),
        "options": options,
        "expected": str(raw.get("expected") or ""),
    }


def next_segment(
    plan: LessonPlan,
    state: SessionState,
    chunks: list[SourceChunk],
) -> TeachingSegment:
    if not isinstance(plan, LessonPlan):
        plan = LessonPlan.model_validate(plan)
    if not isinstance(state, SessionState):
        state = SessionState.model_validate(state)
    chunks = [SourceChunk.model_validate(c) for c in chunks]
    index = min(state.current_concept, len(plan.concepts) - 1)
    concept = plan.concepts[index]

    numbered_chunks = "\n".join(
        f"[{i}] (score {c.score:.2f}) {c.text[:400]}" for i, c in enumerate(chunks)
    ) or "no supporting material"

    ask = should_ask(state)
    qid = f"q{len(state.evaluations) + 1}"

    prompt = fill(
        SEGMENT_PROMPT,
        TOPIC=plan.topic,
        LANGUAGE=state.profile.language,
        DIFFICULTY=difficulty_of(state),
        CONCEPT=f"{concept.name} (id {concept.id})",
        MINUTES=concept.minutes,
        HISTORY=recent_history(state),
        CHUNKS=numbered_chunks,
        ASK=str(ask).lower(),
        CONCEPT_ID=concept.id,
    )
    data = llm.generate_json(prompt)

    question = _clean_question(data.get("question"), concept.id, qid)
    if not ask:
        question = None
    if ask and question is None:
        question = _clean_question(
            {"kind": "short", "prompt": "", "expected": ""},
            concept.id, qid)

    used = [int(i) for i in data.get("used_chunk_indexes") or []]
    citations = [chunks[i] for i in used if 0 <= i < len(chunks)]

    return TeachingSegment(
        concept_id=concept.id,
        script=str(data.get("script") or ""),
        visual=_clean_visual(data.get("visual") or {}),
        question=question,
        citations=citations,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Generate a teaching segment.")
    parser.add_argument("fixture", help="path to a JSON fixture")
    args = parser.parse_args()
    with open(args.fixture, encoding="utf-8") as f:
        data = json.load(f)
    plan = LessonPlan.model_validate(data["plan"])
    state = SessionState.model_validate(data["state"])
    chunks = [SourceChunk.model_validate(c) for c in data["chunks"]]
    result = next_segment(plan, state, chunks)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    _main()