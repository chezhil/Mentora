"""The teaching loop, for the brutalist web UI.

Before this, the web UI could not teach. `upload.html` collected a topic, ran
a fake progress bar, then redirected the browser to the Streamlit app on port
8501 -- so "start lesson" meant "leave". Everything here is the same
orchestrator the Streamlit app drives; only the surface is new.

Segments are built on a BACKGROUND THREAD and polled, rather than returned
from the POST that asks for them. One segment is a plan lookup, a retrieval, a
teaching call, a TTS render and a ~60s board video: comfortably past the point
where a browser or a proxy gives up on a request. Polling also gives the page
something honest to show while it waits, instead of a spinner that cannot say
which of the five steps is running.

Kept out of server.py deliberately: that file is being worked on, and a router
in its own module merges cleanly.
"""

from __future__ import annotations

import sys
import threading
import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env before orchestrator, which imports llm, which reads the provider
# and the key at import time. server.py never did this, so the web UI would
# have picked up the default provider with no key even when .env was correct.
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except Exception:
    pass

import orchestrator as orch                                    # noqa: E402
from shared.models import LearnerProfile, StudentResponse       # noqa: E402

router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Where _build_media writes. Everything served by /api/lesson/media must
# resolve inside here -- see _media_url and serve_media.
_MEDIA_ROOT = (_ROOT / "out").resolve()


# ---------------------------------------------------------------------------
# Live sessions
# ---------------------------------------------------------------------------

class _Live:
    """One browser's lesson: the session, what has been taught, and the job."""

    def __init__(self) -> None:
        self.session = None
        self.segments: list[dict] = []
        self.report: dict | None = None
        self.job: dict = {"state": "idle", "phase": "", "error": ""}
        self.lock = threading.Lock()


# Bounded for the same reason orchestrator bounds its own runtime: a long-lived
# server that never evicts grows until it is killed. Oldest out first.
_LIVE: dict[str, _Live] = {}
_MAX_LIVE = 32


def _live(session_id: str) -> _Live | None:
    return _LIVE.get(session_id)


def _new_live() -> tuple[str, _Live]:
    while len(_LIVE) >= _MAX_LIVE:
        _LIVE.pop(next(iter(_LIVE)), None)
    sid = uuid.uuid4().hex[:12]
    live = _Live()
    _LIVE[sid] = live
    return sid, live


def _spawn(live: _Live, phase: str, fn) -> None:
    """Run `fn` off the request thread, recording progress on `live.job`."""
    live.job = {"state": "running", "phase": phase, "error": ""}

    def run() -> None:
        try:
            fn()
            live.job = {"state": "done", "phase": phase, "error": ""}
        except Exception as exc:
            # Surfaced to the page rather than only to the log: a lesson that
            # dies on a missing API key should say so on screen.
            traceback.print_exc()
            live.job = {"state": "error", "phase": phase,
                        "error": f"{type(exc).__name__}: {exc}"}

    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------------------
# Shaping orchestrator output for the page
# ---------------------------------------------------------------------------

def _media_url(path: str | None) -> str | None:
    """A servable URL for a file the media pipeline wrote, or None.

    Paths from SegmentMedia are filesystem paths relative to the repo root, so
    they cannot be handed to the browser directly.
    """
    if not path:
        return None
    try:
        resolved = (_ROOT / path).resolve()
        rel = resolved.relative_to(_MEDIA_ROOT)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return f"/api/lesson/media/{rel.as_posix()}"


def _question_dict(question) -> dict | None:
    if question is None:
        return None
    return {
        "id": question.id,
        "kind": question.kind,
        "prompt": question.prompt,
        "options": list(question.options or []) or None,
    }


def _segment_dict(session, segment, media) -> dict:
    name = None
    for concept in session.plan.concepts:
        if concept.id == segment.concept_id:
            name = concept.name
            break
    return {
        "concept_id": segment.concept_id,
        "concept": name or segment.concept_id,
        "script": segment.script,
        "visual_kind": segment.visual.kind if segment.visual else "none",
        "caption": (segment.visual.caption if segment.visual else "") or "",
        "video": _media_url(media.video_mp4),
        "audio": _media_url(media.audio_wav),
        "image": _media_url(media.visual_png),
        "question": _question_dict(segment.question),
        "citations": [
            {"source": getattr(c, "source", "") or "",
             "text": (getattr(c, "text", "") or "")[:240]}
            for c in (segment.citations or [])
        ],
        "notes": list(media.notes or []),
        "answered": None,
    }


def _teach_one(live: _Live) -> None:
    """Advance the lesson by one segment, or finish it."""
    session = live.session
    runtime = orch.runtime(session)
    # A queued re-explanation outranks "the lesson is over": answer() parks it
    # on the runtime, and step() serves it before any new concept. Checking
    # is_finished alone would drop the re-teach the student just earned.
    if runtime.pending is None and orch.is_finished(session):
        _finish(live)
        return
    segment = orch.step(session)
    media = orch.media_for(session, segment)
    with live.lock:
        live.segments.append(_segment_dict(session, segment, media))


def _finish(live: _Live) -> None:
    report = orch.finish(live.session)
    live.report = {
        "score": report.score,
        "strong": list(report.strong),
        "weak": list(report.weak),
        "misconceptions": list(report.misconceptions),
        "revise": list(report.revise),
        "next_topic": report.next_topic,
    }


def _state(session_id: str, live: _Live) -> dict:
    session = live.session
    plan = getattr(session, "plan", None)
    return {
        "session_id": session_id,
        "job": live.job,
        "ready": session is not None,
        "topic": getattr(plan, "topic", "") if plan else "",
        "language": getattr(plan, "language", "en") if plan else "en",
        "concepts": [c.name for c in plan.concepts] if plan else [],
        "current": getattr(session, "current_concept", 0) if session else 0,
        "total": len(plan.concepts) if plan else 0,
        "finished": live.report is not None,
        "segments": live.segments,
        "report": live.report,
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class StartBody(BaseModel):
    topic: str = ""
    level: str = "intermediate"
    minutes: int = 20
    goal: str = ""
    language: str = "en"
    student_id: str = "student"
    file_path: str | None = None


@router.post("/api/lesson/start")
def lesson_start(body: StartBody) -> JSONResponse:
    topic = (body.topic or "").strip()
    if not topic:
        return JSONResponse({"error": "Name a topic to learn."}, status_code=400)

    level = body.level if body.level in ("beginner", "intermediate", "advanced") \
        else "intermediate"
    profile = LearnerProfile(
        level=level,
        language=body.language or "en",
        time_minutes=max(5, min(int(body.minutes or 20), 60)),
        goal=(body.goal or "").strip() or None,
    )

    session_id, live = _new_live()

    def build() -> None:
        live.session = orch.start_session(
            topic=topic, profile=profile,
            file_path=body.file_path, student_id=body.student_id,
        )
        _teach_one(live)

    _spawn(live, "Planning the lesson", build)
    return JSONResponse({"session_id": session_id})


@router.get("/api/lesson/state")
def lesson_state(session_id: str) -> JSONResponse:
    live = _live(session_id)
    if live is None:
        return JSONResponse({"error": "That lesson is no longer open."},
                            status_code=404)
    return JSONResponse(_state(session_id, live))


@router.post("/api/lesson/next")
def lesson_next(session_id: str) -> JSONResponse:
    live = _live(session_id)
    if live is None:
        return JSONResponse({"error": "That lesson is no longer open."},
                            status_code=404)
    if live.session is None or live.job.get("state") == "running":
        return JSONResponse({"ok": False, "job": live.job})
    _spawn(live, "Building the next segment", lambda: _teach_one(live))
    return JSONResponse({"ok": True})


class AnswerBody(BaseModel):
    session_id: str
    question_id: str
    answer: str


@router.post("/api/lesson/answer")
def lesson_answer(body: AnswerBody) -> JSONResponse:
    live = _live(body.session_id)
    if live is None or live.session is None:
        return JSONResponse({"error": "That lesson is no longer open."},
                            status_code=404)
    text = (body.answer or "").strip()
    if not text:
        return JSONResponse({"error": "Type an answer first."}, status_code=400)

    evaluation = orch.answer(
        live.session,
        StudentResponse(question_id=body.question_id, answer=text),
    )
    result = {
        "correct": bool(evaluation.correct),
        "feedback": evaluation.feedback,
        "action": evaluation.action,
        "misconception": evaluation.misconception,
    }
    # Mark the segment this answered so a reload does not re-ask it.
    with live.lock:
        for seg in reversed(live.segments):
            if seg.get("question") and seg["question"]["id"] == body.question_id:
                seg["answered"] = {**result, "given": text}
                break
    return JSONResponse(result)


@router.post("/api/lesson/finish")
def lesson_finish(session_id: str) -> JSONResponse:
    live = _live(session_id)
    if live is None or live.session is None:
        return JSONResponse({"error": "That lesson is no longer open."},
                            status_code=404)
    if live.job.get("state") == "running":
        return JSONResponse({"ok": False, "job": live.job})
    _spawn(live, "Marking the final quiz", lambda: _finish(live))
    return JSONResponse({"ok": True})


@router.get("/api/lesson/media/{path:path}")
def serve_media(path: str):
    """Serve one generated file, confined to out/.

    The media pipeline writes outside static/, so it needs its own route;
    resolving and containing keeps that from becoming a way to read the repo.
    """
    try:
        target = (_MEDIA_ROOT / path).resolve()
    except (OSError, ValueError):
        return HTMLResponse("Not Found", status_code=404)
    if not target.is_relative_to(_MEDIA_ROOT) or not target.is_file():
        return HTMLResponse("Not Found", status_code=404)
    return FileResponse(target)


@router.get("/lesson")
def serve_lesson():
    page = STATIC_DIR / "lesson.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>lesson.html not found</h1>", status_code=404)
