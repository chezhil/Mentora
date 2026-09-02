# Freebuff Desktop — Media Pipeline

AI teaching video generation: voice synthesis, avatar animation,
and video composition.

## Quick Start

```python
from freebuff.voice import speak
from freebuff.composite import compose, stitch

# 1. Synthesize narration
wav = speak("Ohm's Law states V equals I times R", lang="en")

# 2. Compose segment (visual + audio)
compose("slide.png", wav, "segment.mp4",
        subtitle_text="V = I x R")

# 3. Stitch into final video
stitch(["segment.mp4"], "lesson.mp4")
```

## Architecture

```
freebuff/
├── voice/                  # Text-to-speech
│   ├── speak.py            # speak(), to_ssml(), split_audio()
│   └── piper_backend.py    # Piper TTS engine
├── avatar/                 # Face animation
│   ├── render_avatar.py    # render_avatar() with 60s guard
│   └── models/
│       ├── base.py         # Abstract AvatarBackend
│       └── sadtalker.py    # Replicate SadTalker
├── composite/              # Video assembly
│   ├── compose.py          # compose() — visual + audio + avatar
│   └── stitch.py           # stitch() — join segments
├── cache.py                # SHA-256 caching (voice + avatar)
├── config.py               # YAML config + env overrides
├── ffmpeg.py               # Shared ffmpeg binary accessor
└── pipeline.py             # render_lesson() orchestrator
```

**Data flow:**

```
Text ──► speak() ──► WAV ──► compose() ──► MP4 ──► stitch() ──► Lesson
              │                  ▲
              ▼                  │
         split_audio()     Visual PNG
              │                  ▲
              ▼                  │
        render_avatar() ──► MP4 ─┘
```

## Configuration

All settings in `config.yaml`:

```yaml
voice:
  engine: piper              # "piper" (dev) or "cloud_tts" (demo)
  output_dir: cache/voice
  piper_voices:
    en: en_US-lessac-medium
    hi: hi_IN-swara-medium

avatar:
  model: cjwbw/sadtalker     # Replicate model
  max_duration_seconds: 60   # Hard limit
  output_dir: cache/avatar
  enhancer: gfpgan

composite:
  avatar_width: 320          # pixels
  margin: 40                 # pixels from corner
  pixel_format: yuv420p
```

Override via environment variables:

```bash
export FREEBUFF_VOICE_ENGINE=cloud_tts
export FREEBUFF_AVATAR_MODEL=cjwbw/sadtalker
```

## Modules

### Voice (`freebuff.voice`)

```python
from freebuff.voice import speak

# Basic synthesis with caching
wav = speak("Hello world", lang="en")

# With SSML pauses for teaching cadence
wav = speak("Hello world. How are you?", lang="en", use_ssml=True)

# Split long audio for avatar rendering
from freebuff.voice.speak import split_audio
chunks = split_audio("long.wav", max_seconds=60)
```

See [docs/voice.md](docs/voice.md) for full documentation.

### Avatar (`freebuff.avatar`)

```python
from freebuff.avatar import render_avatar

# Animate photo with audio (≤60 seconds)
mp4 = render_avatar("teacher.wav", "teacher.jpg")
```

See [docs/avatar.md](docs/avatar.md) for full documentation.

### Compositing (`freebuff.composite`)

```python
from freebuff.composite import compose, stitch

# Compose segment with subtitle and volume normalization
compose("slide.png", "audio.wav", "segment.mp4",
        subtitle_text="V = I x R",
        normalize_audio=True)

# Stitch segments into final video
stitch(["seg1.mp4", "seg2.mp4"], "lesson.mp4")
```

See [docs/composite.md](docs/composite.md) for full documentation.

## Dependencies

```
pip install -e ".[dev]"
```

Core: matplotlib, numpy, networkx, Pygments, piper-tts, replicate,
imageio-ffmpeg, Pillow, PyYAML, requests

Dev: pytest, pytest-cov, ruff

Optional: google-cloud-texttospeech (for final demo TTS)

## Testing

```bash
py -m pytest tests/ -v          # Run all 36 tests
py -m ruff check freebuff/      # Lint check
```

## How Caching Works

Every generated file (WAV, MP4) is cached by SHA-256 hash:

- **Voice:** `SHA256(text:lang)` → WAV
- **Avatar:** `SHA256(audio_path:photo_path)` → MP4

Same inputs never re-generate. This saves money (Replicate API calls)
and time (Piper synthesis on every test run).
