# Compositing

`prompt_101/media_pipeline/compositor.py` — turn a rendered visual, the
narration and (optionally) the avatar into one segment MP4, then join the
segments into the lesson video.

```python
from prompt_101.media_pipeline import compose, stitch, build_lesson_video

# One segment: visual + narration, avatar overlaid bottom-right if given
segment = compose("slide.png", "narration.wav", "avatar.mp4")

# Join segments as-is
lesson = stitch([seg1, seg2, seg3], "lesson.mp4")

# Or the whole deliverable: title card + segments + closing card
lesson = build_lesson_video([seg1, seg2, seg3], title="Ohm's Law")
```

> This file previously documented a `freebuff.composite` module with
> `subtitle_text` and `normalize_audio` arguments and a `freebuff.ffmpeg`
> helper. None of that exists — the package was deleted and the work lives in
> `prompt_101/media_pipeline`. The signatures below are the real ones.

## compose(visual_path, audio_path=None, avatar_path=None, show_avatar=True, output_path=None)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `visual_path` | str/Path | required | Slide/diagram PNG |
| `audio_path` | str/Path | `None` | Narration WAV. `None` gets 3s of silence |
| `avatar_path` | str/Path | `None` | Talking-head MP4 to overlay |
| `show_avatar` | bool | `True` | Set `False` for a visual-only segment |
| `output_path` | str/Path | `None` | Defaults to a uuid name in `output/composed/` |

Returns the path to the composed MP4.

The avatar is scaled to 320px wide and overlaid 40px from the bottom-right
corner of the visual. The visual is a still, so it is looped and `-shortest`
ends the segment with the audio.

`orchestrator` does not call this signature directly: `wiring._adapt_compose`
reorders the arguments to the `compose(avatar_mp4, visual_png, audio_wav)`
the contract specifies.

## stitch(segments, output_path=None)

Concatenates segment MP4s. Every part is re-encoded to identical stream
parameters first — 1280x720, 25fps, yuv420p, 44100Hz mono AAC — because the
concat demuxer copies streams and silently drops anything that disagrees.
That cost one bug worth knowing about: a title card of a different size made
concat adopt *its* dimensions and discard the rest of the lesson, producing a
16-second file that played perfectly and contained almost nothing.

Anything that does not fit the target is letterboxed, never stretched.
Raises `ValueError` on an empty list; the normalised temporaries are always
cleaned up, including on failure.

## build_lesson_video(segment_paths, title="", output_path=None)

The single entry point for the deliverable. Prepends a title card, appends a
closing card, and stitches. Returns `""` for an empty segment list rather than
raising, because a lesson with no rendered media is a degraded lesson, not an
error. `orchestrator.lesson_video()` is the caller.

## ffmpeg

Every ffmpeg call goes through `get_ffmpeg_exe()`, which returns the static
binary shipped by `imageio-ffmpeg`. Never use a system ffmpeg — the team is on
three different OSes and the versions differ. Note that imageio-ffmpeg ships
**no ffprobe**, which is why `_has_audio()` parses ffmpeg's own stderr instead.

Commands are run through `_run_ffmpeg`, which enforces a 5-minute timeout and
raises `RuntimeError` carrying ffmpeg's stderr on failure.

## Configuration

`config.yaml` under `composite:` records the intended geometry:

| Key | Default | Description |
|-----|---------|-------------|
| `avatar_width` | `320` | Avatar overlay width (px) |
| `margin` | `40` | Margin from the bottom-right corner (px) |
| `pixel_format` | `yuv420p` | Output pixel format |

The output geometry itself is the `TARGET_W` / `TARGET_H` / `TARGET_FPS` /
`TARGET_RATE` / `TARGET_CH` constants at the top of `compositor.py`, which is
what `stitch()` normalises to.
