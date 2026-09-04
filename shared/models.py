"""The shared data shapes. Copied exactly from CONTRACT.txt.

Nobody edits this file alone. Propose changes to Chezhil.
"""

from pydantic import BaseModel
from typing import Literal
from datetime import datetime, timezone


class LearnerProfile(BaseModel):
    """Who the student is and what they asked for."""
    level: Literal["beginner", "intermediate", "advanced"]
    language: str                      # "en", "hi", "ta", "kn", "hinglish"
    time_minutes: int                  # 5, 20, 60
    goal: str | None = None
    known_concepts: list[str] = []
    weak_concepts: list[str] = []
    # How the teacher sounds and who the student sees. Both were stored in the
    # preferences table and read by nothing: persona never reached a prompt and
    # the avatar could only be changed with an environment variable, so picking
    # either in the UI did nothing at all.
    persona: str = "socratic"
    avatar: Literal["f", "m"] = "f"


class SourceChunk(BaseModel):
    """A piece of the uploaded document, with where it came from."""
    text: str
    page: int | None = None
    section: str | None = None
    score: float                       # 0.0 to 1.0, higher = more relevant


class Concept(BaseModel):
    """One thing to be taught."""
    id: str                            # "c1", "c2", ...
    name: str
    depth: Literal["brief", "standard", "deep"]
    minutes: float
    prerequisites: list[str] = []      # ids of other concepts


class LessonPlan(BaseModel):
    """The full plan for one teaching session."""
    topic: str
    language: str
    total_minutes: int
    concepts: list[Concept]


class VisualSpec(BaseModel):
    """Instructions for what to draw on screen."""
    kind: Literal["equation", "graph", "diagram", "timeline",
                  "code", "concept_map", "none"]
    payload: str                       # LaTeX / python / mermaid / code text
    caption: str | None = None


class Question(BaseModel):
    """A question asked during or after the lesson."""
    id: str                            # "q1", "q2", ...
    concept_id: str
    kind: Literal["mcq", "mmcq", "msq", "short", "explain", "problem"]
    prompt: str
    options: list[str] | None = None   # for mcq and mmcq
    expected: str                      # the correct answer


class TeachingSegment(BaseModel):
    """One chunk of teaching: what to say, what to show, what to ask."""
    concept_id: str
    script: str                        # what the avatar says out loud
    visual: VisualSpec
    question: Question | None = None
    citations: list[SourceChunk] = []


class StudentResponse(BaseModel):
    """What the student typed back."""
    question_id: str
    answer: str


class Evaluation(BaseModel):
    """The teacher's judgement of a student answer."""
    correct: bool
    misconception: str | None = None   # NAME the mistake, not just "wrong"
    action: Literal["continue", "reexplain", "simplify",
                    "harden", "example"]
    feedback: str                      # what to say to the student


class Turn(BaseModel):
    """One entry in the conversation history."""
    role: Literal["teacher", "student", "system"]
    content: str
    concept_id: str | None = None
    timestamp: datetime


class LessonReport(BaseModel):
    """The final report card."""
    score: float                       # 0 to 100
    strong: list[str]
    weak: list[str]
    misconceptions: list[str]
    revise: list[str]
    next_topic: str


class SessionState(BaseModel):
    """Everything about one student's current session."""
    session_id: str
    profile: LearnerProfile
    plan: LessonPlan
    doc_id: str | None = None
    turns: list[Turn] = []
    current_concept: int = 0
    attempts: dict[str, int] = {}      # concept_id -> times re-explained
    evaluations: list[Evaluation] = []
    started_at: datetime | None = None  # set when the lesson begins, for elapsed timer
