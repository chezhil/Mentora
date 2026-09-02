# Compositing Module

Combine visuals, audio, and avatar into video segments, then stitch
them into a final lesson video.

## Quick Start

```python
from freebuff.composite import compose, stitch

# Compose a segment: visual + audio + optional avatar
compose("slide.png", "narration.wav", "segment.mp4")

# Compose with subtitle and volume normalization
compose("slide.png", "narration.wav", "segment.mp4",
        subtitle_text="V = I x R", normalize_audio=True)

# Stitch segments into final video
stitch(["seg1.mp4", "seg2.mp4", "seg3.mp4"], "lesson.mp4")
```

## compose(visual_png, audio_wav, output_mp4, ...)

Combines a static visual image with narration audio into a video
segment. Optionally overlays a talking-head avatar and subtitle text.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `visual_png` | str/Path | required | Slide/diagram PNG image |
| `audio_wav` | str/Path | required | Narration WAV file |
| `output_mp4` | str/Path | required | Output video path |
| `avatar_mp4` | str/Path | None | Talking-head overlay |
| `subtitle_text` | str | None | Text overlay at bottom |
| `normalize_audio` | bool | True | Apply loudnorm filter |

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
from freebuff.ffmpeg import get_ffmpeg

ffmpeg_path = get_ffmpeg()  # Returns path to bundled ffmpeg binary
```

Never use a system-installed ffmpeg — the team is on three different
OSes and system ffmpeg versions will differ.

## Configuration

All composite settings in `config.yaml` under `composite:`:

| Key | Default | Description |
|-----|---------|-------------|
| `avatar_width` | `320` | Avatar overlay width (px) |
| `margin` | `40` | Margin from bottom-right corner (px) |
| `pixel_format` | `yuv420p` | Output pixel format |
