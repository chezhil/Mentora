"""planner.plan — Jyothi's half: turn (topic, profile, doc_id) into a LessonPlan.

The critical invariant: sum(concept.minutes) == profile.time_minutes exactly.
Gemini proposes minutes; this module force-fits them to the budget so no
prompt drift can break the timing requirement.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque

from shared.models import Concept, LearnerProfile, LessonPlan
from prompts import PLAN_PROMPT, fill
import llm

DEPTHS = ("brief", "standard", "deep")

# Coercion fallback if the model emits a depth outside the contract.
_DEPTH_BY_LEVEL = {
    "beginner": "brief",
    "intermediate": "standard",
    "advanced": "deep",
}


def _clean_depth(value: str, level: str) -> str:
    if value in DEPTHS:
        return value
    return _DEPTH_BY_LEVEL.get(level, "standard")


def _resequence(raw_concepts: list[dict], level: str) -> list[Concept]:
    """Renumber ids, drop bad prerequisites, and topologically sort so every
    concept comes after its prerequisites."""
    names = [str(c.get("name", "")).strip() for c in raw_concepts]
    idx_by_name = {name: i for i, name in enumerate(names) if name}
    order_by_name: dict[int, set[int]] = defaultdict(set)
    for i, c in enumerate(raw_concepts):
        for prereq in c.get("prerequisites") or []:
            target = idx_by_name.get(prereq) if isinstance(prereq, str) else None
            if target is None:
                continue
            if target != i and names[target] != names[i]:
                order_by_name[i].add(target)

    indegree = {i: len(order_by_name[i]) for i in range(len(names))}
    children: dict[int, list[int]] = defaultdict(list)
    for node, parents in order_by_name.items():
        for p in parents:
            children[p].append(node)
    queue = deque(i for i in range(len(names)) if indegree[i] == 0)
    ordered: list[int] = []
    while queue:
        i = queue.popleft()
        ordered.append(i)
        for j in children[i]:
            indegree[j] -= 1
            if indegree[j] == 0:
                queue.append(j)
    if len(ordered) != len(names):
        ordered = list(range(len(names)))

    concepts: list[Concept] = []
    for new_pos, old_pos in enumerate(ordered):
        raw = raw_concepts[old_pos]
        deps = {names[p] for p in order_by_name[old_pos]}
        c = Concept(
            id=f"c{new_pos + 1}",
            name=names[old_pos] or f"Concept {new_pos + 1}",
            depth=_clean_depth(str(raw.get("depth", "")), level),
            minutes=float(raw.get("minutes", 0.0)),
        )
        # prerequisites resolved only from concepts placed earlier
        c.prerequisites = _prereq_ids(concepts, deps)
        concepts.append(c)
    return concepts


def _ids_by_name(concepts: list[Concept]) -> dict[str, str]:
    return {c.name: c.id for c in concepts}


def _prereq_ids(concepts: list[Concept], deps: set[str]) -> list[str]:
    ids = _ids_by_name(concepts)
    return [ids[d] for d in deps if d in ids]


def _fit_budget(concepts: list[Concept], target: int) -> list[Concept]:
    """Scale + round concept minutes so they sum to exactly `target`."""
    if not concepts:
        return concepts
    raw = [max(c.minutes, 0.001) for c in concepts]
    total = sum(raw)
    scaled = [m * target / total for m in raw]
    rounded = [round(m, 1) for m in scaled]
    drift = round(target - sum(rounded), 2)
    if drift:
        biggest = max(range(len(rounded)), key=lambda i: rounded[i])
        rounded[biggest] = round(rounded[biggest] + drift, 1)
    for c, m in zip(concepts, rounded):
        c.minutes = m
    return concepts


def plan(
    topic: str,
    profile: LearnerProfile,
    doc_id: str | None = None,
) -> LessonPlan:
    """Build a LessonPlan. doc_id=None means topic-only teaching."""
    if not isinstance(profile, LearnerProfile):
        profile = LearnerProfile.model_validate(profile)
    prompt = fill(
        PLAN_PROMPT,
        LEVEL=profile.level,
        LANGUAGE=profile.language,
        TIME=profile.time_minutes,
        GOAL=profile.goal,
        KNOWN=", ".join(profile.known_concepts) or "nothing specified",
        WEAK=", ".join(profile.weak_concepts) or "nothing specified",
        TOPIC=topic,
        DOC_STATUS="a document is indexed (doc_id=%s)" % doc_id if doc_id
        else "no document — teach the topic from general knowledge",
        DOC_SNIPPET="",
    )
    data = llm.generate_json(prompt)

    raw_concepts = data.get("concepts") or []
    if not raw_concepts:
        raise llm.LLMError("Lesson planner returned no concepts.")

    concepts = _resequence(raw_concepts, profile.level)
    concepts = _fit_budget(concepts, profile.time_minutes)
    if not concepts:
        raise llm.LLMError("Lesson planner returned an empty plan.")

    plan = LessonPlan(
        topic=str(data.get("topic") or topic),
        language=str(data.get("language") or profile.language),
        total_minutes=profile.time_minutes,
        concepts=concepts,
    )
    return plan


def _main() -> None:
    parser = argparse.ArgumentParser(description="Generate a LessonPlan.")
    parser.add_argument("fixture", help="path to a JSON fixture")
    args = parser.parse_args()
    with open(args.fixture, encoding="utf-8") as f:
        data = json.load(f)
    profile = LearnerProfile.model_validate(data["profile"])
    result = plan(data["topic"], profile, data.get("doc_id"))
    print(result.model_dump_json(indent=2))
    used = sum(c.minutes for c in result.concepts)
    print(
        f"\n# total_minutes={result.total_minutes} "
        f"sum(concepts)={used:.2f} OK={abs(used - result.total_minutes) < 1e-9}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    _main()