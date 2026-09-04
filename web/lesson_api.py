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

import os
import sys
import threading
import traceback
import uuid
from datetime import datetime, timezone
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
        self.quiz: list[dict] | None = None
        self.auto_quiz: bool = True
        self.student_id: str = "student"
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
        _end_lesson(live)
        return
    segment = orch.step(session)
    media = orch.media_for(session, segment)
    with live.lock:
        live.segments.append(_segment_dict(session, segment, media))


def _build_quiz(live: _Live) -> None:
    """Generate the end-of-lesson quiz and hold it for the page.

    finish() built a quiz and then wrote the report without ever asking it,
    so "auto-generate quiz" produced a quiz nobody ever saw and a score drawn
    only from mid-lesson questions.
    """
    questions = orch.quiz_questions(live.session)
    live.quiz = [_question_dict(q) for q in questions if q is not None]
    if not live.quiz:
        _finish(live)


def _submit_quiz(live: _Live, answers: dict) -> None:
    report = orch.submit_quiz(live.session, answers)
    live.quiz = None
    live.report = _report_dict(report)


def _report_dict(report) -> dict:
    return {
        "score": report.score,
        "strong": list(report.strong),
        "weak": list(report.weak),
        "misconceptions": list(report.misconceptions),
        "revise": list(report.revise),
        "next_topic": report.next_topic,
    }


def _finish(live: _Live) -> None:
    report = orch.finish(live.session)
    live.report = _report_dict(report)


def _end_lesson(live: _Live) -> None:
    """Quiz first if the student wants one, otherwise straight to the report."""
    if live.auto_quiz:
        _build_quiz(live)
    else:
        _finish(live)


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
        "quiz": live.quiz,
        "segments": live.segments,
        "report": live.report,
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class StartBody(BaseModel):
    topic: str = ""
    minutes: int = 20
    goal: str = ""
    student_id: str = "student"
    file_path: str | None = None
    # Unset means "use what is saved in settings". A plain default here would
    # silently override the student's own choice every time the page omitted
    # a field, which is exactly how these settings came to do nothing.
    level: str | None = None
    language: str | None = None
    persona: str | None = None
    avatar: str | None = None


@router.post("/api/lesson/start")
def lesson_start(body: StartBody) -> JSONResponse:
    topic = (body.topic or "").strip()
    if not topic:
        return JSONResponse({"error": "Name a topic to learn."}, status_code=400)

    prefs = hdb.get_preferences(body.student_id)
    level = body.level or prefs.get("difficulty") or "intermediate"
    if level not in ("beginner", "intermediate", "advanced"):
        level = "intermediate"
    avatar = body.avatar or prefs.get("avatar") or "f"
    profile = LearnerProfile(
        level=level,
        language=body.language or prefs.get("language") or "en",
        time_minutes=max(1, min(int(body.minutes or 5), 10)),
        goal=(body.goal or "").strip() or None,
        persona=body.persona or prefs.get("persona") or "socratic",
        avatar=avatar if avatar in ("f", "m") else "f",
    )

    session_id, live = _new_live()
    live.student_id = body.student_id
    live.auto_quiz = bool(prefs.get("auto_quiz", True))

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
    phase = "Writing the final quiz" if live.auto_quiz else "Marking the lesson"
    _spawn(live, phase, lambda: _end_lesson(live))
    return JSONResponse({"ok": True})


class QuizBody(BaseModel):
    session_id: str
    answers: dict[str, str] = {}


@router.post("/api/lesson/quiz")
def lesson_quiz(body: QuizBody) -> JSONResponse:
    live = _live(body.session_id)
    if live is None or live.session is None:
        return JSONResponse({"error": "That lesson is no longer open."},
                            status_code=404)
    if live.job.get("state") == "running":
        return JSONResponse({"ok": False, "job": live.job})
    answers = {k: v for k, v in (body.answers or {}).items() if str(v).strip()}
    _spawn(live, "Marking the final quiz",
           lambda: _submit_quiz(live, answers))
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


# ---------------------------------------------------------------------------
# Settings, API keys and uploaded material
#
# The settings page wrote to localStorage and nothing else, so preferences did
# not survive a different browser, and no other page could read them. They now
# live in the preferences table, which is also where the Streamlit app reads
# them from -- one set of settings for both surfaces.
# ---------------------------------------------------------------------------

import history.db as hdb                                        # noqa: E402

_UPLOAD_DIR = (_ROOT / "out" / "uploads").resolve()
_KEY_ENV = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}

LANGUAGES = [
    ("en", "English"), ("hi", "\u0939\u093f\u0928\u094d\u0926\u0940 (Hindi)"),
    ("ta", "\u0ba4\u0bae\u0bbf\u0bb4\u0bcd (Tamil)"),
    ("te", "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 (Telugu)"),
    ("kn", "\u0c95\u0ca8\u0ccd\u0ca8\u0ca1 (Kannada)"),
    ("mr", "\u092e\u0930\u093e\u0920\u0940 (Marathi)"),
    ("bn", "\u09ac\u09be\u0982\u09b2\u09be (Bengali)"),
    ("es", "Espa\u00f1ol (Spanish)"),
]


def _settings(student_id: str) -> dict:
    prefs = hdb.get_preferences(student_id)
    return {
        "language": prefs.get("language") or "en",
        "difficulty": prefs.get("difficulty") or "intermediate",
        "persona": prefs.get("persona") or "socratic",
        "avatar": prefs.get("avatar") or "f",
        "auto_quiz": bool(prefs.get("auto_quiz", True)),
        "daily_goal": prefs.get("daily_goal") or 0,
        "languages": [{"code": c, "name": n} for c, n in LANGUAGES],
        # Whether a key exists, never the key. Reading one back to the browser
        # would put it in the DOM, in logs and in any screenshot of the page.
        "keys": {name: bool(os.environ.get(env))
                 for name, env in _KEY_ENV.items()},
        "provider": os.environ.get("AI_TEACHER_PROVIDER", "groq"),
    }


@router.get("/api/settings")
def get_settings(student_id: str = "student") -> JSONResponse:
    return JSONResponse(_settings(student_id))


class SettingsBody(BaseModel):
    student_id: str = "student"
    language: str | None = None
    difficulty: str | None = None
    persona: str | None = None
    avatar: str | None = None
    daily_goal: int | None = None
    auto_quiz: bool | None = None


@router.post("/api/settings")
def save_settings(body: SettingsBody) -> JSONResponse:
    patch: dict = {}
    if body.language:
        patch["language"] = body.language
    if body.difficulty in ("beginner", "intermediate", "advanced"):
        patch["difficulty"] = body.difficulty
    if body.persona:
        patch["persona"] = body.persona
    if body.avatar in ("f", "m"):
        patch["avatar"] = body.avatar
    if body.daily_goal is not None:
        patch["daily_goal"] = int(body.daily_goal)
    if body.auto_quiz is not None:
        patch["auto_quiz"] = bool(body.auto_quiz)
    if patch:
        hdb.set_preferences(body.student_id, patch)
    return JSONResponse(_settings(body.student_id))


class KeysBody(BaseModel):
    provider: str | None = None
    groq: str | None = None
    gemini: str | None = None


@router.post("/api/keys")
def save_keys(body: KeysBody) -> JSONResponse:
    """Store API keys in .env and apply them to the running process.

    Writing .env as well as os.environ is what makes the key survive a
    restart; .env is gitignored, so it does not end up committed.
    """
    import llm

    updates: dict[str, str] = {}
    for name, env in _KEY_ENV.items():
        value = (getattr(body, name, None) or "").strip()
        if value:
            updates[env] = value
    provider = (body.provider or "").strip().lower()
    if provider in ("groq", "gemini", "ollama", "local"):
        updates["AI_TEACHER_PROVIDER"] = provider

    if not updates:
        return JSONResponse({"error": "Nothing to save."}, status_code=400)

    for env, value in updates.items():
        os.environ[env] = value

    env_path = _ROOT / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines() \
            if env_path.exists() else []
    except OSError:
        lines = []
    kept = [ln for ln in lines
            if not any(ln.strip().startswith(k + "=") for k in updates)]
    kept += [f"{k}={v}" for k, v in updates.items()]
    try:
        env_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except OSError as exc:
        return JSONResponse({"error": f"Could not write .env: {exc}"},
                            status_code=500)

    # llm caches the client and the key at import, so setting the environment
    # alone would not take effect until a restart.
    try:
        llm.configure(
            provider=updates.get("AI_TEACHER_PROVIDER"),
            api_key=updates.get(_KEY_ENV.get(
                updates.get("AI_TEACHER_PROVIDER",
                            os.environ.get("AI_TEACHER_PROVIDER", "groq")), "")),
        )
    except Exception:
        pass
    return JSONResponse({"ok": True, "saved": sorted(updates)})


@router.get("/api/materials")
def list_materials(student_id: str = "student") -> JSONResponse:
    """Everything this student has uploaded, newest first."""
    prefs = hdb.get_preferences(student_id)
    topics = {}
    for entry in prefs.get("pending_uploads") or []:
        if isinstance(entry, dict) and entry.get("name"):
            topics[entry["name"]] = entry.get("topic") or ""

    out = []
    if _UPLOAD_DIR.is_dir():
        for f in _UPLOAD_DIR.iterdir():
            if not f.is_file() or f.name.startswith("."):
                continue
            stat = f.stat()
            out.append({
                "name": f.name,
                "size": stat.st_size,
                "uploaded": datetime.fromtimestamp(
                    stat.st_mtime, timezone.utc).isoformat(),
                "topic": topics.get(f.name, ""),
                "kind": f.suffix.lstrip(".").upper() or "FILE",
                "path": str(f.relative_to(_ROOT)),
            })
    out.sort(key=lambda m: m["uploaded"], reverse=True)
    return JSONResponse({"materials": out, "count": len(out)})


class UploadBody(BaseModel):
    name: str
    content: str = ""          # base64, with or without a data: prefix
    topic: str = ""
    student_id: str = "student"


@router.post("/api/materials/upload")
def upload_material(body: UploadBody) -> JSONResponse:
    """Store one uploaded document so a lesson can be built from it.

    The page used to collect files, list them, and then throw them away: no
    request ever carried the bytes, so "your material" was decoration and the
    material list was always empty.
    """
    import base64
    import re

    name = Path(body.name or "").name          # basename only; no traversal
    if not name:
        return JSONResponse({"error": "No filename."}, status_code=400)
    if Path(name).suffix.lower() not in (".pdf", ".docx", ".pptx", ".txt", ".md"):
        return JSONResponse({"error": f"{name}: unsupported file type."},
                            status_code=400)

    raw = re.sub(r"^data:[^;]*;base64,", "", body.content or "")
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception:
        return JSONResponse({"error": f"{name}: could not read the file."},
                            status_code=400)
    if not data:
        return JSONResponse({"error": f"{name} is empty."}, status_code=400)
    if len(data) > 200 * 1024 * 1024:
        return JSONResponse({"error": f"{name} is over 200MB."}, status_code=400)

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = _UPLOAD_DIR / name
    target.write_bytes(data)

    prefs = hdb.get_preferences(body.student_id)
    pending = [e for e in (prefs.get("pending_uploads") or [])
               if not (isinstance(e, dict) and e.get("name") == name)]
    pending.append({"name": name, "size": len(data), "topic": body.topic or ""})
    hdb.set_preferences(body.student_id, {"pending_uploads": pending})

    return JSONResponse({"ok": True, "name": name, "size": len(data),
                         "path": str(target.relative_to(_ROOT))})
