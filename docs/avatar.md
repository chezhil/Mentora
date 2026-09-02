# Avatar Module

Audio-driven face animation via Replicate, with cost controls and caching.

## Quick Start

```python
from freebuff.avatar import render_avatar

# Animate a teacher photo with audio
mp4_path = render_avatar("teacher.wav", "teacher.jpg")
```

## The 60-Second Guard

```python
from freebuff.avatar.render_avatar import render_avatar

render_avatar("3_minute_lesson.wav", "teacher.jpg")
# Raises ValueError: Audio is 180.0s -- must be <= 60s
```

**Why this exists:**

| Duration | Cost | Quality |
|----------|------|---------|
| 60 seconds | ~$0.40 | Stable face, good lip sync |
| 20 minutes | ~$5-8 | Face drifts, mouth artifacts |

Two serious problems with long renders:

1. **Money.** One careless call spends the entire project budget.
2. **Quality.** Models drift on long clips — the face stops looking
   like the same person and mouth artifacts accumulate.

**Solution:** Split long audio before rendering:

```python
from freebuff.voice.speak import split_audio
from freebuff.avatar import render_avatar

chunks = split_audio("long_lesson.wav", max_seconds=60)
for chunk in chunks:
    render_avatar(chunk, "teacher.jpg")
```

## How It Works

### render_avatar(audio_path, photo_path, backend_name)

1. Checks cache — same audio+photo never re-rendered
2. Validates audio duration ≤ 60 seconds
3. Dispatches to the configured avatar backend
4. Caches the result MP4
5. Returns path to cached MP4

**Caching:** SHA-256 hash of `audio_path:photo_path` determines the
cache key. Same inputs = same MP4, no second API call.

### Backend Interface

All avatar backends implement the same interface:

```python
class AvatarBackend(ABC):
    @abstractmethod
    def animate(self, photo_path, audio_path) -> str:
        """Animate photo with audio. Returns path to MP4."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name."""
        ...
```

### SadTalker (Default)

Model: `cjwbw/sadtalker` on Replicate
Cost: ~$0.01/second of audio
Quality: Proven (180K+ runs), uses GFPGAN face enhancement

```yaml
# config.yaml
avatar:
  model: cjwbw/sadtalker
  enhancer: gfpgan
```

Requires `REPLICATE_API_TOKEN` environment variable.

## Swapping Models

To use a different avatar model:

1. Create `freebuff/avatar/models/my_model.py`:
```python
from freebuff.avatar.models.base import AvatarBackend

class MyModelBackend(AvatarBackend):
    @property
    def name(self):
        return "MyModel"

    def animate(self, photo_path, audio_path):
        # Your API call here
        return output_path
```

2. Register in `render_avatar.py`:
```python
def _get_backend(name=None):
    if "mymodel" in model.lower():
        from freebuff.avatar.models.my_model import MyModelBackend
        return MyModelBackend()
```

3. Set in config:
```yaml
avatar:
  model: mymodel
```

## Photo Requirements

The source photo matters more than the model:

- **Front-facing** — face clearly visible
- **Evenly lit** — no harsh shadows
- **High resolution** — at least 512x512
- **Neutral expression** — slight smile is fine

A bad photo makes every model look bad.

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `cjwbw/sadtalker` | Replicate model identifier |
| `max_duration_seconds` | `60` | Hard limit on audio length |
| `output_dir` | `cache/avatar` | Cache directory for MP4s |
| `enhancer` | `gfpgan` | Face enhancement (`gfpgan` or none) |
