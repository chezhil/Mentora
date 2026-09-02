# Media Pipeline — Visual Rendering, Voice, Avatar, Video Assembly

**Pair C: Santosh + Hamza**

A complete media pipeline for AI teaching video generation. This system takes lesson content and produces segmented MP4 videos with subject-aware visuals, voice narration, and optional avatar overlay.

---

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   choose_   │    │   render()  │    │   speak()   │    │  compose()  │
│   visual()  │───>│   (PNG)     │    │   (WAV)     │───>│   (MP4)     │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │                  │
       v                  v                  v                  v
  Rules table        matplotlib         Piper/TTS        ffmpeg stitch
  + keywords         networkx           Google Cloud
```

### The 4 Components

| Component | Input | Output | File |
|-----------|-------|--------|------|
| **Visual** | Concept + Subject | PNG image | `renderers/*.py` |
| **Voice** | Text + Language | WAV audio | `voice.py` |
| **Avatar** | WAV + Photo | MP4 video | `avatar.py` |
| **Compositor** | PNG + WAV + MP4 | Final MP4 | `compositor.py` |

---

## choose_visual() — The 15-Mark Feature

This is the **MARKED FUNCTION** — 15 marks for "AI Teaching Video Generation" depend on this decision.

### How It Works

The function uses a **deterministic rules table** (not AI/LLM) to map concepts to visual types:

```python
choose_visual("Ohm's Law", "physics")       # -> "diagram"
choose_visual("quadratic functions", "maths") # -> "graph"
choose_visual("French Revolution", "history") # -> "timeline"
```

### Why Rules Table Over AI

1. **Explainable** — We can show exactly *why* a concept gets a visual type
2. **Deterministic** — Same input always produces same output
3. **Fast** — O(1) keyword matching, no API calls

### Subject Mappings

| Subject | Keywords → Visual Type |
|---------|------------------------|
| Physics | circuit, ohm → `diagram`; wave, motion → `graph` |
| Maths | equation, theorem → `equation`; function, plot → `graph` |
| Biology | cell, organ → `diagram`; cycle, pathway → `concept_map` |
| History | revolution, war → `timeline`; cause, effect → `concept_map` |
| Programming | code, function → `code`; algorithm, flow → `concept_map` |

See `docs/choose_visual.md` for complete documentation.

---

## Setup

### Install Dependencies

```bash
cd prompt_101
pip install -r requirements.txt
```

### Required (Always Works)

- **matplotlib** — Visual rendering
- **networkx** — Diagram/concept map rendering
- **Pillow** — Image processing
- **imageio-ffmpeg** — Cross-platform ffmpeg

### Optional (API Keys Needed)

| Service | Purpose | Cost | How to Get |
|---------|---------|------|------------|
| **Piper TTS** | Local voice generation | Free | Download from [github.com/rhasspy/piper](https://github.com/rhasspy/piper) |
| **Google Cloud TTS** | High-quality voice | Free tier: 1M chars/month | Create service account at [console.cloud.google.com](https://console.cloud.google.com) |
| **Replicate** | Avatar video generation | ~$0.40/minute | Get token at [replicate.com](https://replicate.com) |

### Environment Variables

```bash
# TTS Provider (default: piper)
export TTS_PROVIDER=piper  # or "google"

# Piper (local, no key needed)
export PIPER_BIN=/path/to/piper
export PIPER_MODEL_DIR=/path/to/models

# Google Cloud TTS
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Replicate (for avatar)
export REPLICATE_API_TOKEN=r8_xxxxx
```

---

## Usage

### Quick Start

```python
from media_pipeline import render, speak, compose, stitch, choose_visual

# 1. Choose visual type
kind = choose_visual("Ohm's Law", "physics")  # -> "diagram"

# 2. Render visual
visual = render(kind, "Ohm's Law V=IR", subject="physics")

# 3. Generate voice
audio = speak("Ohm's law states that voltage equals current times resistance.", lang="en")

# 4. Compose segment (without avatar)
segment = compose(visual, audio)

# 5. Stitch multiple segments
final = stitch([segment1, segment2, segment3])
```

### Run Demo

```bash
cd prompt_101
python demo.py
```

### Run Tests

```bash
cd prompt_101
python test_all.py
```

---

## Visual Renderers

All visuals are drawn with code (matplotlib, networkx) — never AI image models.

| Kind | Renderer | Use Case |
|------|----------|----------|
| `equation` | matplotlib | Mathematical formulas, equations |
| `graph` | matplotlib | Function plots, data visualization |
| `diagram` | networkx/matplotlib | Labeled diagrams, flowcharts |
| `timeline` | matplotlib | Historical events, sequences |
| `code` | matplotlib | Syntax-highlighted code |
| `concept_map` | networkx/matplotlib | Concept relationships |
| `none` | matplotlib | Title cards, placeholders |

All renderers produce **1280x720 PNGs** with content filling 60%+ of the canvas.

---

## What's Tested vs Placeholder

### Tested (Works Locally)

- [x] `render()` — All 7 visual kinds produce valid PNGs
- [x] `choose_visual()` — Rules table returns correct kinds
- [x] `speak()` — Hash caching works (placeholder audio when Piper not installed)
- [x] `compose()` — Visual + audio → MP4 segment
- [x] `stitch()` — Multiple segments → final video
- [x] `render_avatar()` — 60-second limit enforced
- [x] `PipelineConfig` — Dataclass with defaults

### Placeholder (Needs API Keys)

- [ ] `speak()` with Piper — Needs Piper binary + models
- [ ] `speak()` with Google Cloud — Needs service account JSON
- [ ] `render_avatar()` with LivePortrait — Needs Replicate API token
- [ ] Avatar overlay in `compose()` — Needs real avatar MP4

---

## File Structure

```
prompt_101/
├── README.md                      # This file
├── requirements.txt               # Python dependencies
├── demo.py                        # Quick demo script
├── test_all.py                    # Full test suite
└── media_pipeline/
    ├── __init__.py                # Public API exports
    ├── config.py                  # Configuration + PipelineConfig dataclass
    ├── utils.py                   # Hashing, caching, audio utilities
    ├── visual.py                  # render() + choose_visual()
    ├── voice.py                   # speak() with Piper/Google TTS
    ├── avatar.py                  # render_avatar() via LivePortrait
    ├── compositor.py              # compose() + stitch()
    ├── renderers/
    │   ├── __init__.py            # Lazy-loaded renderer registry
    │   ├── equation.py            # Equation/formula renderer
    │   ├── graph.py               # Graph/plot renderer
    │   ├── diagram.py             # Diagram renderer
    │   ├── timeline.py            # Timeline renderer
    │   ├── code.py                # Code renderer with syntax highlighting
    │   ├── concept_map.py         # Concept map renderer
    │   └── none.py                # Title card/placeholder renderer
    ├── docs/
    │   └── choose_visual.md       # Documentation for the 15-mark feature
    └── output/                    # Generated files (gitignored)
        ├── visuals/               # PNG images
        ├── tts/                   # WAV audio files
        ├── avatar/                # MP4 avatar videos
        └── composed/              # Final MP4 segments
```

---

## API Reference

### `render(kind, content, subject="", data=None)`

Render a visual explanation as PNG.

- `kind`: One of: equation, graph, diagram, timeline, code, concept_map, none
- `content`: The concept/equation/code to visualize
- `subject`: Subject area for context
- `data`: Optional dict with renderer-specific data

### `choose_visual(concept_name, subject)`

Determine appropriate visual type for a concept.

- Returns: One of the 7 visual kinds

### `speak(text, lang="en")`

Generate speech audio with hash caching.

- `text`: Text to speak
- `lang`: Language code (en, hi, ta, kn, te, bn, mr)
- Returns: Path to WAV file

### `render_avatar(audio_path, photo_path)`

Create talking head video via LivePortrait.

- `audio_path`: Path to WAV file (max 60 seconds)
- `photo_path`: Path to teacher photo
- Returns: Path to MP4 file

### `compose(visual_path, audio_path=None, avatar_path=None)`

Compose visual + audio into segment MP4.

- Returns: Path to MP4 file

### `stitch(segments)`

Concatenate multiple segments into final video.

- `segments`: List of MP4 paths
- Returns: Path to final MP4

---

## License

Internal project code — not for distribution.
