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
        self.notes: str = ""
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

    The quiz is the LAST thing a lesson does and the least important. If
    writing it fails -- a rate limit at the end of a long lesson is the
    obvious case -- the student must still get the report they earned, not an
    error where their result should be. Any failure degrades to the report.
    """
    try:
        questions = orch.quiz_questions(live.session)
        live.quiz = [_question_dict(q) for q in questions if q is not None]
    except Exception as exc:
        traceback.print_exc()
        live.quiz = []
        live.notes = f"The final quiz could not be written ({type(exc).__name__}); " \
                     "this report is marked on the lesson itself."
    if not live.quiz:
        _finish(live)


def _submit_quiz(live: _Live, answers: dict) -> None:
    try:
        report = orch.submit_quiz(live.session, answers)
    except Exception as exc:
        # Same rule: a marking failure must not cost the student the report.
        traceback.print_exc()
        live.notes = f"The quiz could not be marked ({type(exc).__name__}); " \
                     "this report covers the lesson itself."
        live.quiz = None
        _finish(live)
        return
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
    try:
        report = orch.finish(live.session)
    except Exception as exc:
        traceback.print_exc()
        # Even here there is something honest to show: the lesson happened.
        live.notes = (live.notes or "") + \
            f" The report could not be generated ({type(exc).__name__})."
        live.report = {"score": 0.0, "strong": [], "weak": [],
                       "misconceptions": [], "revise": [],
                       "next_topic": ""}
        return
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
        # The handle above is this module's; the orchestrator has its own, and
        # that is what turns, reports and study_sessions are keyed on. Without
        # it the page cannot link to the transcript or the report of the very
        # lesson it just finished.
        "lesson_id": getattr(session, "session_id", "") if session else "",
        "job": live.job,
        "ready": session is not None,
        "topic": getattr(plan, "topic", "") if plan else "",
        "language": getattr(plan, "language", "en") if plan else "en",
        "concepts": [c.name for c in plan.concepts] if plan else [],
        "current": getattr(session, "current_concept", 0) if session else 0,
        "total": len(plan.concepts) if plan else 0,
        "finished": live.report is not None,
        "quiz": live.quiz,
        "notes": live.notes,
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
        teacher=prefs.get("teacher") or "maya",
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
        "teacher": prefs.get("teacher") or "maya",
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
    teacher: str | None = None
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
    if body.teacher:
        patch["teacher"] = body.teacher
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


# ---------------------------------------------------------------------------
# Transcripts
#
# Every turn of every lesson has been written to the turns table since the
# history store shipped -- 450 of them here -- and nothing ever read them
# back. Clicking a past lesson now opens what was actually said in it.
# ---------------------------------------------------------------------------

def _lesson_id(session_id: str) -> str:
    """Accept either id: this module's live handle, or the stored lesson id.

    Links made during a lesson carry the handle; links made from the
    dashboard carry the stored id. Translating here means every link works
    rather than only half of them.
    """
    live = _LIVE.get(session_id)
    if live is not None and live.session is not None:
        return getattr(live.session, "session_id", session_id) or session_id
    return session_id


@router.get("/api/transcript")
def transcript(session_id: str, student_id: str = "student") -> JSONResponse:
    import sqlite3

    if not session_id:
        return JSONResponse({"error": "Which lesson?"}, status_code=400)
    session_id = _lesson_id(session_id)

    db = _ROOT / "mentora.db"
    if not db.exists():
        return JSONResponse({"error": "No history yet."}, status_code=404)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM study_sessions WHERE session_id=? AND student_id=?",
                    (session_id, student_id))
        lesson = cur.fetchone()
        cur.execute("SELECT * FROM reports WHERE session_id=? AND student_id=?",
                    (session_id, student_id))
        report = cur.fetchone()
        cur.execute("SELECT role, content, concept_id, timestamp FROM turns "
                    "WHERE session_id=? ORDER BY id ASC", (session_id,))
        rows = cur.fetchall()
    finally:
        conn.close()

    if lesson is None and not rows:
        return JSONResponse({"error": "No transcript for that lesson."},
                            status_code=404)

    # Turns carry a concept id, not a name. Numbering the distinct ids in the
    # order they were first spoken gives the transcript readable section
    # headings without needing the plan, which is not persisted.
    order: dict[str, int] = {}
    turns = []
    for r in rows:
        cid = r["concept_id"] or ""
        if cid and cid not in order:
            order[cid] = len(order) + 1
        turns.append({
            "role": r["role"],
            "content": r["content"],
            "concept": order.get(cid, 0),
            "at": r["timestamp"] or "",
        })

    return JSONResponse({
        "session_id": session_id,
        "topic": (lesson["topic"] if lesson else "") or "Lesson",
        "started": (lesson["started_at"] if lesson else "") or "",
        "ended": (lesson["ended_at"] if lesson else "") or "",
        "minutes": (lesson["minutes_planned"] if lesson else 0) or 0,
        "score": (report["score"] if report else None),
        "next_topic": (report["next_topic"] if report else "") or "",
        "concepts": len(order),
        "turns": turns,
    })


@router.get("/transcript")
def serve_transcript():
    page = STATIC_DIR / "transcript.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>transcript.html not found</h1>", status_code=404)


# ---------------------------------------------------------------------------
# Flashcards
#
# The deck, the SM-2 scheduler and the review-recording have been in the
# orchestrator since it shipped, and 16 real cards are sitting in the table.
# The web UI had no way to reach any of it: the sidebar's flashcard count
# linked to the review page, which does not review cards.
# ---------------------------------------------------------------------------

@router.get("/api/flashcards")
def flashcards(student_id: str = "student") -> JSONResponse:
    due = orch.due_reviews(student_id)
    every = orch.browse_flashcards(student_id)
    due_keys = {c.get("card_key") for c in due}
    return JSONResponse({
        "due": due,
        "all": every,
        "counts": {"due": len(due), "total": len(every),
                   "later": len([c for c in every
                                 if c.get("card_key") not in due_keys])},
    })


class ReviewBody(BaseModel):
    card_key: str
    front: str = ""
    back: str = ""
    source: str = "lesson"
    ease: str = "good"          # again | hard | good | easy
    student_id: str = "student"


@router.post("/api/flashcards/review")
def review_flashcard(body: ReviewBody) -> JSONResponse:
    if body.ease not in ("again", "hard", "good", "easy"):
        return JSONResponse({"error": "Unknown rating."}, status_code=400)
    interval = orch.record_flashcard(
        body.student_id,
        {"card_key": body.card_key, "front": body.front,
         "back": body.back, "source": body.source},
        body.ease,
    )
    if interval is None:
        return JSONResponse({"error": "Could not save that review."},
                            status_code=500)
    days = float(interval)
    return JSONResponse({
        "ok": True,
        "interval_days": days,
        "next": "again today" if days < 1
                else ("tomorrow" if days < 2 else f"in {round(days)} days"),
    })


@router.get("/flashcards")
def serve_flashcards():
    page = STATIC_DIR / "flashcards.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>flashcards.html not found</h1>", status_code=404)


@router.get("/api/summary")
def summary(session_id: str, student_id: str = "student") -> JSONResponse:
    """A plain-text summary of one lesson, for the download button.

    The button existed and pointed at #download-summary, which does nothing
    at all.
    """
    data = transcript(session_id, student_id)
    import json as _json
    d = _json.loads(bytes(data.body).decode("utf-8"))
    if "error" in d:
        return data

    lines = [f"MENTORA - {d['topic']}", "=" * (10 + len(d["topic"])), ""]
    if d.get("started"):
        lines.append(f"Date       : {d['started'][:10]}")
    if d.get("score") is not None:
        lines.append(f"Score      : {round(d['score'])}/100")
    lines += [f"Concepts   : {d['concepts']}",
              f"Exchanges  : {len(d['turns'])}"]
    if d.get("next_topic"):
        lines.append(f"Next topic : {d['next_topic']}")
    lines += ["", "TRANSCRIPT", "-" * 10, ""]
    who = {"teacher": "Mentora", "student": "You", "system": "Lesson"}
    section = -1
    for t in d["turns"]:
        if t["concept"] != section:
            section = t["concept"]
            lines += ["", f"[{'Concept ' + str(section) if section else 'Lesson'}]", ""]
        lines.append(f"{who.get(t['role'], t['role'])}: {t['content']}")
        lines.append("")

    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in d["topic"]).strip()
    name = (safe.replace(" ", "-").lower() or "lesson") + ".txt"
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------------------------------------------------------------------------
# Voice mode
#
# A spoken conversation with the teacher. Speech in and speech out both
# happen in the BROWSER -- SpeechRecognition and speechSynthesis -- because a
# server round trip through edge-tts plus a board render is 30-60 seconds,
# which is a lecture, not a conversation. The server does the two things the
# browser cannot: think of the reply, and draw the diagram.
#
# The visual is a still PNG, not a board video. Rendering one measures 0.07s
# against 30s+ for video, and in a live exchange the picture has to be there
# while the sentence is still being spoken.
# ---------------------------------------------------------------------------

_VOICE_DIR = (_ROOT / "out" / "voice").resolve()

VOICE_PROMPT = """You are Mentora, a patient human teacher, talking OUT LOUD
with a student. This is speech, not an essay.

Rules for what you say:
- At most 70 words. It is spoken aloud; long answers are unbearable to listen
  to and the student cannot re-read them.
- Answer the actual question first, in one or two plain sentences.
- No markdown, no bullet points, no headings, no emoji, no stage directions.
  Write what a person would SAY.
- End by inviting the next step only if it is natural. Do not end every turn
  with a question.
- Speak in the language with code '<<LANGUAGE>>'.

IMPORTANT: You MUST include a visual whenever ANY of these are true:
- The student asks for a diagram, chart, drawing, or visual
- The topic involves a process, system, cycle, flow, relationship, or structure
- The topic involves a formula or equation
- There are more than 2 connected concepts that benefit from being shown
A conversational reply with no visual is fine ONLY for simple factual questions
like "what is X called" or "when did Y happen".

For diagrams use mermaid syntax (graph LR, flowchart TD, etc.).
For equations use LaTeX.

<<HISTORY>>

Student just said: <<QUESTION>>

Return ONLY this JSON:
{"answer": "what you say out loud",
 "visual": {"kind": "diagram|equation|none",
            "payload": "mermaid graph LR ... | LaTeX | \"\"",
            "caption": "short caption or null"}}
"""


class VoiceBody(BaseModel):
    text: str
    history: list[dict] = []          # [{role: "student"|"teacher", text: ...}]
    student_id: str = "student"
    language: str | None = None


@router.post("/api/voice/reply")
def voice_reply(body: VoiceBody) -> JSONResponse:
    import llm

    said = (body.text or "").strip()
    if not said:
        return JSONResponse({"error": "Nothing was heard."}, status_code=400)

    prefs = hdb.get_preferences(body.student_id)
    language = body.language or prefs.get("language") or "en"

    # Only the last few turns: this is a conversation, and the whole history
    # would cost latency the student hears as a pause.
    tail = [t for t in (body.history or []) if t.get("text")][-6:]
    history = "\n".join(
        f"{'Student' if t.get('role') == 'student' else 'You'}: {t['text']}"
        for t in tail
    )
    prompt = (VOICE_PROMPT
              .replace("<<LANGUAGE>>", language)
              .replace("<<HISTORY>>", ("Conversation so far:\n" + history) if history else "")
              .replace("<<QUESTION>>", said))

    try:
        data = llm.generate_json(prompt)
    except Exception as exc:
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"},
                            status_code=502)

    answer = (data or {}).get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return JSONResponse({"error": "The teacher had nothing to say."},
                            status_code=502)

    image = caption = None
    visual = (data or {}).get("visual")
    if isinstance(visual, dict):
        kind = str(visual.get("kind") or "none").strip().lower()
        payload = str(visual.get("payload") or "").strip()
        # Models routinely emit a mermaid graph with LITERAL backslash-n
        # between the edges rather than real newlines. The parser then reads
        # the whole graph as a single line and invents nodes out of the
        # fragments -- "\n A[Light reactions]", "C[Calvin cycle]\n C" -- so
        # the picture is worse than no picture. Undo the escaping first.
        if "\\n" in payload:
            payload = payload.replace("\\r\\n", "\n").replace("\\n", "\n")
        payload = payload.replace("\\t", " ").strip()
        if kind in ("diagram", "equation", "graph", "concept_map") and payload:
            try:
                import hashlib

                import board_media

                caption = (visual.get("caption") or "").strip() or None
                lv = board_media._lesson_video()
                _VOICE_DIR.mkdir(parents=True, exist_ok=True)
                stamp = hashlib.sha1(
                    (kind + payload).encode("utf-8", "ignore")).hexdigest()[:10]
                dest = _VOICE_DIR / f"voice_{kind}_{stamp}.png"
                if not dest.exists():
                    # The board renderer, not the media pipeline's still one:
                    # same parse and layout as the lesson videos, where a
                    # chained mermaid arrow and a long label are handled.
                    lv.still(dest, "equation" if kind == "equation" else "diagram",
                             payload, caption or "")
                image = _media_url(str(dest.relative_to(_ROOT)))
            except Exception:
                image = caption = None      # never lose the reply over a picture

    return JSONResponse({"answer": answer.strip(), "image": image,
                         "caption": caption, "language": language})


@router.get("/voice")
def serve_voice():
    page = STATIC_DIR / "voice.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>voice.html not found</h1>", status_code=404)


@router.get("/materials")
def serve_materials():
    page = STATIC_DIR / "materials.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>materials.html not found</h1>", status_code=404)


@router.get("/api/teachers")
def teacher_presets() -> JSONResponse:
    """The teacher presets, served from the one file the renderer reads."""
    import json
    path = _ROOT / "avatar-prototype" / "teachers.json"
    try:
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return JSONResponse([{"id": "maya", "name": "Ms. Maya", "variant": "f",
                              "note": "Default", "palette": {}}])
