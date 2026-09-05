# Compositing Module

Combine visuals, audio, and avatar into video segments, then stitch
them into a final lesson video.

## Quick Start

```python
from prompt_101.media_pipeline.compositor import compose, stitch

# Visual + narration. Returns the path it wrote.
segment = compose("slide.png", "narration.wav")

# Visual + narration + a talking-head overlay in the bottom-right corner
segment = compose("slide.png", "narration.wav", "avatar.mp4")

# Choose the output path rather than taking the generated one
compose("slide.png", "narration.wav", output_path="segment.mp4")

# Stitch the segments into the lesson
stitch([seg1, seg2, seg3])
```

Both functions **return the path they wrote**, and both invent one under the
output directory when `output_path` is not given — so the return value is the
thing to pass on, not the argument.

## compose(visual_path, audio_path=None, avatar_path=None, ...)

Combines a static visual image with narration audio into a video
segment. Optionally overlays a talking-head avatar and subtitle text.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `visual_path` | str | required | Slide/diagram PNG image |
| `audio_path` | str | `None` | Narration audio. Omitted, three seconds of silence stands in, so a segment still renders |
| `avatar_path` | str | `None` | Talking-head MP4, scaled to 320px wide and overlaid 40px from the bottom-right corner |
| `show_avatar` | bool | `True` | Set `False` to ignore `avatar_path` and compose the visual alone |
| `output_path` | str | `None` | Where to write. Omitted, a name is generated under the compose output directory |

### How It Works

1. Validates input files exist
2. Builds ffmpeg command with:
   - `-loop 1` — turns still image into video stream
   - `-c:v libx264 -tune stillimage` — efficient encoding for static content
   - `-pix_fmt yuv420p` — browser/Streamlit compatible
   - `-movflags +faststart` — web-optimized metadata

**Without avatar:**
```
ffmpeg -loop 1 -i slide.png -i audio.wav \
  -c:v libx264 -tune stillimage -c:a aac -b:a 192k \
  -shortest -pix_fmt yuv420p segment.mp4
```

**With avatar overlay:**
```
ffmpeg -loop 1 -i slide.png -i avatar.mp4 -i audio.wav \
  -filter_complex "[1:v]scale=320:-1[av];[0:v][av]overlay=W-w-40:H-h-40" \
  -map 2:a -map 0:v -c:v libx264 -shortest segment.mp4
```

## Subtitle Overlay

When `subtitle_text` is provided, adds an ffmpeg `drawtext` filter:

```
drawtext=text='Your text':fontsize=28:fontcolor=white:
  borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-th-40:
  box=1:boxcolor=black@0.5:boxborderw=8
```

- **Centered** at bottom of frame with 40px margin
- **White text** with black border for readability
- **Semi-transparent black box** background
- **Escapes** colons, backslashes, and single quotes for ffmpeg safety

```python
compose("slide.png", "audio.wav", "out.mp4",
        subtitle_text="Ohm's Law: V = I x R")
```

## Volume Normalization (loudnorm)

When `normalize_audio=True` (default), applies the ITU-R BS.1770
standard loudness filter:

```
loudnorm=I=-16:TP=-1.5:LRA=11
```

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `I` | -16 | Target integrated loudness (LUFS) |
| `TP` | -1.5 | True peak limit (dBTP) |
| `LRA` | 11 | Loudness range (LU) |

**Why this matters:** Without normalization, different segments have
different volume levels, causing jarring transitions when stitched.
The loudnorm filter ensures all segments play at consistent loudness.

```python
# With normalization (default) — consistent volume
compose("slide.png", "audio.wav", "out.mp4", normalize_audio=True)

# Without normalization — raw audio levels
compose("slide.png", "audio.wav", "out.mp4", normalize_audio=False)
```

## stitch(segment_paths, output_path)

Concatenates segment MP4s into a single final video using ffmpeg's
concat demuxer with **stream copy** — instant and lossless.

```python
stitch(["seg_000.mp4", "seg_001.mp4", "seg_002.mp4"], "lesson.mp4")
```

**Why stream copy works:** Every segment was encoded the same way
by `compose()` (same codec, same pixel format, same settings). This
means concatenation requires no re-encoding — just binary concatenation.

**Single segment:** If only one segment is provided, it's copied
directly without ffmpeg.

**Error handling:** Raises `FileNotFoundError` if any segment is
missing. Raises `RuntimeError` if ffmpeg fails.

## Using imageio-ffmpeg

All ffmpeg calls use `imageio-ffmpeg`, which ships a static ffmpeg
binary for each platform. This avoids version mismatches across
macOS, Windows, and Linux.

```python
from prompt_101.media_pipeline.compositor import get_ffmpeg_exe

ffmpeg_path = get_ffmpeg_exe()  # the binary imageio-ffmpeg ships
```

Note that `imageio-ffmpeg` bundles **ffmpeg only, not ffprobe** — anything
needing to read a file's duration or dimensions has to parse `ffmpeg -i`
stderr instead.

Never use a system-installed ffmpeg — the team is on three different
OSes and system ffmpeg versions will differ.

## Configuration

`config.yaml` carries a `composite:` block:

| Key | Default | Description |
|-----|---------|-------------|
| `avatar_width` | `320` | Avatar overlay width (px) |
| `margin` | `40` | Margin from bottom-right corner (px) |
| `pixel_format` | `yuv420p` | Output pixel format |

**These are not read.** The compositor hardcodes the same three values in the
filter it builds (`scale=320:-1`, `overlay=W-w-40:H-h-40`, `-pix_fmt
yuv420p`), so editing the config changes nothing — the constants in
`compositor.py` are what to edit.
