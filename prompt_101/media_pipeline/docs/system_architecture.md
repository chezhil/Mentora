# System Architecture — Media Pipeline

## Overview

The media pipeline is the core of the AI teaching video generation system. It converts structured lesson scripts into composed video segments and final lesson videos.

---

## Module Structure

```
prompt_101/media_pipeline/
├── __init__.py          # Public API: render, speak, compose, stitch, build_lesson_video
├── config.py            # All configuration (env vars, directories, dataclass)
├── visual.py            # Visual rendering dispatcher + choose_visual() decision logic
├── voice.py             # TTS synthesis (Piper + Google Cloud) with auto-routing
├── avatar.py            # Talking-head video via LivePortrait on Replicate
├── compositor.py        # Video assembly: compose, stitch, build_lesson_video
├── utils.py             # Hashing, caching, audio utilities
├── renderers/           # 7 visual kind renderers (matplotlib/networkx)
│   ├── __init__.py      # Renderer registry, Indic font registration
│   ├── equation.py
│   ├── graph.py
│   ├── diagram.py
│   ├── timeline.py
│   ├── code.py
│   ├── concept_map.py
│   └── none.py
├── docs/                # Documentation
│   ├── choose_visual.md
│   ├── voice_implementation.md
│   ├── multilingual_implementation.md
│   ├── avatar_video_generation.md
│   └── system_architecture.md
├── assets/fonts/        # Noto Sans Indic fonts (5 scripts + Latin)
└── piper_models/        # Piper ONNX voice models (en, hi, te)
```

## Data Flow

```
                     Lesson Script (JSON/text)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │  render() │   │  speak() │   │ render_  │
        │  visual   │   │  voice   │   │ avatar() │
        └────┬─────┘   └────┬─────┘   └────┬─────┘
             │              │              │
             ▼              ▼              ▼
         PNG slide      WAV audio      MP4 avatar
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                    ┌──────────────┐
                    │   compose()  │  → Segment MP4
                    └──────┬───────┘
                           │  (repeat for each segment)
                           ▼
                ┌──────────────────────┐
                │ build_lesson_video() │  → Final Lesson MP4
                │ (title + segments    │
                │  + closing card)     │
                └──────────────────────┘
```

## Module Responsibilities

### config.py
- Central configuration via env vars and dataclass
- Directory setup (output/visuals, output/tts, output/avatar, output/composed)
- PipelineConfig dataclass for testability

### visual.py
- `render(kind, content, subject, data)` — Dispatches to kind-specific renderers
- `choose_visual(concept, subject)` — Deterministic rules table for visual selection
- Safety wrapper: never crashes, always returns a path

### voice.py
- `speak(text, lang)` — Unified TTS with hash-based caching
- `_resolve_provider(lang)` — Auto-selects Piper or Google per language
- Piper: Python API (`PiperVoice.load`) with CLI fallback
- Google Cloud TTS: `google-cloud-texttospeech` library

### avatar.py
- `render_avatar(audio, photo)` — LivePortrait lip-sync via Replicate
- 60-second hard limit enforced in code
- Placeholder fallback when API token not set
- Photo validation (resolution, aspect ratio)

### compositor.py
- `compose(visual, audio, avatar)` — Assembles one segment MP4
- `stitch(segments)` — Concatenates segments via ffmpeg concat
- `build_lesson_video(segments, title)` — Full lesson with title/closing cards
- All video ops use imageio-ffmpeg (no system ffmpeg required)

### renderers/
- 7 renderers, one per visual kind
- Lazy-loaded registry (missing deps don't break the package)
- Indic font support via rcParams fallback mechanism
- All render at 1280×720, 100 DPI

### utils.py
- `hash_content(text, extra)` — SHA256-based cache keys
- `get_cached_path(...)` — Resolves cache file paths
- `get_audio_duration(path)` — WAV duration via wave module
- `create_silent_audio(duration, dir)` — Silent WAV generation

---

## External Dependencies

| Dependency | Purpose | Required? |
|------------|---------|-----------|
| matplotlib | Visual rendering | Yes |
| numpy | Graph/data operations | Yes |
| networkx | Diagram/concept maps | Yes |
| Pillow | Image resize/verify | Yes |
| piper-tts | Local TTS | Yes (for Piper voices) |
| imageio-ffmpeg | Video encoding | Yes |
| google-cloud-texttospeech | Cloud TTS | Only for ta/kn |
| replicate | Avatar generation | Only for avatar |
| Pygments | Syntax highlighting | Optional |

---

## Output Structure

```
output/
├── visuals/          # PNG renders (per kind)
├── tts/              # WAV audio (cached by hash)
├── avatar/           # MP4 talking heads (cached by hash)
└── composed/         # Segment MP4s + final lesson video
    ├── segment_*.mp4
    ├── card_*.mp4    # Temporary title/closing cards
    └── lesson_video.mp4
```

---

## Error Resilience

The pipeline is designed to never crash the caller:

1. **Visual**: Falls back to `render_none()` (title card) on any renderer error
2. **Voice**: Falls back to silent WAV placeholder on TTS failure
3. **Avatar**: Falls back to colored placeholder video on API failure
4. **Compositor**: Returns `""` on empty input; raises `RuntimeError` on ffmpeg failure
5. **Cache**: Missing cache → regenerate; corrupt cache → overwrite

This means the pipeline always produces output, even with missing credentials or broken dependencies.
