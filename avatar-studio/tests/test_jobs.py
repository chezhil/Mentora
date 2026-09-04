"""Executable contract for jobs.py's job state machine.

Pure policy: the engine is a scriptable fake, TTS is stubbed, and time is
injected — no torch, network, model weights, or real sleeps. Run from
avatar-studio:  python -m pytest
"""

from __future__ import annotations

import asyncio
import json
import threading
import time as real_time
from pathlib import Path

import pytest

import jobs
import tts as tts_module
from jobs import EngineUnavailable, JobManager

# ---------------------------------------------------------------- doubles
class FakeHandle:
    def __init__(self, prediction_id: str) -> None:
        self.id = prediction_id
        self.status = "processing"
        self.error: str | None = None


class FakeEngine:
    """Scriptable RenderEngine. submit() snapshots the audio into a scratch
    file (exactly what the local engine does); poll() — the "worker phase",
    which runs after the job machine has deleted the source WAV — reads only
    that snapshot, so the race guarantee is pinned: if the machine ever
    deleted the audio before submit() finished, the poll assertion fires."""

    def __init__(self, *, poll_statuses=("succeeded",),
                 pred_error: str | None = None,
                 output: str | None = "/rendered.mp4",
                 submit_error: Exception | None = None,
                 poll_error: Exception | None = None,
                 download_error: Exception | None = None) -> None:
        self._statuses = list(poll_statuses)
        self.pred_error = pred_error
        self.output = output
        self.submit_error = submit_error
        self.poll_error = poll_error
        self.download_error = download_error
        self.submit_release: threading.Event | None = None
        self.poll_release: threading.Event | None = None
        self.handle = FakeHandle("pred-1")
        self.submits = 0
        self.polls = 0
        self.scratch: Path | None = None      # set by the test that pins the race

    # ----------------------------------------------------- RenderEngine
    def available(self) -> bool:
        return True

    def submit(self, audio_path: Path, overrides: dict | None = None):
        self.submits += 1
        audio_bytes = Path(audio_path).read_bytes()   # source still exists
        if self.scratch is not None:
            (self.scratch / f"{self.handle.id}.wav").write_bytes(audio_bytes)
        if self.submit_release is not None:
            self.submit_release.wait(timeout=10)
        if self.submit_error is not None:
            raise self.submit_error
        self.handle.status = "processing"
        return self.handle

    def poll(self, prediction_id: str) -> FakeHandle:
        self.polls += 1
        if self.poll_release is not None:
            self.poll_release.wait(timeout=10)
        if self.poll_error is not None:
            raise self.poll_error
        # Worker phase: the machine deleted the source WAV by now, so the
        # snapshot taken inside submit() must be enough to finish the render.
        if self.scratch is not None:
            assert (self.scratch / f"{prediction_id}.wav").is_file()
        if self._statuses:
            self.handle.status = self._statuses.pop(0)
            self.handle.error = \
                self.pred_error if self.handle.status == "failed" else None
        return self.handle

    def output_url(self, prediction: FakeHandle) -> str | None:
        return self.output if prediction.status == "succeeded" else None

    def download(self, url: str, dest: Path) -> Path:
        if self.download_error is not None:
            raise self.download_error
        Path(dest).write_bytes(b"video")
        return Path(dest)


class FakeClock:
    """Stand-in for jobs' time module: time() and monotonic() are settable."""

    def __init__(self, t: float = 0.0) -> None:
        self._t = t
        self._m = 0.0

    def time(self) -> float:
        return self._t

    def monotonic(self) -> float:
        return self._m

    def advance(self, dt: float) -> None:
        self._t += dt
        self._m += dt


class JumpMonoClock:
    """monotonic() leaps far ahead on every call — for the MAX_RUN test."""

    def time(self) -> float:
        return real_time.time()

    def monotonic(self) -> float:
        self._m = getattr(self, "_m", 0.0) + jobs.MAX_RUN_SECONDS * 2
        return self._m


async def _fake_synth(_text: str, _voice: str, out_path: Path) -> Path:
    Path(out_path).write_bytes(b"fake-audio-content")
    return Path(out_path)


async def _broken_synth(_text: str, _voice: str, _out_path: Path) -> Path:
    raise RuntimeError("tts boom")


# -------------------------------------------------------------- fixtures
@pytest.fixture(autouse=True)
def fake_tts(monkeypatch):
    """No network: TTS is a stub writing a dummy WAV."""
    monkeypatch.setattr(tts_module, "synthesize", _fake_synth)


@pytest.fixture
def make_manager(tmp_path):
    """JobManager wired to a fake engine, fast polls, throwaway dirs."""

    def build(engine: FakeEngine, poll_seconds: float = 0.0) -> JobManager:
        return JobManager(engine, audio_dir=tmp_path / "audio",
                          video_dir=tmp_path / "videos",
                          poll_seconds=poll_seconds)

    return build


def _run(main_coro):
    return asyncio.run(main_coro)


async def _run_to_terminal(manager: JobManager, job_id: str) -> dict:
    for _ in range(20_000):
        snap = await manager.get(job_id)
        if snap is not None and snap["status"] in ("succeeded", "failed"):
            return snap
        await asyncio.sleep(0)
    raise AssertionError(f"job {job_id} never reached a terminal state")


# ---------------------------------------------------------------- success
def test_success_writes_video_and_sidecar(make_manager, tmp_path):
    engine = FakeEngine()

    async def main():
        m = make_manager(engine)
        jid = m.create("Hello there", "en-US-AriaNeural")
        snap = await _run_to_terminal(m, jid)
        assert snap["status"] == "succeeded"
        assert snap["error"] is None
        assert snap["video_url"] == f"/output/videos/{jid}.mp4"
        assert snap["text"] == "Hello there"
        assert snap["voice"] == "en-US-AriaNeural"
        assert engine.submits == 1 and engine.polls >= 1
        assert not (m.audio_dir / f"{jid}.wav").exists()   # source deleted
        assert (m.video_dir / f"{jid}.mp4").is_file()
        meta = json.loads((m.video_dir / f"{jid}.json").read_text(encoding="utf-8"))
        assert meta["text"] == "Hello there"
        assert meta["voice"] == "en-US-AriaNeural"
        assert [h["id"] for h in await m.history()] == [jid]

    _run(main())


def test_audio_snapshotted_inside_submit(make_manager, tmp_path):
    """The local-engine race guarantee: submit() copies the WAV before the
    machine deletes it, so poll() (the worker phase) only needs the copy."""
    engine = FakeEngine()
    engine.scratch = tmp_path / "scratch"
    engine.scratch.mkdir()

    async def main():
        m = make_manager(engine)
        jid = m.create("Race check", "en-US-AriaNeural")
        snap = await _run_to_terminal(m, jid)
        assert snap["status"] == "succeeded"
        assert not (m.audio_dir / f"{jid}.wav").exists()
        assert engine.polls >= 1        # poll() asserted the copy existed

    _run(main())


def test_status_transitions_visible(make_manager):
    """A user polling /api/jobs/<id> sees tts → rendering → succeeded."""
    engine = FakeEngine()
    engine.poll_release = threading.Event()          # park during rendering
    seen = []

    async def main():
        m = make_manager(engine)
        jid = m.create("Hi", "en-US-AriaNeural")
        while True:
            snap = await m.get(jid)
            if snap:
                seen.append(snap["status"])
            if engine.polls >= 1:                     # poll() entered: rendering
                break
            await asyncio.sleep(0)
        engine.poll_release.set()
        snap = await _run_to_terminal(m, jid)
        assert snap["status"] == "succeeded"
        assert "rendering" in seen     # visible to a poller before completion

    _run(main())


# ------------------------------------------------------- terminal failures
FAILURE_CASES = [
    # (synth, engine kwargs, expected error fragment)
    ("broken", {}, "Text-to-speech failed: tts boom"),
    ("ok", {"submit_error": EngineUnavailable("no engine today")},
     "no engine today"),
    ("ok", {"submit_error": RuntimeError("boom")},
     "Could not start the render: boom"),
    ("ok", {"poll_error": RuntimeError("poll boom")},
     "Lost the render job: poll boom"),
    ("ok", {"poll_statuses": ("failed",), "pred_error": "engine said no"},
     "engine said no"),
    ("ok", {"poll_statuses": ("failed",)},
     "The render failed without details"),
    ("ok", {"output": None}, "Render finished with no output video"),
    ("ok", {"download_error": RuntimeError("dl boom")},
     "Could not fetch the video: dl boom"),
]


@pytest.mark.parametrize("synth,engine_kwargs,fragment", FAILURE_CASES,
                         ids=["tts_failure", "engine_unavailable",
                              "submit_crashed", "poll_crashed",
                              "engine_failure", "engine_failure_no_detail",
                              "no_output", "download_failed"])
def test_terminal_failures(make_manager, tmp_path, monkeypatch,
                           synth, engine_kwargs, fragment):
    engine = FakeEngine(**engine_kwargs)
    if synth == "broken":
        monkeypatch.setattr(tts_module, "synthesize", _broken_synth)

    async def main():
        m = make_manager(engine)
        jid = m.create("Say something", "en-US-AriaNeural")
        snap = await _run_to_terminal(m, jid)
        assert snap["status"] == "failed"
        assert fragment in snap["error"]
        # no half-written artifacts: no video, no sidecar, no leftover audio
        assert list(m.video_dir.glob(f"{jid}.*")) == []
        assert not (m.audio_dir / f"{jid}.wav").exists()

    _run(main())


def test_tts_failure_never_touches_engine(make_manager, monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(tts_module, "synthesize", _broken_synth)

    async def main():
        m = make_manager(engine)
        jid = m.create("X", "en-US-AriaNeural")
        await _run_to_terminal(m, jid)
        assert engine.submits == 0 and engine.polls == 0

    _run(main())


# ------------------------------------------------------------- MAX_RUN
def test_max_run_timeout(make_manager, monkeypatch):
    """A render that never finishes is declared dead after MAX_RUN_SECONDS."""
    engine = FakeEngine(poll_statuses=())              # never advances
    monkeypatch.setattr(jobs, "time", JumpMonoClock())

    async def main():
        m = make_manager(engine)
        jid = m.create("Long render", "en-US-AriaNeural")
        snap = await _run_to_terminal(m, jid)
        assert snap["status"] == "failed"
        assert "timed out" in snap["error"]

    _run(main())


# ---------------------------------------------------- TTL eviction (pair)
def test_ttl_eviction_deletes_record_and_files_together(make_manager, monkeypatch):
    clock = FakeClock(t=1_000.0)
    monkeypatch.setattr(jobs, "time", clock)

    async def main():
        m = make_manager(FakeEngine())
        jid = m.create("Ephemeral", "en-US-AriaNeural")
        assert (await _run_to_terminal(m, jid))["status"] == "succeeded"
        assert (m.video_dir / f"{jid}.mp4").is_file()
        assert (m.video_dir / f"{jid}.json").is_file()
        assert [h["id"] for h in await m.history()] == [jid]
        clock.advance(jobs.JOB_TTL_SECONDS + 1)
        assert await m.prune() == 1
        assert await m.get(jid) is None
        assert list(m.video_dir.glob(f"{jid}.*")) == []   # mp4 AND json gone
        assert await m.history() == []

    _run(main())


def test_lazy_eviction_on_read(make_manager, monkeypatch):
    clock = FakeClock(t=5_000.0)
    monkeypatch.setattr(jobs, "time", clock)

    async def main():
        m = make_manager(FakeEngine())
        jid = m.create("Gone soon", "en-US-AriaNeural")
        assert (await _run_to_terminal(m, jid))["status"] == "succeeded"
        clock.advance(jobs.JOB_TTL_SECONDS + 1)
        assert await m.get(jid) is None                  # stale read evicts
        assert list(m.video_dir.glob(f"{jid}.*")) == []

    _run(main())


def test_history_newest_first(make_manager, monkeypatch):
    clock = FakeClock(t=100.0)
    monkeypatch.setattr(jobs, "time", clock)

    async def main():
        # two sequential jobs share one engine: script one success each
        m = make_manager(FakeEngine(poll_statuses=("succeeded", "succeeded")))
        first = m.create("First", "en-US-AriaNeural")
        await _run_to_terminal(m, first)          # updated at t=100
        clock.advance(50.0)
        second = m.create("Second", "en-US-AriaNeural")
        await _run_to_terminal(m, second)         # updated at t=150
        assert [h["id"] for h in await m.history()] == [second, first]

    _run(main())


# -------------------------------------------------------- startup adoption
def _write_pair(dir: Path, jid: str, text: str, t: float) -> None:
    (dir / f"{jid}.mp4").write_bytes(b"video")
    (dir / f"{jid}.json").write_text(
        json.dumps({"id": jid, "text": text, "voice": "v",
                    "created": t, "updated": t}), encoding="utf-8")


ADOPT_CASES = [
    # (name, file kind, adopted, removed)
    ("paired render adopted", "mp4+json", 1, 0),
    ("orphan mp4 removed", "mp4", 0, 1),
    ("mp4-less sidecar removed", "json", 0, 1),
    ("unreadable sidecar removed", "garbage", 0, 1),
]


@pytest.mark.parametrize("name,kind,adopted,removed", ADOPT_CASES,
                         ids=[c[0] for c in ADOPT_CASES])
def test_adoption(make_manager, tmp_path, name, kind, adopted, removed):
    m = make_manager(FakeEngine())
    jid = "a1"
    if kind == "mp4+json":
        # fresh timestamps: an adopted record must survive lazy eviction
        _write_pair(m.video_dir, jid, "Alpha text", real_time.time())
    elif kind == "mp4":
        (m.video_dir / f"{jid}.mp4").write_bytes(b"video")
    elif kind == "json":
        (m.video_dir / f"{jid}.json").write_text("{}")
    else:
        (m.video_dir / f"{jid}.json").write_text("{ not json")

    got_adopted, got_removed = m._adopt()

    async def check():
        assert (got_adopted, got_removed) == (adopted, removed)
        if adopted:
            snap = await m.get(jid)
            assert snap and snap["status"] == "succeeded"
            assert snap["text"] == "Alpha text"
            assert sorted(p.name for p in m.video_dir.iterdir()) == \
                [f"{jid}.json", f"{jid}.mp4"]
            assert [h["id"] for h in await m.history()] == [jid]
        else:
            assert list(m.video_dir.iterdir()) == []

    _run(check())


def test_adoption_history_newest_first(make_manager, tmp_path):
    m = make_manager(FakeEngine())
    _write_pair(m.video_dir, "older", "Old", 100.0)
    _write_pair(m.video_dir, "newer", "New", 300.0)
    m._adopt()

    async def check():
        hist = await m.history()
        assert [h["id"] for h in hist] == ["newer", "older"]
        assert [h["text"] for h in hist] == ["New", "Old"]

    _run(check())


def test_start_adopts_and_runs_sweeper(make_manager, tmp_path):
    m = make_manager(FakeEngine())
    _write_pair(m.video_dir, "a1", "Kept", 1.0)
    (m.video_dir / "stray.mp4").write_bytes(b"x")

    async def main():
        m.start()                      # the real startup path
        assert "a1" in m._jobs
        assert not (m.video_dir / "stray.mp4").exists()
        assert (await m.history())[0]["id"] == "a1"
        m.stop()

    _run(main())