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
import re

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
    concept comes after its prerequisites. Gemini is asked to write
    prerequisites as ids of ITS OWN listing order (its 'c1' = its first
    concept), which we map onto listing positions before renumbering."""
    names = [str(c.get("name", "")).strip() for c in raw_concepts]
    idx_by_name = {name: i for i, name in enumerate(names) if name}
    id_to_pos = {f"c{i + 1}": i for i in range(len(raw_concepts))}

    parents: dict[int, set[int]] = defaultdict(set)
    for i, c in enumerate(raw_concepts):
        for prereq in c.get("prerequisites") or []:
            if not isinstance(prereq, str):
                continue
            if re.fullmatch(r"c\d+", prereq):
                target = id_to_pos.get(prereq)
            else:
                target = idx_by_name.get(prereq)
            if target is None or target == i or names[target] == names[i]:
                continue
            parents[i].add(target)

    indegree = {i: len(parents[i]) for i in range(len(names))}
    children: dict[int, list[int]] = defaultdict(list)
    for node, ps in parents.items():
        for p in ps:
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

    new_id_of_old = {old: f"c{i + 1}" for i, old in enumerate(ordered)}
    concepts: list[Concept] = []
    for new_pos, old in enumerate(ordered):
        raw = raw_concepts[old]
        prereqs = sorted(
            ({new_id_of_old[p] for p in parents[old]}),
            key=lambda x: int(x[1:]),
        )
        concepts.append(
            Concept(
                id=f"c{new_pos + 1}",
                name=names[old] or f"Concept {new_pos + 1}",
                depth=_clean_depth(str(raw.get("depth", "")), level),
                minutes=float(raw.get("minutes", 0.0)),
                prerequisites=prereqs,
            )
        )
    return concepts


def _fit_budget(concepts: list[Concept], target: int) -> list[Concept]:
    """Scale + round concept minutes so they sum to exactly `target`."""
    if not concepts:
        return concepts
    raw = [max(c.minutes, 0.001) for c in concepts]
    total = sum(raw)
    scaled = [m * target / total for m in raw]
    rounded = [round(m, 1) for m in scaled]
    # Push the rounding drift onto the largest slices first, and never below
    # 0.1 -- a concept billed at -0.4 minutes is nonsense, and the invariant
    # every caller relies on is that the slices SUM to the budget.
    drift = round(target - sum(rounded), 2)
    for i in sorted(range(len(rounded)), key=lambda i: rounded[i], reverse=True):
        if not drift:
            break
        take = round(max(0.1, rounded[i] + drift) - rounded[i], 1)
        rounded[i] = round(rounded[i] + take, 1)
        drift = round(drift - take, 2)
    for c, m in zip(concepts, rounded, strict=True):
        c.minutes = m
    return concepts


def plan(
    topic: str,
    profile: LearnerProfile,
    doc_id: str | None = None,
    days: int = 1,
) -> LessonPlan | list[LessonPlan]:
    """Build a LessonPlan, or a list of them when days > 1.

    doc_id=None means topic-only teaching.

    The return type is decided by `days` ALONE, never by how many sessions the
    model happened to emit. It used to be `days == 1 and len(plans) == 1`, so a
    model that ignored the one-session instruction returned a list to a caller
    expecting a LessonPlan — and orchestrator.start_session fed that straight
    into SessionState(plan=...), which raises a pydantic ValidationError with
    nothing in the message about the real cause.
    """
    if not isinstance(profile, LearnerProfile):
        profile = LearnerProfile.model_validate(profile)
    prompt = fill(
        PLAN_PROMPT,
        DAYS=days,
        LEVEL=profile.level,
        LANGUAGE=profile.language,
        TIME=profile.time_minutes,
        GOAL=profile.goal,
        KNOWN=", ".join(profile.known_concepts) or "nothing specified",
        WEAK=", ".join(profile.weak_concepts) or "nothing specified",
        TOPIC=topic,
        DOC_STATUS=(f"a document is indexed (doc_id={doc_id})" if doc_id
                    else "no document — teach the topic from general knowledge"),
    )
    data = llm.generate_json(prompt)

    sessions_data = data.get("sessions")
    if not sessions_data:
        # fallback if model ignores sessions format
        sessions_data = [data]

    plans = []
    for s_data in sessions_data:
        raw_concepts = s_data.get("concepts") or []
        if not raw_concepts:
            raise llm.LLMError("Lesson planner returned no concepts in a session.")

        concepts = _resequence(raw_concepts, profile.level)
        concepts = _fit_budget(concepts, profile.time_minutes)
        if not concepts:
            raise llm.LLMError("Lesson planner returned an empty plan.")

        plan_obj = LessonPlan(
            topic=str(s_data.get("topic") or topic),
            language=str(s_data.get("language") or profile.language),
            total_minutes=profile.time_minutes,
            concepts=concepts,
        )
        plans.append(plan_obj)
    
    return plans[0] if days == 1 else plans


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