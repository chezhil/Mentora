"""Shared fixture data in Python form (used by the offline tests)."""

from __future__ import annotations

from shared.models import (
    LearnerProfile,
    LessonPlan,
    Question,
    SessionState,
    SourceChunk,
    StudentResponse,
)

PLAN_DICT = {
    "topic": "Electricity Basics",
    "language": "en",
    "total_minutes": 20,
    "concepts": [
        {"id": "c1", "name": "Current", "depth": "brief",
         "minutes": 4.0, "prerequisites": []},
        {"id": "c2", "name": "Voltage", "depth": "brief",
         "minutes": 5.0, "prerequisites": ["c1"]},
        {"id": "c3", "name": "Resistance", "depth": "standard",
         "minutes": 5.0, "prerequisites": ["c1"]},
        {"id": "c4", "name": "Ohm's Law", "depth": "standard",
         "minutes": 6.0, "prerequisites": ["c2", "c3"]},
    ],
}

segment_plan = LessonPlan.model_validate(PLAN_DICT)
reexplain_plan = LessonPlan.model_validate(PLAN_DICT)

segment_state = SessionState.model_validate({
    "session_id": "s1",
    "current_concept": 1,
    "profile": {
        "level": "beginner", "language": "en", "time_minutes": 20,
        "goal": "understand Ohm's law", "known_concepts": [],
        "weak_concepts": ["resistance"],
    },
    "plan": PLAN_DICT,
    "doc_id": "doc-abc123",
    "turns": [],
    "attempts": {},
    "evaluations": [],
})

segment_chunks = [
    SourceChunk(
        text="Ohm's law states current is proportional to voltage and "
             "inversely proportional to resistance.",
        page=41, section="Chapter 4", score=0.92,
    ),
    SourceChunk(
        text="Resistance is the opposition to current flow, measured in ohms.",
        page=39, section="Chapter 4", score=0.85,
    ),
    SourceChunk(
        text="If resistance increases at constant voltage, current decreases.",
        page=42, section="Chapter 4", score=0.9,
    ),
]

wrong_question = Question(
    id="q3", concept_id="c4", kind="short",
    prompt="What happens to current if resistance increases while voltage "
           "remains constant?",
    expected="Current decreases.",
)

wrong_answer = StudentResponse(question_id="q3", answer="Current increases.")

report_session = SessionState.model_validate({
    "session_id": "s1",
    "profile": {
        "level": "beginner", "language": "en", "time_minutes": 20,
        "goal": "understand Ohm's law", "known_concepts": [],
        "weak_concepts": ["resistance"],
    },
    "plan": PLAN_DICT,
    "doc_id": "doc-abc123",
    "turns": [
        {"role": "teacher", "content": "Voltage is the push.",
         "concept_id": "c2", "timestamp": "2026-09-02T10:00:00"},
        {"role": "teacher", "content": "If resistance increases at constant "
         "voltage, what happens to current?", "concept_id": "c4",
         "timestamp": "2026-09-02T10:08:00"},
        {"role": "student", "content": "Current increases.",
         "concept_id": "c4", "timestamp": "2026-09-02T10:09:00"},
    ],
    "current_concept": 3,
    "attempts": {"c4": 0},
    "evaluations": [
        {"correct": True, "misconception": None, "action": "continue",
         "feedback": "Good."},
        {"correct": False,
         "misconception": "believes current and resistance are directly "
         "proportional", "action": "reexplain",
         "feedback": "Not quite."},
    ],
})