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

  2. reexplain() takes the session state as a 4th argument. CONTRACT.txt
     originally specified three; Pair B built the four-argument version and it
     is the better one, so the contract was amended to match. wiring.py
     tolerates both shapes during integration.

  3. evaluate(question, response) cannot know how many times this concept has
     already been re-explained, so it can never legitimately return
     "simplify" (defined as "wrong twice, go simpler"). The orchestrator
     escalates reexplain -> simplify on the second attempt and records that
     it did so, so the adaptation panel can show it honestly.
"""

from __future__ import annotations

import os
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

try:
    import history
except Exception:          # history is Utkarsh's; never let it kill a lesson
    history = None

VISUAL_DIR = "out/visuals"
FACE_IMAGE = "assets/teacher.jpg"
DEFAULT_STUDENT = "default_student"


def _persist(call, *args) -> None:
    """Best-effort write to SQLite. A storage failure degrades to in-memory."""
    if history is None:
        return
    try:
        getattr(history, call)(*args)
    except Exception:
        pass


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
    student_id: str = DEFAULT_STUDENT


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
    turn = Turn(role=role, content=content, concept_id=concept_id,
                timestamp=_now())
    session.turns.append(turn)
    _persist("save_turn", session.session_id, turn)


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

def past_reports(student_id: str = DEFAULT_STUDENT) -> list[LessonReport]:
    """Everything this student has done before. Empty if they are new."""
    if history is None:
        return []
    try:
        return history.load_history(student_id)
    except Exception:
        return []


def _query_for(plan, concept) -> str:
    """Build the retrieval query for a concept.

    Retrieving on the bare concept name silently loses the most relevant
    material: a single noun carries too little signal to match a 150-word
    passage. Measured against fixtures/sample.pdf with MIN_SCORE 0.45 —

        "Resistance"                  0.359  dropped
        "Ohm's Law: Resistance"       0.662  kept
        "Current"                     0.450  dropped
        "Ohm's Law: Current"          0.603  kept

    "Resistance" scored below an unrelated question about the French
    Revolution (0.433). Prefixing the lesson topic restores the context the
    embedder needs.
    """
    name = concept.name
    if plan.topic.lower() in name.lower():
        return name
    return f"{plan.topic}: {name}"


def start_session(topic: str, profile: LearnerProfile,
                  file_path: str | None = None,
                  student_id: str = DEFAULT_STUDENT) -> SessionState:
    """Ingest the file if there is one, ask Pair B for a plan, open a session.

    `student_id` is additive to the contract signature — existing three-argument
    callers are unaffected. It is what makes a returning student get "last time
    you struggled with Ohm's Law" (Section 14 of the brief).
    """
    # Carry forward what earlier lessons revealed, so the plan can account for
    # it. Pair B reads profile.weak_concepts.
    previous = past_reports(student_id)
    if previous:
        carried = [w for r in previous for w in r.weak]
        profile = profile.model_copy(update={
            "weak_concepts": list(dict.fromkeys(profile.weak_concepts + carried)),
        })

    doc_id = wiring.ingest(file_path) if file_path else None

    plan = wiring.plan(topic, profile, doc_id)

    session = SessionState(
        session_id=uuid.uuid4().hex[:12],
        profile=profile,
        plan=plan,
        doc_id=doc_id,
    )
    _RUNTIME[session.session_id] = Runtime(student_id=student_id)

    source = f"from {file_path}" if file_path else "with no uploaded material"
    _log(session, "system",
         f"Session opened: {topic}, {profile.level}, {profile.language}, "
         f"{profile.time_minutes} min, {source}.")

    if previous:
        weak = ", ".join(profile.weak_concepts[:3]) or "nothing in particular"
        _log(session, "system",
             f"Returning student: {len(previous)} previous lesson(s). "
             f"Last time they struggled with {weak}.")
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
        chunks = wiring.retrieve(session.doc_id, _query_for(session.plan, concept),
                                 RETRIEVE_K)

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
        # Drop any re-explanation queued by an earlier attempt. Without this
        # the abandoned concept still gets taught, and answering it advances
        # current_concept a SECOND time — silently skipping a concept.
        rt.pending = None
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
            trim_state(session),
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
    _persist("save_report", session.session_id, report, rt.student_id)
    rt.finished = True
    _log(session, "system", f"Lesson finished. Score {report.score}.")
    return report


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Data access for the screens in screens/.
#
# These exist so a screen never has to reach into planner/, teacher/ or the
# Runtime side-table. Each screen calls one of these and renders the result.
# Signatures are fixed — screens are built against them.
# ---------------------------------------------------------------------------

def lesson_video(session: SessionState) -> str:
    """One MP4 of the whole lesson, or "" if there is nothing to stitch.

    Segments were being composed individually and then thrown away — Pair C's
    build_lesson_video existed and nothing called it, so there was no single
    video to hand over, which is the actual deliverable of the brief.

    Runtime.media preserves insertion order, so segments come out in the order
    they were taught, including re-explanations.
    """
    paths = [
        m.video_mp4 for m in runtime(session).media.values()
        if m.video_mp4 and os.path.exists(m.video_mp4)
    ]
    if not paths:
        return ""
    try:
        return wiring.build_lesson_video(paths, session.plan.topic)
    except Exception:
        return ""          # a failed stitch must not break the report


def skip(session: SessionState, question_id: str) -> None:
    """Move past a question the student does not want to answer.

    Not the same as getting it wrong: no Evaluation is recorded, so a skipped
    question does not count against the score or trigger a re-explanation. It
    does advance the lesson, and it clears any queued re-explanation — a
    student who skips is telling us to move on, not to try again.
    """
    rt = runtime(session)
    question = rt.questions.get(question_id)
    concept_id = question.concept_id if question else None

    _log(session, "student", "(skipped this question)", concept_id)
    _log(session, "system", "Student skipped the question; moving on.",
         concept_id)

    rt.pending = None
    if not is_finished(session):
        session.current_concept += 1

    rt.panel = PanelState(
        answered=True,
        correct=None,
        action_taken="skipped",
        concept_name=rt.panel.concept_name,
        retrieved=rt.panel.retrieved,
        grounded_pages=rt.panel.grounded_pages,
    )


def note(session: SessionState, text: str) -> None:
    """Record a system event (a language switch, say) on the transcript."""
    _log(session, "system", text)


def quiz_questions(session: SessionState) -> list[Question]:
    """The final quiz. Empty until finish() has run."""
    return list(runtime(session).quiz)


def submit_quiz(session: SessionState,
                answers: dict[str, str]) -> LessonReport:
    """Mark the final quiz and fold it into the report.

    `answers` is {question_id: answer}. Each is marked by Pair B's evaluate,
    recorded on the session like any other answer, and the report is rebuilt so
    the score reflects the quiz rather than only mid-lesson answers.
    """
    rt = runtime(session)
    for question_id, answer in answers.items():
        question = rt.questions.get(question_id)
        if question is None or not str(answer).strip():
            continue
        response = StudentResponse(question_id=question_id, answer=answer)
        evaluation = wiring.evaluate(question, response)
        _log(session, "student", answer, question.concept_id)
        _log(session, "teacher", evaluation.feedback, question.concept_id)
        session.evaluations.append(evaluation)

    report = wiring.build_report(trim_state(session))
    _persist("save_report", session.session_id, report, rt.student_id)
    return report


def learning_path_for(topic: str) -> list[str]:
    """Ordered next topics. Each entry is "Step name - why it comes here"."""
    try:
        return list(wiring.learning_path(topic))
    except Exception:
        return []


def ask(session: SessionState, question: str) -> str:
    """A student's own question, mid-lesson.

    Retrieves against their material first so the reply can be grounded, then
    hands both to Pair B. Never raises: a failed follow-up must not end the
    lesson.
    """
    chunks = []
    if session.doc_id and question.strip():
        try:
            chunks = wiring.retrieve(session.doc_id, question, RETRIEVE_K)
        except Exception:
            chunks = []

    _log(session, "student", question)
    try:
        reply = wiring.answer_followup(question, trim_state(session), chunks)
    except Exception as exc:
        reply = f"I could not answer that just now ({type(exc).__name__}). Let's continue."
    _log(session, "teacher", reply)
    return reply


def _remember_question(session: SessionState,
                       segment: TeachingSegment) -> None:
    """answer() is only given a question_id, so we keep the questions."""
    if segment.question is not None:
        runtime(session).questions[segment.question.id] = segment.question
