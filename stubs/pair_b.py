"""STUB for Pair B (Jyothi + Naman) — planner/ and teacher/.

Real signatures, fake thinking. Jyothi and Naman: your functions must return
these shapes. The values are nonsense; the structure is the contract.
"""

from datetime import datetime, timezone

from shared.models import (
    Concept, Evaluation, LearnerProfile, LessonPlan, LessonReport, Question,
    SessionState, SourceChunk, StudentResponse, TeachingSegment, VisualSpec,
)

DEPTH_FOR_LEVEL = {
    "beginner": "brief",
    "intermediate": "standard",
    "advanced": "deep",
}

# reexplain() MUST use a different analogy per attempt. This list is the
# single most-graded behaviour in the project — repeating an explanation is
# what the rubric explicitly marks against.
ANALOGIES = [
    "water flowing through a pipe",
    "a crowd squeezing through a doorway",
    "cars slowing on a narrowing road",
    "a queue at a ticket counter",
]

VISUAL_CYCLE = ["diagram", "equation", "graph", "concept_map", "timeline", "code"]


def plan(topic: str, profile: LearnerProfile,
         doc_id: str | None = None) -> LessonPlan:
    """MUST: minutes sum to profile.time_minutes. MUST: work with doc_id=None."""
    if profile.time_minutes <= 5:
        names = ["what it is", "the one rule that matters"]
    elif profile.time_minutes <= 20:
        names = ["foundations", "the core idea", "worked example", "common mistakes"]
    else:
        names = ["foundations", "the core idea", "the maths", "worked example",
                 "common mistakes", "where it is used"]

    # Split the time so it sums EXACTLY. Remainder lands on the last concept.
    n = len(names)
    base = profile.time_minutes // n
    minutes = [float(base)] * n
    minutes[-1] += profile.time_minutes - sum(minutes)

    depth = DEPTH_FOR_LEVEL[profile.level]
    concepts = [
        Concept(
            id=f"c{i + 1}",
            name=f"{topic}: {name}",
            depth=depth,
            minutes=minutes[i],
            prerequisites=[f"c{i}"] if i else [],
        )
        for i, name in enumerate(names)
    ]
    return LessonPlan(
        topic=topic,
        language=profile.language,
        total_minutes=profile.time_minutes,
        concepts=concepts,
    )


def next_segment(plan: LessonPlan, state: SessionState,
                 chunks: list[SourceChunk]) -> TeachingSegment:
    """MUST: script in state.profile.language. MUST: citations copied from chunks."""
    i = min(state.current_concept, len(plan.concepts) - 1)
    concept = plan.concepts[i]
    lang = state.profile.language

    grounded = ""
    if chunks:
        pages = sorted({c.page for c in chunks if c.page is not None})
        if pages:
            grounded = f" (grounded in page {pages[0]} of your material)"

    script = (
        f"[{lang}] Let's look at {concept.name}.{grounded} "
        f"Here is the short version, then one example, then a question for you."
    )

    return TeachingSegment(
        concept_id=concept.id,
        script=script,
        visual=VisualSpec(
            kind=VISUAL_CYCLE[i % len(VISUAL_CYCLE)],
            payload=f"placeholder payload for {concept.name}",
            caption=concept.name,
        ),
        question=Question(
            id=f"q_{concept.id}",
            concept_id=concept.id,
            kind="short",
            prompt=f"In your own words: what happens in {concept.name}?",
            expected="decreases",
        ),
        citations=list(chunks),
    )


def evaluate(question: Question, response: StudentResponse) -> Evaluation:
    """MUST: misconception NAMES the specific error, never 'wrong answer'."""
    answer = response.answer.strip().lower()

    if not answer:
        return Evaluation(
            correct=False,
            misconception="gave no answer, so understanding is unknown",
            action="reexplain",
            feedback="Have a go even if you are unsure — a wrong answer tells me more than a blank one.",
        )

    if question.expected.lower() in answer:
        return Evaluation(
            correct=True,
            misconception=None,
            action="continue",
            feedback="That's right, and you said it cleanly. Moving on.",
        )

    # The brief's own example: the student thinks current rises with resistance.
    if any(w in answer for w in ("increase", "rises", "more", "badhta", "up")):
        return Evaluation(
            correct=False,
            misconception="believes current and resistance are directly proportional",
            action="reexplain",
            feedback="Not quite — you have the relationship the right way round for voltage, but backwards for resistance.",
        )

    return Evaluation(
        correct=False,
        misconception="cannot yet state the relationship between the two quantities",
        action="example",
        feedback="Close to the idea but not yet precise. Let me show you one more case.",
    )


def reexplain(concept_id: str, misconception: str, attempt: int,
              state: SessionState | None = None) -> TeachingSegment:
    """MUST: a DIFFERENT ANALOGY for each value of attempt.

    `state` was added to the contract after Pair B built against it — it lets
    the re-explanation use what the student has already been told.
    """
    analogy = ANALOGIES[(attempt - 1) % len(ANALOGIES)]
    return TeachingSegment(
        concept_id=concept_id,
        script=(
            f"Let's try that a different way. Think of it as {analogy}. "
            f"You said something that suggests you {misconception}, "
            f"so watch what happens here."
        ),
        visual=VisualSpec(
            kind="diagram",
            payload=f"analogy: {analogy}",
            caption=f"Attempt {attempt}: {analogy}",
        ),
        question=Question(
            id=f"q_{concept_id}_retry{attempt}",
            concept_id=concept_id,
            kind="short",
            prompt=f"Using the {analogy} picture — what happens now?",
            expected="decreases",
        ),
    )


def final_quiz(plan: LessonPlan) -> list[Question]:
    return [
        Question(
            id=f"quiz_{c.id}",
            concept_id=c.id,
            kind="mcq",
            prompt=f"Which statement about {c.name} is correct?",
            options=["It increases", "It decreases", "It stays the same"],
            expected="It decreases",
        )
        for c in plan.concepts
    ]


def build_report(session: SessionState) -> LessonReport:
    evals = session.evaluations
    correct = sum(1 for e in evals if e.correct)
    score = round(100.0 * correct / len(evals), 1) if evals else 0.0

    by_concept = {c.id: c.name for c in session.plan.concepts}
    weak_ids = {
        cid for cid, n in session.attempts.items() if n > 0
    }
    weak = [by_concept.get(cid, cid) for cid in sorted(weak_ids)]
    strong = [n for cid, n in by_concept.items() if cid not in weak_ids]

    return LessonReport(
        score=score,
        strong=strong,
        weak=weak,
        misconceptions=[e.misconception for e in evals if e.misconception],
        revise=weak[:2],
        next_topic=f"{session.plan.topic} — applications",
    )


def learning_path(topic: str) -> list[str]:
    return [
        f"{topic}: fundamentals",
        f"{topic}: core theory",
        f"{topic}: worked problems",
        f"{topic}: applications",
        f"{topic}: advanced topics",
    ]
