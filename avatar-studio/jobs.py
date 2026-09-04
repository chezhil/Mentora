"""The render job state machine — one owner for every job and its files.

Lifecycle of a job, driven by the engine injected at construction:

    submit -> poll -> download -> evict

Ownership rules:

  - Job *records* and terminal *videos* are owned here. A terminal job is
    evicted (record dropped, video deleted) JOB_TTL_SECONDS after its last
    state change; a sweep task enforces that, plus lazy eviction on read.
  - Finished renders are *durable*: on success the job's metadata is written
    to a JSON sidecar next to its video (<video_dir>/<id>.json), and start()
    adopts those back into memory — deleting stray .mp4 files that have no
    sidecar and sidecars whose video is gone — so records and files can
    never drift apart across restarts.
  - A transient *audio* file (output/audio/<id>.wav) is owned by the run
    itself: it exists only between TTS and the engine accepting it, and is
    deleted no matter how that hand-off ends.
  - A *running* job that outlives MAX_RUN_SECONDS is declared dead here —
    only _run() ever writes a job's status, so it cannot be resurrected.

The engine is deliberately not imported: it only has to satisfy the
RenderEngine protocol. Engines live next to jobs.py and are chosen in
app.py: wav2lip_engine.Wav2LipEngine (free, on-device — the default) and
avatar.ReplicateEngine (paid, cloud).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Protocol

import tts

# Job life spans, in seconds.
JOB_TTL_SECONDS = 2 * 3600     # terminal jobs (and their video) live this long
MAX_RUN_SECONDS = 20 * 60      # a render stuck longer than this is dead
                               # (generous: on-device CPU engines are slow)
SWEEP_SECONDS = 60.0           # how often the eviction sweep runs
HISTORY_LIMIT = 12             # finished renders the /api/history endpoint returns

PUBLIC_FIELDS = ("id", "status", "message", "text", "voice", "video_url", "error")


class EngineUnavailable(RuntimeError):
    """An engine that cannot render (missing key, package, or photo).

    The message is user-facing and shown verbatim in the UI.
    """


class RenderEngine(Protocol):
    """What a talking-head engine must do to be a JobManager's engine."""

    def available(self) -> bool: ...
    def submit(self, audio_path: Path, overrides: dict | None = None) -> Any:
        """Start one render from a WAV; return an opaque handle with
        `.id`, `.status` and `.error` attributes."""
        ...
    def poll(self, prediction_id: str) -> Any: ...
    def output_url(self, prediction: Any) -> str | None: ...
    def download(self, url: str, dest: Path) -> Path: ...


def _as_time(value, fallback: float) -> float:
    """A timestamp from a sidecar, however it was written."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return out if out == out and abs(out) != float("inf") else fallback


class JobManager:
    """In-memory job store with a state machine per job and file cleanup."""

    def __init__(self, engine: RenderEngine, *, audio_dir: Path, video_dir: Path,
                 poll_seconds: float = 2.0) -> None:
        self.engine = engine
        self.audio_dir = Path(audio_dir)
        self.video_dir = Path(video_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.poll_seconds = poll_seconds
        self._jobs: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._sweep_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ app
    def start(self) -> None:
        """Adopt finished renders from disk, then begin periodic eviction.

        Call from the app's lifespan, before serving requests.
        """
        adopted, removed = self._adopt()
        if adopted or removed:
            print(f"[jobs] adopted {adopted} finished render(s), "
                  f"removed {removed} stray file(s)", flush=True)
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.get_running_loop().create_task(self._sweep())

    def stop(self) -> None:
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            self._sweep_task = None

    async def _sweep(self) -> None:
        try:
            while True:
                await asyncio.sleep(SWEEP_SECONDS)
                try:
                    await self.prune()
                except Exception:          # never let the sweeper die
                    pass
        except asyncio.CancelledError:
            pass

    # ----------------------------------------------------------------- API
    def create(self, text: str, voice: str) -> str:
        """Record a new job and start its state machine. Returns the id."""
        now = time.time()
        job_id = uuid.uuid4().hex[:10]
        self._jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "message": "Queued",
            "text": text,
            "voice": voice,
            "video_url": None,
            "error": None,
            "video_path": None,
            "created": now,
            "updated": now,
        }
        asyncio.get_running_loop().create_task(self._run(job_id))
        return job_id

    async def get(self, job_id: str) -> Optional[dict]:
        """Public snapshot of a job, or None when unknown/evicted."""
        now = time.time()
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job["status"] in ("succeeded", "failed") \
                    and now - job["updated"] > JOB_TTL_SECONDS:
                self._drop(job_id, job)          # lazy eviction on read
                return None
            return {k: job[k] for k in PUBLIC_FIELDS}

    async def history(self, limit: int = HISTORY_LIMIT) -> list[dict]:
        """Finished renders, newest first — what the page's gallery shows."""
        async with self._lock:
            done = [j for j in self._jobs.values()
                    if j["status"] == "succeeded"]
        done.sort(key=lambda j: j["updated"], reverse=True)
        return [{k: j[k] for k in PUBLIC_FIELDS} for j in done[:limit]]

    async def prune(self) -> int:
        """Evict every terminal job past its TTL. Returns how many went."""
        now = time.time()
        async with self._lock:
            expired = [(jid, job) for jid, job in list(self._jobs.items())
                       if job["status"] in ("succeeded", "failed")
                       and now - job["updated"] > JOB_TTL_SECONDS]
            for jid, job in expired:
                self._drop(jid, job)
        return len(expired)

    def _drop(self, job_id: str, job: dict) -> None:
        """Remove a record and delete whatever it produced. Lock held by caller."""
        video = job.get("video_path")
        if video:
            try:
                Path(video).unlink(missing_ok=True)
            except OSError:
                pass
        self._sidecar(job_id).unlink(missing_ok=True)
        self._jobs.pop(job_id, None)

    # --------------------------------------------------------- persistence
    def _sidecar(self, job_id: str) -> Path:
        return self.video_dir / f"{job_id}.json"

    def _persist(self, job: dict) -> None:
        """Write the finished render's metadata next to its video."""
        meta = {k: job[k] for k in
                ("id", "text", "voice", "video_url", "created", "updated")}
        sidecar = self._sidecar(job["id"])
        tmp = sidecar.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(sidecar)

    def _adopt(self) -> tuple[int, int]:
        """Sync the in-memory store with what is on disk. Returns
        (adopted, removed): videos with a metadata sidecar become finished
        job records; anything left over — mp4 without sidecar, sidecar
        without mp4, unreadable sidecar — is deleted."""
        now = time.time()
        adopted = removed = 0
        for sidecar in self.video_dir.glob("*.json"):
            jid = sidecar.stem
            # The try has to cover the WHOLE record, not just the parse. It
            # used to wrap json.loads alone, so a sidecar that was valid JSON
            # but the wrong shape got past it and then raised: a list or a
            # string has no .get, and float() rejects "yesterday", null or a
            # dict. _adopt runs from start(), inside the app's lifespan, so
            # any of those took the whole service down at boot -- and a
            # sidecar half-written by a crash or a full disk looks exactly
            # like that. Treat every malformed one the way an unreadable one
            # was already treated: delete it and move on.
            mp4 = self.video_dir / f"{jid}.mp4"
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                if not isinstance(meta, dict):
                    raise ValueError("sidecar is not an object")
                if not mp4.is_file():
                    raise FileNotFoundError("no video beside the sidecar")
                record = {
                    "id": jid,
                    "status": "succeeded",
                    "message": "Done",
                    "text": str(meta.get("text") or ""),
                    "voice": str(meta.get("voice") or ""),
                    "video_url": f"/output/videos/{mp4.name}",
                    "error": None,
                    "video_path": str(mp4),
                    "created": _as_time(meta.get("created"), now),
                    "updated": _as_time(meta.get("updated"), now),
                }
            except Exception:
                sidecar.unlink(missing_ok=True)
                removed += 1
                continue
            self._jobs[jid] = record
            adopted += 1
        for mp4 in self.video_dir.glob("*.mp4"):
            if mp4.stem not in self._jobs:
                try:
                    mp4.unlink(missing_ok=True)
                except OSError:
                    pass
                removed += 1
        return adopted, removed

    # -------------------------------------------------------------- machine
    async def _run(self, job_id: str) -> None:
        """One job end to end. The only writer of a job's status."""
        job = self._jobs.get(job_id)
        if job is None:
            return
        started = time.monotonic()
        audio = self.audio_dir / f"{job_id}.wav"

        async def update(**changes: Any) -> None:
            async with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    return
                current.update(changes)
                current["updated"] = time.time()

        try:
            await update(status="tts", message="Generating neural speech…")
            await tts.synthesize(job["text"], job["voice"], audio)
        except Exception as exc:
            await update(status="failed", error=f"Text-to-speech failed: {exc}")
            return

        try:
            prediction = await asyncio.to_thread(self.engine.submit, audio)
        except EngineUnavailable as exc:
            await update(status="failed", error=str(exc))
            return
        except Exception as exc:
            await update(status="failed",
                         error=f"Could not start the render: {exc}")
            return
        finally:
            # The WAV lived only to be handed to the engine; gone either way.
            audio.unlink(missing_ok=True)

        await update(status="rendering", message="Rendering the avatar…")
        while True:
            if time.monotonic() - started > MAX_RUN_SECONDS:
                await update(status="failed", error=(
                    "Render timed out. Try a shorter script or run it again."))
                return
            await asyncio.sleep(self.poll_seconds)
            try:
                prediction = await asyncio.to_thread(
                    self.engine.poll, prediction.id)
            except Exception as exc:
                await update(status="failed",
                             error=f"Lost the render job: {exc}")
                return
            if prediction.status == "succeeded":
                break
            if prediction.status == "failed":
                await update(status="failed", error=(
                    prediction.error or "The render failed without details"))
                return

        url = self.engine.output_url(prediction)
        if not url:
            await update(status="failed",
                         error="Render finished with no output video")
            return

        dest = self.video_dir / f"{job_id}.mp4"
        try:
            await asyncio.to_thread(self.engine.download, url, dest)
        except Exception as exc:
            await update(status="failed",
                         error=f"Could not fetch the video: {exc}")
            return
        await update(status="succeeded", message="Done",
                     video_url=f"/output/videos/{dest.name}",
                     video_path=str(dest))
        async with self._lock:
            current = self._jobs.get(job_id)
            if current is not None:
                self._persist(current)          # durable across restarts