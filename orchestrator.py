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

import hashlib
import json
import os
from pathlib import Path
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

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

# Optional local avatar (Pair C free tier). If not installed, falls back to
# the still-image visual pair_b rendered.
try:
    from local_avatar import render_avatar
except ImportError:
    render_avatar = None  # Pair C not ready yet; fallback handled in step()

try:
    import history
except ImportError:
    history = None  # Pair D not ready yet; past_reports() returns empty list

DEFAULT_STUDENT = "student"
FACE_IMAGE = "assets/teacher.jpg"
VISUAL_DIR = "out/visuals"


class SegmentMedia(BaseModel):
    """Rendered output for one segment. Not in CONTRACT.txt — see gap 1."""
    visual_png: str | None = None
    audio_wav: str | None = None
    video_mp4: str | None = None
    notes: list[str] = Field(default_factory=list)


class PanelState(BaseModel):
    """Exactly what the adaptation panel renders. Not in CONTRACT.txt."""
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
    grounded_pages: list[int] = Field(default_factory=list)
    retrieved: int = 0


class Runtime(BaseModel):
    """Per-session state the contract has no home for."""
    questions: dict[str, Question] = Field(default_factory=dict)
    media: dict[str, SegmentMedia] = Field(default_factory=dict)
    pending: TeachingSegment | None = None
    panel: PanelState = Field(default_factory=PanelState)
    quiz: list[Question] = Field(default_factory=list)
    finished: bool = False
    student_id: str = DEFAULT_STUDENT


_RUNTIME: dict[str, Runtime] = {}
_GLOBAL_QUESTIONS: dict[str, Question] = {}
_QUESTION_CACHE_DIR = Path(".cache/questions")


def _cache_question(session_id: str, question: Question) -> None:
    try:
        _QUESTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _QUESTION_CACHE_DIR / f"{session_id}.json"
        existing = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        existing[question.id] = question.model_dump()
        path.write_text(json.dumps(existing), encoding="utf-8")
    except Exception:
        pass


def _load_cached_question(session_id: str, question_id: str) -> Question | None:
    try:
        path = _QUESTION_CACHE_DIR / f"{session_id}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if question_id in data:
                return Question.model_validate(data[question_id])
    except Exception:
        pass
    return None


def remember_question(session: SessionState, question: Question | None) -> None:
    """Store question across all runtime, global, and disk registries."""
    if question is None:
        return
    rt = runtime(session)
    rt.questions[question.id] = question
    _GLOBAL_QUESTIONS[question.id] = question
    _cache_question(session.session_id, question)


def runtime(session: SessionState) -> Runtime:
    return _RUNTIME.setdefault(session.session_id, Runtime())


def media_for(session: SessionState, segment: TeachingSegment) -> SegmentMedia:
    return runtime(session).media.get(_media_key(segment, session.profile.language), SegmentMedia())


def _media_key(segment: TeachingSegment, lang: str = "") -> str:
    q = segment.question.id if segment.question else "noq"
    h = hashlib.sha1(segment.script.encode("utf-8")).hexdigest()[:8]
    return f"{segment.concept_id}:{q}:{lang}:{h}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _persist(call, *args) -> None:
    """Best-effort write to SQLite. A storage failure degrades to in-memory."""
    if history is None:
        return
    try:
        getattr(history, call)(*args)
    except Exception:
        pass


def _log(session: SessionState, role: str, content: str,
         concept_id: str | None = None) -> None:
    turn = Turn(role=role, content=content, concept_id=concept_id,
                timestamp=_now())
    session.turns.append(turn)
    _persist("save_turn", session.session_id, turn)


def note(session: SessionState, text: str) -> None:
    """Record an operational event or student action into the transcript."""
    _log(session, "system", text)


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
            # Do not even attempt an avatar — Pair C refuses, and rightly. A
            # segment this long is a planning bug, so say so loudly.
            out.notes.append(
                f"script is {seconds:.0f}s, over the {MAX_AVATAR_SECONDS}s "
                f"avatar cap — teaching as audio + visual only"
            )
        elif _board_video_enabled():
            # Preferred path: the animated board video (avatar-prototype's
            # restyled renderer), timed to the narration we already have.
            # Falls back to the legacy avatar-compose path below on any
            # failure, so the product behaves exactly as before offline.
            try:
                import board_media
                board = board_media.render_board_video(
                    script=segment.script,
                    kind=segment.visual.kind if segment.visual else "none",
                    payload=segment.visual.payload if segment.visual else "",
                    caption=segment.visual.caption if segment.visual else "",
                    out_dir=os.path.join(VISUAL_DIR, "board"),
                    audio_wav=out.audio_wav,
                    max_seconds=MAX_AVATAR_SECONDS,
                )
                if board:
                    out.video_mp4 = board
                    out.notes.append("board video (animated visual)")
            except Exception as exc:
                out.notes.append(f"board video failed: {exc}")
        if seconds <= MAX_AVATAR_SECONDS and not out.video_mp4:
            # Legacy fallback: Wav2Lip-style avatar composed over the still.
            try:
                mp4 = wiring.render_avatar(out.audio_wav, FACE_IMAGE)
                if mp4:
                    out.video_mp4 = wiring.compose(
                        mp4, out.visual_png or "", out.audio_wav
                    )
            except Exception as exc:
                out.notes.append(f"avatar failed: {exc}")

    runtime(session).media[_media_key(segment, session.profile.language)] = out
    return out


def _board_video_enabled() -> bool:
    """Off switch: set MENTORA_BOARD_VIDEO=0 to force the legacy avatar path."""
    return os.environ.get("MENTORA_BOARD_VIDEO", "1") != "0"


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


def _concept_name(session: SessionState, concept_id: str) -> str | None:
    """Human-readable name for a concept id, for the progress dashboard."""
    for c in session.plan.concepts:
        if c.id == concept_id:
            return c.name
    return None


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
    _persist("record_study_start", session.session_id, student_id,
             topic, profile.time_minutes)

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
           response: StudentResponse,
           question: Question | None = None) -> Evaluation:
    """Judge the answer, record it, and queue a re-explanation if needed."""
    rt = runtime(session)

    # 1. Directly supplied question takes priority
    if question is not None:
        remember_question(session, question)
    else:
        # 2. Check session runtime questions
        question = rt.questions.get(response.question_id)
        # 3. Check global registry
        if question is None:
            question = _GLOBAL_QUESTIONS.get(response.question_id)
        # 4. Check disk cache
        if question is None:
            question = _load_cached_question(session.session_id, response.question_id)
        # 5. Check if any known question matches the concept
        if question is None:
            for q in list(rt.questions.values()) + list(_GLOBAL_QUESTIONS.values()):
                if response.question_id.startswith(f"q_{q.concept_id}") or q.id == response.question_id:
                    question = q
                    break
        # 6. Safe synthesized fallback if state was wiped by restart
        if question is None:
            concept_id = None
            if "_" in response.question_id:
                parts = response.question_id.split("_")
                if len(parts) >= 2 and parts[1].startswith("c"):
                    concept_id = parts[1]
            if not concept_id and session.current_concept < len(session.plan.concepts):
                concept_id = session.plan.concepts[session.current_concept].id
            concept = next((c for c in session.plan.concepts if c.id == concept_id), None)
            
            question = Question(
                id=response.question_id,
                concept_id=concept_id or (concept.id if concept else "c1"),
                kind="short",
                prompt=f"Assess understanding of {concept.name if concept else 'the concept'}",
                expected=f"Accurate understanding of {concept.name}" if concept else "Correct conceptual understanding"
            )
            remember_question(session, question)

    evaluation = wiring.evaluate(question, response)

    _log(session, "student", response.answer, question.concept_id)
    _log(session, "teacher", evaluation.feedback, question.concept_id)
    session.evaluations.append(evaluation)
    _persist("record_answer", session.session_id, rt.student_id,
             question.concept_id, question.kind, evaluation.correct,
             _concept_name(session, question.concept_id))
    if not evaluation.correct:
        # A miss becomes a flashcard rated "again": due now, relearning
        # state — the same place a self-rated miss lands.
        record_flashcard(rt.student_id, _question_card(question), "again")

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
    _persist("record_study_end", session.session_id, report.score)
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
    """The final quiz. If not yet generated, build it from the plan."""
    rt = runtime(session)
    if not rt.quiz and session.plan:
        try:
            rt.quiz = wiring.final_quiz(session.plan)
            for q in rt.quiz:
                remember_question(session, q)
        except Exception:
            pass
    return list(rt.quiz)


def submit_quiz(session: SessionState,
                answers: dict[str, str]) -> LessonReport:
    """Mark the final quiz and fold it into the report."""
    rt = runtime(session)
    if not rt.quiz:
        quiz_questions(session)

    for question_id, ans in answers.items():
        if not str(ans).strip():
            continue
        question = rt.questions.get(question_id) or _GLOBAL_QUESTIONS.get(question_id)
        if question is None:
            question = _load_cached_question(session.session_id, question_id)
        if question is None:
            question = next((q for q in rt.quiz if q.id == question_id), None)
        if question is None:
            continue
        
        response = StudentResponse(question_id=question_id, answer=ans)
        evaluation = wiring.evaluate(question, response)
        _log(session, "student", ans, question.concept_id)
        _log(session, "teacher", evaluation.feedback, question.concept_id)
        session.evaluations.append(evaluation)
        _persist("record_answer", session.session_id, rt.student_id,
                 question.concept_id, question.kind, evaluation.correct,
                 _concept_name(session, question.concept_id))
        if not evaluation.correct:
            record_flashcard(rt.student_id, _question_card(question, source="quiz"),
                             "again")

    report = wiring.build_report(trim_state(session))
    _persist("save_report", session.session_id, report, rt.student_id)
    return report


# ---------------------------------------------------------------------------
# Flashcards & progress dashboard — data access for screens/flashcards.py and
# screens/path.py. Everything is best-effort: a missing history store degrades
# to an empty deck / zeroed stats rather than an error.
# ---------------------------------------------------------------------------

LEVEL_XP_BASE = 100   # XP needed for level 1; each level costs this more


def level_from_xp(xp: int) -> tuple[int, int, int]:
    """(level, xp_into_level, xp_needed_for_next) from cumulative XP."""
    level, remaining = 1, xp
    while True:
        cost = LEVEL_XP_BASE * level
        if remaining < cost:
            return level, remaining, cost
        remaining -= cost
        level += 1


def _question_card(question, source: str = "question") -> dict:
    """The card shape for one question — front/back/key, shared by the deck
    builder and the miss-recorder so they can never drift apart. `source` is
    "question" for a lesson question, "quiz" for a final-quiz miss."""
    back = question.expected
    if question.options:
        letters = "ABCDEFGH"
        opts = "\n".join(
            f"{letters[i]}. {o}" for i, o in enumerate(question.options)
        )
        back = f"{back}\n\n{opts}"
    return {"card_key": f"question:{question.id}",
            "front": question.prompt, "back": back, "source": source}


def flashcard_deck(session: SessionState) -> list[dict]:
    """Build a review deck from the current lesson.

    Two kinds of card:
      - question cards: front is the question, back is the expected answer
        (plus the options, when it was an MCQ)
      - concept cards: front is the concept name, back is the teacher's
        explanation, taken from the first teacher turn about that concept
    """
    deck: dict[str, dict] = {}

    # Teacher explanations, keyed by concept.
    script_by_concept: dict[str, str] = {}
    for turn in session.turns:
        if turn.role == "teacher" and turn.concept_id:
            script_by_concept.setdefault(turn.concept_id, turn.content)

    for concept in session.plan.concepts:
        key = f"concept:{concept.id}"
        back = script_by_concept.get(concept.id) or (
            f"Core concept of {session.plan.topic}: {concept.name}."
        )
        deck[key] = {
            "card_key": key, "front": concept.name, "back": back,
            "source": "concept",
        }

    # Questions asked during the lesson and the final quiz.
    rt = runtime(session)
    quiz_ids = {q.id for q in rt.quiz}
    for q in list(rt.questions.values()) + list(rt.quiz):
        if not q.prompt or not q.expected:
            continue
        source = "quiz" if q.id in quiz_ids else "question"
        card = _question_card(q, source=source)
        deck[card["card_key"]] = card
    return list(deck.values())


def due_reviews(student_id: str) -> list[dict]:
    """Cards from earlier sessions that are due for spaced repetition."""
    if history is None:
        return []
    try:
        return history.due_flashcards(student_id)
    except Exception:
        return []


def browse_flashcards(student_id: str) -> list[dict]:
    """Every persisted card with its SRS stats — the browse view's source."""
    if history is None:
        return []
    try:
        return history.list_flashcards(student_id)
    except Exception:
        return []


def edit_flashcard(student_id: str, card_key: str, front: str,
                   back: str) -> bool:
    """Rewrite a card's front/back in place; scheduling state untouched."""
    if history is None:
        return False
    try:
        return history.update_flashcard(student_id, card_key, front, back)
    except Exception:
        return False


def delete_flashcard(student_id: str, card_key: str) -> bool:
    """Remove a card and its whole review history."""
    if history is None:
        return False
    try:
        return history.delete_flashcard(student_id, card_key)
    except Exception:
        return False


def flashcard_signature(student_id: str) -> tuple:
    """Fingerprint of the student's cards; changes on any write or delete."""
    if history is None:
        return ()
    try:
        return history.flashcard_signature(student_id)
    except Exception:
        return ()


def record_flashcard(student_id: str, card: dict, ease: str) -> float | None:
    """Persist one self-rated flashcard review.

    Returns the SM-2 interval the card now sits on (0 = due again now), so
    the screen can say "next review in N days" right where it happened.
    """
    if history is None:
        return None
    try:
        return history.save_flashcard_review(
            student_id, card["card_key"], card["front"], card["back"],
            card.get("source", "lesson"), ease,
        )
    except Exception:
        return None


def goals_today(student_id: str) -> dict:
    """Daily review goal and how many cards were rated today."""
    if history is None:
        return {"goal": 0, "done": 0}
    try:
        s = history.review_summary(student_id)
        return {"goal": history.get_daily_goal(student_id),
                "done": s["today"]}
    except Exception:
        return {"goal": 0, "done": 0}


def goal_memory(student_id: str) -> dict:
    """How many of the last 7 days met the daily review goal.

    Returns {"met": int|None, "days": 7, "daily": [int x 7]};
    met is None only when the student has no goal set.
    """
    if history is None:
        return {"met": None, "days": 7, "daily": [0]*7}
    try:
        goal = int(history.get_daily_goal(student_id))
        s = history.review_summary(student_id)
        daily = s["daily"]
        if goal <= 0:
            return {"met": None, "days": 7, "daily": daily}
        return {"met": sum(1 for c in daily if c >= goal), "days": 7,
                "daily": daily}
    except Exception:
        return {"met": None, "days": 7, "daily": [0]*7}


def set_daily_goal(student_id: str, goal: int) -> bool:
    """Persist the daily review target."""
    if history is None:
        return False
    try:
        history.set_daily_goal(student_id, goal)
        return True
    except Exception:
        return False


def badges_for(student_id: str) -> dict:
    """Earned/locked badges from existing aggregates — see history/badges.py."""
    import history.badges as hb
    stats = {"lessons": 0, "streak": 0, "reviews": 0,
             "recovery": False, "perfect": False}
    if history is not None:
        try:
            stats["lessons"] = len(past_reports(student_id))
            stats["streak"] = history.study_streak(student_id)
            # Total rating events ever — monotonic (the review log is
            # append-only), so an earned milestone can't be un-earned by a
            # later 'again' that resets a card's repetition counter.
            stats["reviews"] = history.review_summary(student_id)["all_time"]
            stats["recovery"] = history.had_recovery(student_id)
            stats["perfect"] = history.has_perfect_score(student_id)
        except Exception:
            pass
    return hb.evaluate(stats)


def stats_dashboard(student_id: str) -> dict:
    """Everything screens/path.py renders, in one call."""
    reports = past_reports(student_id)
    scores = [r.score for r in reports]
    stats = {
        "lessons": len(reports),
        "avg_score": sum(scores) / len(scores) if scores else 0.0,
        "best_score": max(scores) if scores else 0.0,
        "reports": reports,
    }
    if history is not None:
        try:
            stats.update({
                "streak": history.study_streak(student_id),
                "xp": history.xp_earned(student_id),
                "mastery": history.concept_mastery(student_id),
                "activity": history.daily_activity(student_id, days=28),
                "reviews": history.review_stats(student_id),
                "score_history": history.score_history(student_id),
            })
        except Exception:
            stats.update({"streak": 0, "xp": 0, "mastery": [],
                          "activity": [], "reviews": {},
                          "score_history": []})
    else:
        stats.update({"streak": 0, "xp": 0, "mastery": [],
                      "activity": [], "reviews": {},
                      "score_history": []})
    level, into, need = level_from_xp(stats["xp"])
    stats["level"] = level
    stats["xp_into_level"] = into
    stats["xp_for_next"] = need
    return stats


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


def switch_language(session: SessionState, new_lang: str,
                    current_segment: TeachingSegment | None = None) -> TeachingSegment | None:
    """Switch language immediately, translating/re-rendering the current segment."""
    session.profile.language = new_lang
    session.plan.language = new_lang
    _log(session, "system", f"Teaching language switched to {new_lang}.")
    
    if current_segment is None:
        return None

    import llm
    prompt = f"""
You are a human teacher. Translate and adapt the following teaching segment into the language '{new_lang}'.
Keep the exact pedagogical structure, meaning, tone, and visual specification.
Ensure the spoken script sounds natural and conversational in {new_lang}.
Translate the question prompt and its options into {new_lang} as well.
Return ONLY a valid JSON object matching this structure:
{{
  "concept_id": "{current_segment.concept_id}",
  "script": "spoken script in {new_lang}",
  "visual": {json.dumps(current_segment.visual.model_dump())},
  "question": {json.dumps(current_segment.question.model_dump()) if current_segment.question else "null"},
  "citations": {json.dumps([c.model_dump() for c in current_segment.citations])}
}}
"""
    try:
        data = llm.generate_json(prompt)
        if data.get("question"):
            data["question"]["id"] = f"q_{current_segment.concept_id}_{new_lang}_{uuid.uuid4().hex[:4]}"
            data["question"]["concept_id"] = current_segment.concept_id
        new_seg = TeachingSegment.model_validate(data)
        _build_media(session, new_seg)
        _remember_question(session, new_seg)
        return new_seg
    except Exception as exc:
        try:
            _build_media(session, current_segment)
        except Exception:
            pass
        return current_segment


def regenerate_current(session: SessionState, current_segment: TeachingSegment) -> TeachingSegment:
    """Regenerate the current segment with an alternative explanation and analogy."""
    concept_id = current_segment.concept_id
    concept = next((c for c in session.plan.concepts if c.id == concept_id), None)
    
    attempt = session.attempts.get(concept_id, 0) + 1
    session.attempts[concept_id] = attempt
    
    new_seg = wiring.reexplain(
        concept_id,
        "Student requested an alternative, clearer perspective with a fresh analogy",
        attempt,
        trim_state(session),
    )
    _build_media(session, new_seg)
    _remember_question(session, new_seg)
    _log(session, "teacher", f"(Alternative explanation): {new_seg.script}", concept_id)
    return new_seg
