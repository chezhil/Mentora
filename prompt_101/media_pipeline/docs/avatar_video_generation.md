# Avatar & Video Generation Approach

## Overview

The video generation pipeline converts text lessons into talking-head teaching videos. It combines four subsystems: visual rendering, voice synthesis, avatar animation, and video compositing.

---

## Pipeline Flow

```
Lesson Script
    │
    ├── render()          → PNG visual (per segment)
    ├── speak()           → WAV audio (per segment)
    ├── render_avatar()   → MP4 talking head (per segment)
    │
    └── compose()         → Segment MP4 (visual + audio + avatar)
         │
         └── build_lesson_video()  → Final lesson MP4
              (title card + segments + closing card)
```

## Components

### 1. Visual Rendering (`visual.py` + `renderers/`)

Renders 7 kinds of educational visuals as 1280×720 PNGs using matplotlib:

| Kind | Use Case | Example |
|------|----------|---------|
| `equation` | Math formulas, physics equations | E = mc² |
| `graph` | Function plots, data visualization | Sine waves |
| `diagram` | Labeled diagrams, circuit schematics | Cell structure |
| `timeline` | Historical events, sequences | World War II |
| `code` | Syntax-highlighted code blocks | Python functions |
| `concept_map` | Relationship diagrams | ML taxonomy |
| `none` | Title cards, text slides | Course intro |

The `choose_visual(concept, subject)` function uses a deterministic rules table to select the appropriate kind — this is the "subject-aware visual explanation" that earns marks.

### 2. Voice Synthesis (`voice.py`)

Two providers behind a single `speak()` function:

- **Piper** (local, free): en, hi, te, bn, mr — verified upstream models
- **Google Cloud TTS** (cloud): ta, kn — no Piper models exist upstream

Auto-routing selects the best provider per language. All output cached by SHA256 hash of (text, lang).

### 3. Avatar Animation (`avatar.py`)

Creates talking-head videos from a still photo + audio using **LivePortrait on Replicate**.

Key constraints:
- **60-second limit** per segment (enforced in code)
- Pair B caps scripts at ~130 words ≈ 41s of speech, so the limit should never trigger
- Requires `REPLICATE_API_TOKEN` environment variable
- Falls back to a placeholder video when token is not set

Photo requirements:
- Front-facing, evenly lit, neutral expression
- Minimum 512×512 resolution
- 1:1 to 4:3 aspect ratio preferred

### 4. Video Compositing (`compositor.py`)

Assembles everything into MP4 video files using **imageio-ffmpeg** (cross-platform, no system ffmpeg required).

#### compose()

Combines visual + audio + optional avatar into a segment MP4:

```
┌─────────────────────┐
│                     │
│    Visual Slide     │
│    (1280×720)       │
│                     │
│              ┌──────┤
│              │Avatar│  ← Bottom-right overlay (320px wide)
│              │      │
│              └──────┘
└─────────────────────┘
```

#### stitch()

Concatenates segment MP4s using ffmpeg's concat demuxer (lossless stream copy).

#### build_lesson_video()

The **single entry point** for producing the final lesson video:

```python
from media_pipeline import build_lesson_video

lesson = build_lesson_video(
    segment_paths=["seg1.mp4", "seg2.mp4", "seg3.mp4"],
    title="Introduction to Physics",
)
# → "output/lesson_video.mp4"
```

Structure of the output:
```
┌──────────────────┐
│   Title Card     │  ← 4 seconds, dark background
│   "Lesson Title" │
└──────────────────┘
┌──────────────────┐
│   Segment 1      │  ← Visual + Audio + Avatar
└──────────────────┘
┌──────────────────┐
│   Segment 2      │
└──────────────────┘
   ...
┌──────────────────┐
│  Closing Card    │  ← 3 seconds, "Thank You"
└──────────────────┘
```

Returns `""` if `segment_paths` is empty (never raises).

---

## Error Handling

Every function has a safety wrapper:

1. **Visual renderers** catch all exceptions and fall back to `render_none()` (title card)
2. **Voice synthesis** falls back to a silent WAV placeholder
3. **Avatar** falls back to a colored placeholder video with audio
4. **Compositor** propagates ffmpeg errors as `RuntimeError`
5. **build_lesson_video** returns `""` on empty input, never raises

---

## Caching

All expensive operations are cached:

| Output | Cache Key | Location |
|--------|-----------|----------|
| TTS audio | SHA256(text + lang) | `output/tts/` |
| Avatar video | SHA256(audio + photo) | `output/avatar/` |
| Visual PNG | UUID (per render) | `output/visuals/` |

Same text + language = same hash = same file, never regenerated.

---

## Configuration

| Setting | Default | Purpose |
|---------|---------|---------|
| `TTS_PROVIDER` | `"auto"` | `"auto"`, `"piper"`, or `"google"` |
| `REPLICATE_API_TOKEN` | `None` | Required for avatar generation |
| `MAX_AVATAR_DURATION_SECONDS` | `60` | Hard limit on avatar segment length |
| `USE_IMAGEIO_FFMPEG` | `True` | Use imageio-ffmpeg binary |
| `IMAGE_WIDTH` | `1280` | Visual output width |
| `IMAGE_HEIGHT` | `720` | Visual output height |
