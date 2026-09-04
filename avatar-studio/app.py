"""Avatar Studio — FastAPI backend (routes and wiring only).

POST /api/render  {text, voice, still_mode?} -> {job_id}
GET  /api/jobs/{job_id}                       -> job state
GET  /api/voices                              -> voice list
GET  /api/health                              -> setup status

Rendering, polling, and cleanup belong to jobs.JobManager; speech to
tts.py; the paid engine behind the RenderEngine interface in avatar.py.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import avatar
import jobs
import tts
import wav2lip_engine

ROOT = Path(__file__).resolve().parent
# Standalone project: secrets come only from its own .env, never the repo's.
load_dotenv(ROOT / ".env")

MAX_TEXT = 600

# Free by default: Wav2Lip runs on this machine, no key, no per-render cost.
# AVATAR_ENGINE=replicate opts into the paid cloud engine (needs a token).
if os.environ.get("AVATAR_ENGINE", "wav2lip") == "replicate":
    engine = avatar.ReplicateEngine()
else:
    engine = wav2lip_engine.Wav2LipEngine()

manager = jobs.JobManager(
    engine,
    audio_dir=ROOT / "output" / "audio",
    video_dir=ROOT / "output" / "videos",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    manager.start()          # periodic eviction of stale jobs
    yield
    manager.stop()


app = FastAPI(title="Avatar Studio", lifespan=lifespan)


class RenderRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    voice: str = tts.DEFAULT_VOICE


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "engine": engine.name,
        "engine_ready": engine.available(),
        "engine_hint": engine.setup_hint(),
        "voice_count": len(tts.VOICES),
        "avatar_photo": engine.image_path.is_file(),
        "max_text": MAX_TEXT,          # single source the page mirrors
    }


@app.get("/api/voices")
async def voices():
    return tts.list_voices()


@app.get("/api/history")
async def history():
    """Finished renders, newest first — what the gallery shows on load."""
    return await manager.history()


@app.post("/api/render")
async def render(req: RenderRequest):
    if req.voice not in {v["id"] for v in tts.VOICES}:
        raise HTTPException(400, f"Unknown voice {req.voice!r}")
    job_id = manager.create(req.text, req.voice)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job(job_id: str):
    snapshot = await manager.get(job_id)
    if snapshot is None:
        raise HTTPException(404, "Unknown job")
    return snapshot


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
app.mount("/output", StaticFiles(directory=ROOT / "output"), name="output")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)