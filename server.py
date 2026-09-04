"""FastAPI front end for Mentora — serves frontend/ and wraps the orchestrator.

Run it with:

    .venv/bin/uvicorn server:app --port 8000

Everything the browser can do goes through `orchestrator`, exactly as app.py
does. Nothing here contains teaching logic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

# Load .env BEFORE orchestrator, which imports llm, which reads the provider
# and the API key at import time. Without this the server always fell back to
# the Gemini default with no key, and every /api call returned a 500 reading
# "No Gemini API key found" even with a perfectly good GROQ_API_KEY sitting in
# .env. app.py has always done this; server.py was missing it.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

import llm
import orchestrator as orch
from shared.models import LearnerProfile, StudentResponse

app = FastAPI(title="Mentora API")

REPO_ROOT = Path(__file__).parent.resolve()
FRONTEND_DIR = (REPO_ROOT / "frontend").resolve()

# Only these directories are reachable over /media. Serving the whole repo
# would put .env, mentora.db and the source itself one URL away.
MEDIA_ROOTS = [
    REPO_ROOT / "out",
    REPO_ROOT / "cache",
    REPO_ROOT / "prompt_101" / "media_pipeline" / "output",
]

# One browser, one lesson: this server is the demo's single-user front end.
# The lock matters anyway — orchestrator state is not re-entrant, and two
# overlapping /api/answer calls would advance current_concept twice.
_SESSIONS: dict[str, object] = {}
_LOCK = asyncio.Lock()


def _current():
    return _SESSIONS.get("current")


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _media_payload(session, segment) -> dict:
    """Rendered paths for a segment, as URLs the page can actually load."""
    media = orch.media_for(session, segment)
    return {
        "visual_png": _as_url(media.visual_png),
        "audio_wav": _as_url(media.audio_wav),
        "video_mp4": _as_url(media.video_mp4),
        "notes": media.notes,
    }


def _as_url(path: str | None) -> str | None:
    """Expose a rendered file under /media/... , or None if it is not there.

    The media paths are local filesystem paths; handing them to a browser
    unchanged gives a 404 every time. serve_media resolves them back.
    """
    if not path:
        return None
    target = Path(path).resolve()
    if not target.is_file():
        return None
    for root in MEDIA_ROOTS:
        if target.is_relative_to(root):
            return "/media/" + target.relative_to(REPO_ROOT).as_posix()
    return None


def _segment_payload(session, segment) -> dict:
    question = None
    if segment.question is not None:
        question = {
            "id": segment.question.id,
            "kind": segment.question.kind,
            "prompt": segment.question.prompt,
            "options": segment.question.options,
        }
    return {
        "concept_id": segment.concept_id,
        "segment_text": segment.script,
        "visual_kind": segment.visual.kind,
        "caption": segment.visual.caption,
        "question": question,
        "citations": [
            {"page": c.page, "score": c.score, "text": c.text}
            for c in segment.citations
        ],
        # The media was being built and then thrown away — the local variable
        # was assigned and never read, so the page had no video, no audio and
        # no diagram to show even though all three had just been rendered.
        "media": _media_payload(session, segment),
        "finished": orch.is_finished(session) and orch.runtime(session).pending is None,
    }


# ---------------------------------------------------------------------------
# Static files
#
# This was a bare @app.get("/{filename}") catch-all, which shadows every GET
# route declared after it and happily served anything the path resolved to.
# Both routes below resolve the target and require it to stay inside the
# directory they are meant to serve.
# ---------------------------------------------------------------------------

def _safe_file(root: Path, relative: str) -> Path | None:
    try:
        target = (root / relative).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/media/{path:path}")
async def serve_media(path: str):
    """Rendered visuals, narration and video, for the page to display."""
    target = _safe_file(REPO_ROOT, path)
    if target is None or not any(target.is_relative_to(r) for r in MEDIA_ROOTS):
        return HTMLResponse("Not Found", status_code=404)
    return FileResponse(target)


@app.get("/{filename:path}")
async def serve_file(filename: str):
    target = _safe_file(FRONTEND_DIR, filename)
    if target is None:
        return HTMLResponse("Not Found", status_code=404)
    return FileResponse(target)


# ---------------------------------------------------------------------------
# API
#
# Every handler here is `async`, and every orchestrator call it makes is
# blocking: an LLM round trip, ffmpeg, a Wav2Lip render. Calling those directly
# from a coroutine pins the event loop for the whole lesson — the page cannot
# even fetch its own CSS while a segment renders. run_in_threadpool hands them
# to a worker thread, which is what FastAPI does for a plain `def` handler.
# ---------------------------------------------------------------------------

@app.post("/api/start")
async def start_lesson(request: Request):
    data = await request.json()
    topic = (data.get("topic") or "").strip() or "Electricity"
    api_key = data.get("api_key")
    language = data.get("language") or "en"
    level = data.get("level") or "beginner"
    minutes = int(data.get("time_minutes") or 15)

    if api_key:
        # Setting os.environ here did nothing: llm reads the key at import and
        # caches the client that holds it, so the pasted key was never used and
        # the request went out on whatever was in .env at startup.
        llm.configure(api_key=api_key)

    profile = LearnerProfile(
        level=level, language=language, time_minutes=minutes, goal=topic,
    )

    async with _LOCK:
        try:
            session = await run_in_threadpool(
                orch.start_session, topic, profile)
            segment = await run_in_threadpool(orch.step, session)
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}", 502)
        _SESSIONS["current"] = session

    return JSONResponse({
        "status": "started",
        "topic": topic,
        "session_id": session.session_id,
        "concepts": [c.name for c in session.plan.concepts],
        **_segment_payload(session, segment),
    })


@app.post("/api/ask")
async def ask_question(request: Request):
    data = await request.json()
    question = (data.get("question") or "").strip()
    session = _current()

    if not session:
        return _error("No active session")
    if not question:
        return _error("Ask something first")

    async with _LOCK:
        reply = await run_in_threadpool(orch.ask, session, question)
    return JSONResponse({"reply": reply})


@app.post("/api/answer")
async def answer_question(request: Request):
    data = await request.json()
    question_id = data.get("question_id")
    answer = data.get("answer")
    session = _current()

    if not session:
        return _error("No active session")
    if not question_id or not str(answer or "").strip():
        return _error("question_id and answer are both required")

    response = StudentResponse(question_id=question_id, answer=str(answer))
    async with _LOCK:
        try:
            evaluation = await run_in_threadpool(orch.answer, session, response)
        except KeyError as exc:
            return _error(str(exc), 404)
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}", 502)
        panel = orch.runtime(session).panel

    return JSONResponse({
        "correct": evaluation.correct,
        "feedback": evaluation.feedback,
        "action": evaluation.action,
        "misconception": evaluation.misconception,
        # What the teacher actually decided to do, so the page can show the
        # adaptation rather than just the verdict.
        "adaptation": {
            "action_taken": panel.action_taken,
            "escalated": panel.escalated,
            "attempt": panel.attempt,
            "difficulty": panel.difficulty,
        },
    })


@app.post("/api/next")
async def next_segment(request: Request):
    """The next segment — new material, or a queued re-explanation."""
    session = _current()
    if not session:
        return _error("No active session")

    async with _LOCK:
        rt = orch.runtime(session)
        if rt.pending is None and orch.is_finished(session):
            return JSONResponse({"finished": True})
        try:
            segment = await run_in_threadpool(orch.step, session)
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}", 502)

    return JSONResponse(_segment_payload(session, segment))


@app.post("/api/finish")
async def finish_lesson():
    session = _current()
    if not session:
        return _error("No active session")

    async with _LOCK:
        try:
            report = await run_in_threadpool(orch.finish, session)
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}", 502)

    return JSONResponse(report.model_dump())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
