"""The conductor. Chezhil owns this file.

The four functions CONTRACT.txt promises, and nothing else. No teaching
logic, no drawing, no audio — this file only decides who gets called, in what
order, and what happens to the result.

If you ever find yourself writing "if the student is a beginner, use simpler
words" in here, that is Pair B's job leaking into our file.

TWO GAPS IN CONTRACT.txt, HANDLED HERE (Chezhil to raise with the team):

  1. step() returns a TeachingSegment, which has no field for the rendered
     PNG / WAV / MP4. The app needs those paths. Rather than edit
     shared/models.py unilaterally, media lives in a side table keyed by
     session id — see SegmentMedia and media_for().

  2. evaluate(question, response) cannot know how many times this concept has
     already been re-explained, so it can never legitimately return
     "simplify" (defined as "wrong twice, go simpler"). The orchestrator
     escalates reexplain -> simplify on the second attempt and records that
     it did so, so the adaptation panel can show it honestly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

import wiring
from shared.config import (
    CONTEXT_FULL_TURNS,
    CONTEXT_SUMMARY_MAX_CHARS,
    MAX_AVATAR_SECONDS,
    MAX_REEXPLAIN_ATTEMPTS,
    RETRIEVE_K,
)
from shared.models import (
    Evaluation, LearnerProfile, LessonReport, Question, SessionState,
    StudentResponse, TeachingSegment, Turn,
)

VISUAL_DIR = "out/visuals"
FACE_IMAGE = "assets/teacher.jpg"


class SegmentMedia(BaseModel):
    """Rendered output for one segment. Not in CONTRACT.txt — see gap 1."""
    visual_png: str | None = None
    audio_wav: str | None = None
    video_mp4: str | None = None
    notes: list[str] = []


class PanelState(BaseModel):
    """Exactly what the adaptation panel renders. Not in CONTRACT.txt.

    Every field is either copied off an Evaluation or is a decision this
    orchestrator made. Nothing here is invented for display.
    """
    answered: bool = False
    correct: bool | None = None
    misconception: str | None = None
    action_from_pair_b: str | None = None
    action_taken: str | None = None
    escalated: bool = False
    attempt: int = 0
    analogy: str | None = None
    difficulty: str | None = None
    concept_name: str | None = None
    grounded_pages: list[int] = []
    retrieved: int = 0


class Runtime(BaseModel):
    """Per-session state the contract has no home for."""
    questions: dict[str, Question] = {}
    media: dict[str, SegmentMedia] = {}
    pending: TeachingSegment | None = None
    panel: PanelState = PanelState()
    quiz: list[Question] = []
    finished: bool = False


_RUNTIME: dict[str, Runtime] = {}


def runtime(session: SessionState) -> Runtime:
    return _RUNTIME.setdefault(session.session_id, Runtime())


def media_for(session: SessionState, segment: TeachingSegment) -> SegmentMedia:
    return runtime(session).media.get(_media_key(segment), SegmentMedia())


def _media_key(segment: TeachingSegment) -> str:
    q = segment.question.id if segment.question else "noq"
    return f"{segment.concept_id}:{q}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(session: SessionState, role: str, content: str,
         concept_id: str | None = None) -> None:
    session.turns.append(
        Turn(role=role, content=content, concept_id=concept_id,
             timestamp=_now())
    )


# ---------------------------------------------------------------------------
# Context budget — Chezhil's dial. Do not send the whole transcript to Gemini.
# ---------------------------------------------------------------------------

def trim_state(session: SessionState) -> SessionState:
    """A copy of the session with old turns collapsed into one summary turn.

    A 60-minute lesson generates far more history than the rate limit allows.
    Pair B gets the last CONTEXT_FULL_TURNS in full plus a short summary of
    everything before that.
    """
    if len(session.turns) <= CONTEXT_FULL_TURNS:
        return session

    old = session.turns[:-CONTEXT_FULL_TURNS]
    recent = session.turns[-CONTEXT_FULL_TURNS:]

    covered = sorted({t.concept_id for t in old if t.concept_id})
    summary = (
        f"Earlier in this session: {len(old)} turns covering "
        f"{', '.join(covered) if covered else 'setup'}. "
        f"Wrong answers so far: "
        f"{sum(1 for e in session.evaluations if not e.correct)}."
    )[:CONTEXT_SUMMARY_MAX_CHARS]

    trimmed = session.model_copy(deep=True)
    trimmed.turns = [
        Turn(role="system", content=summary, timestamp=_now())
    ] + recent
    return trimmed


# ---------------------------------------------------------------------------
# Media — every call to Pair C is wrapped. A media failure degrades the
# lesson to text; it never ends it.
# ---------------------------------------------------------------------------

def _build_media(session: SessionState,
                 segment: TeachingSegment) -> SegmentMedia:
    out = SegmentMedia()

    try:
        out.visual_png = wiring.render(segment.visual, VISUAL_DIR)
    except Exception as exc:
        out.notes.append(f"visual failed: {exc}")

    try:
        out.audio_wav = wiring.speak(segment.script, session.profile.language)
    except Exception as exc:
        out.notes.append(f"audio failed: {exc}")

    if out.audio_wav:
        seconds = wiring.audio_seconds(out.audio_wav)
        if seconds > MAX_AVATAR_SECONDS:
            # Do not even attempt it — Pair C refuses, and rightly. A segment
            # this long is a planning bug, so say so loudly.
            out.notes.append(
                f"script is {seconds:.0f}s, over the {MAX_AVATAR_SECONDS}s "
                f"avatar cap — teaching as audio + visual only"
            )
        else:
            try:
                mp4 = wiring.render_avatar(out.audio_wav, FACE_IMAGE)
                if mp4:
                    out.video_mp4 = wiring.compose(
                        mp4, out.visual_png or "", out.audio_wav
                    )
            except Exception as exc:
                out.notes.append(f"avatar failed: {exc}")

    runtime(session).media[_media_key(segment)] = out
    return out


# ---------------------------------------------------------------------------
# THE FOUR CONTRACT FUNCTIONS
# ---------------------------------------------------------------------------

def start_session(topic: str, profile: LearnerProfile,
                  file_path: str | None = None) -> SessionState:
    """Ingest the file if there is one, ask Pair B for a plan, open a session."""
    doc_id = wiring.ingest(file_path) if file_path else None

    plan = wiring.plan(topic, profile, doc_id)

    session = SessionState(
        session_id=uuid.uuid4().hex[:12],
        profile=profile,
        plan=plan,
        doc_id=doc_id,
    )
    _RUNTIME[session.session_id] = Runtime()

    source = f"from {file_path}" if file_path else "with no uploaded material"
    _log(session, "system",
         f"Session opened: {topic}, {profile.level}, {profile.language}, "
         f"{profile.time_minutes} min, {source}.")
    return session


def is_finished(session: SessionState) -> bool:
    return session.current_concept >= len(session.plan.concepts)


def step(session: SessionState) -> TeachingSegment:
    """Retrieve, ask Pair B what to teach, send it to Pair C, hand it back."""
    rt = runtime(session)

    # A re-explanation queued by answer() takes priority over new material.
    if rt.pending is not None:
        segment, rt.pending = rt.pending, None
        _build_media(session, segment)
        _remember_question(session, segment)
        _log(session, "teacher", segment.script, segment.concept_id)
        return segment

    if is_finished(session):
        raise RuntimeError(
            "step() called after the last concept. Check is_finished() first."
        )

    concept = session.plan.concepts[session.current_concept]

    chunks = []
    if session.doc_id:
        chunks = wiring.retrieve(session.doc_id, concept.name, RETRIEVE_K)

    segment = wiring.next_segment(session.plan, trim_state(session), chunks)

    _build_media(session, segment)
    _remember_question(session, segment)
    _log(session, "teacher", segment.script, segment.concept_id)

    rt.panel.concept_name = concept.name
    rt.panel.retrieved = len(chunks)
    rt.panel.grounded_pages = sorted(
        {c.page for c in segment.citations if c.page is not None}
    )
    return segment


def answer(session: SessionState,
           response: StudentResponse) -> Evaluation:
    """Judge the answer, record it, and queue a re-explanation if needed."""
    rt = runtime(session)

    question = rt.questions.get(response.question_id)
    if question is None:
        raise KeyError(
            f"unknown question id {response.question_id!r} — "
            f"step() must run before answer()"
        )

    evaluation = wiring.evaluate(question, response)

    _log(session, "student", response.answer, question.concept_id)
    _log(session, "teacher", evaluation.feedback, question.concept_id)
    session.evaluations.append(evaluation)

    concept_id = question.concept_id
    concept = next(
        (c for c in session.plan.concepts if c.id == concept_id), None
    )

    panel = PanelState(
        answered=True,
        correct=evaluation.correct,
        misconception=evaluation.misconception,
        action_from_pair_b=evaluation.action,
        action_taken=evaluation.action,
        attempt=session.attempts.get(concept_id, 0),
        concept_name=concept.name if concept else concept_id,
        retrieved=rt.panel.retrieved,
        grounded_pages=rt.panel.grounded_pages,
    )

    if evaluation.correct:
        session.current_concept += 1
        panel.difficulty = "raised" if evaluation.action == "harden" else "unchanged"
        rt.panel = panel
        return evaluation

    # Wrong. Count the attempt, then decide what actually happens.
    attempt = session.attempts.get(concept_id, 0) + 1
    session.attempts[concept_id] = attempt
    panel.attempt = attempt

    if attempt >= MAX_REEXPLAIN_ATTEMPTS:
        # Stop looping on one concept. A lesson that never advances is worse
        # than a lesson with a gap in it.
        session.current_concept += 1
        panel.action_taken = "moved on"
        panel.difficulty = "lowered"
        _log(session, "system",
             f"{concept_id}: {attempt} attempts, moving on to keep the "
             f"lesson inside {session.profile.time_minutes} minutes.",
             concept_id)
        rt.panel = panel
        return evaluation

    # Gap 2: Pair B cannot see the attempt count, so escalate here.
    action = evaluation.action
    if action == "reexplain" and attempt >= 2:
        action = "simplify"
        panel.escalated = True
    panel.action_taken = action
    panel.difficulty = "lowered" if action in ("reexplain", "simplify") else "unchanged"

    if action in ("reexplain", "simplify", "example"):
        segment = wiring.reexplain(
            concept_id,
            evaluation.misconception or "an unnamed misunderstanding",
            attempt,
        )
        rt.pending = segment
        panel.analogy = segment.visual.caption or segment.visual.payload

    rt.panel = panel
    return evaluation


def finish(session: SessionState) -> LessonReport:
    """Final quiz and report card."""
    rt = runtime(session)
    rt.quiz = wiring.final_quiz(session.plan)
    for q in rt.quiz:
        rt.questions[q.id] = q

    report = wiring.build_report(trim_state(session))
    rt.finished = True
    _log(session, "system", f"Lesson finished. Score {report.score}.")
    return report


# ---------------------------------------------------------------------------

def _remember_question(session: SessionState,
                       segment: TeachingSegment) -> None:
    """answer() is only given a question_id, so we keep the questions."""
    if segment.question is not None:
        runtime(session).questions[segment.question.id] = segment.question
