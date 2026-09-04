# Avatar Studio

A standalone website that turns **text into a video of a photo-realistic
human avatar speaking it** — with real lip sync. **Everything is free and
runs on your own machine**: no API keys, no per-render cost, no cloud.

## How it works

```
your text
   │  edge-tts (free neural TTS, no key)
   ▼
16 kHz speech WAV
   │  Wav2Lip on-device — animates the photo's mouth + natural head drift
   ▼
talking-head MP4, served back to the page
```

- **Speech**: [edge-tts](https://github.com/rany2/edge-tts) — free neural
  voices, many languages, no API key.
- **Avatar**: [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) run locally in
  CPU PyTorch — takes one front-facing photo plus the audio and animates a
  talking head with real lip sync. Free, offline, unlimited.
- **Face**: `assets/avatar.jpg` — a real, front-facing human photo is
  required (a drawn avatar will not register with the face detector); swap
  the file to change who the presenter is.

## Run it

Standalone project — it only needs Python 3.10+ and `requirements.txt`.

```bash
cd avatar-studio
pip install -r requirements.txt     # inside any virtualenv of your choosing
python setup_models.py              # one-time ~436 MB model download
python app.py                       # → http://localhost:8000
```

For CPU-only machines install the CPU wheels for torch first:
`pip install torch --index-url https://download.pytorch.org/whl/cpu`.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/render` | `{text, voice}` → `{job_id}` |
| `GET` | `/api/jobs/{job_id}` | Poll job state → `succeeded` gives `video_url` |
| `GET` | `/api/voices` | Voices the composer offers |
| `GET` | `/api/history` | Finished renders, newest first (the gallery on page load) |
| `GET` | `/api/health` | Engine name/readiness, setup hint if something's missing |

## Where things live

Each concern has one owner, so a change lands in one file:

| File | Owns |
|---|---|
| `app.py` | Routes + wiring: picks the engine (`AVATAR_ENGINE` env, default `wav2lip`), constructs the `JobManager`, serves static files. No job logic. |
| `jobs.py` | The job state machine (submit → poll → download → evict) and *all* job state: records, TTL eviction, the files a job produces, and persistence. Engine-agnostic. |
| `wav2lip_engine.py` | The default render engine — `Wav2LipEngine` implements the `RenderEngine` protocol from `jobs.py`. All face detection, blending, head-motion and ffmpeg knowledge lives here. Swap the photo's behaviour in this file. |
| `avatar.py` | The *optional paid* engine, `ReplicateEngine` (SadTalker on Replicate, needs `AVATAR_ENGINE=replicate` + token). Same protocol, injected the same way. |
| `tts.py` | Voice list + text→WAV. All edge-tts knowledge lives here. |
| `setup_models.py` | One-time downloader for the local model weights into `models/`. |
| `vendor/wav2lip/` | Wav2Lip's own model code (unchanged upstream except two marked patches) — see its `README.md` for provenance and license. |
| `static/` | The page (HTML/CSS/JS) — no Python. |

**Lifecycle rules** (all in `jobs.py`, tweak the constants there):

- Terminal jobs are evicted — record dropped, rendered video deleted —
  `JOB_TTL_SECONDS` (2 h) after their last state change.
- Finished renders are durable: on success the job's metadata is written
  to a JSON sidecar beside the video (`output/videos/<id>.json`), and at
  startup the server adopts those back into memory — deleting `.mp4`s
  that have no sidecar and sidecars whose video is gone — so records and
  files never drift apart across restarts. The gallery survives refreshes
  and restarts; history is served from `/api/history`.
- A job still running after `MAX_RUN_SECONDS` (20 min) is failed.
- The transient speech WAV is deleted the moment the engine accepts it
  (or the job fails), so `output/audio` never accumulates.

## Tests

The job state machine's lifecycle contract is pinned by a pytest suite
(fake engine + stubbed TTS + injected clocks — no torch, network, or model
weights needed):

```bash
python -m pytest          # 22 tests, pure policy
python -m mypy            # type check jobs.py + tests
```

## Tuning

- **Voice** — add any voice id to `VOICES` in `tts.py`
  (`edge-tts --list-voices` shows them all).
- **Head motion** — subtlety knobs (`ROT_DEG`, `SHIFT_*`, `SCALE_A`) are in
  `wav2lip_engine.py`, tuned to read natural rather than visible.
- **Script length** — `MAX_TEXT` in `app.py` (mirrored by the page).

## Optional paid upgrade

Want the more cinematic SadTalker head motion? Copy `.env.example` to `.env`,
set `AVATAR_ENGINE=replicate`, and add a `REPLICATE_API_TOKEN` (≈ $0.05 per
render, cloud). The free engine stays the default.
