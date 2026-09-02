"""Compose a segment MP4 from visual, audio, and optional avatar."""

from __future__ import annotations
import logging
import subprocess
from pathlib import Path
from freebuff.ffmpeg import get_ffmpeg
from freebuff.config import get_config

logger = logging.getLogger(__name__)


def compose(visual_png, audio_wav, output_mp4, avatar_mp4=None,
            subtitle_text=None, normalize_audio=True):
    visual_png = Path(visual_png).resolve()
    audio_wav = Path(audio_wav).resolve()
    output_mp4 = Path(output_mp4).resolve()
    if not visual_png.exists():
        raise FileNotFoundError(f"Visual not found: {visual_png}")
    if not audio_wav.exists():
        raise FileNotFoundError(f"Audio not found: {audio_wav}")
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    cfg = get_config().get("composite", {})
    aw = cfg.get("avatar_width", 320)
    margin = cfg.get("margin", 40)
    pf = cfg.get("pixel_format", "yuv420p")

    # Subtitle overlay via ffmpeg drawtext
    sub = ""
    if subtitle_text:
        esc = subtitle_text
        esc = esc.replace(chr(92), chr(92)*2)  # backslash
        esc = esc.replace(":", chr(92)+":")  # colon
        sq = chr(39)  # single quote
        esc = esc.replace(sq, chr(92)+sq)
        sub = (
            ",drawtext=text=" + sq + esc + sq +
            ":fontsize=28:fontcolor=white:borderw=2:bordercolor=black"
            ":x=(w-text_w)/2:y=h-th-40:box=1:boxcolor=black@0.5:boxborderw=8"
        )

    # Volume normalization filter (ITU-R BS.1770)
    loudnorm = ""
    if normalize_audio:
        loudnorm = ",loudnorm=I=-16:TP=-1.5:LRA=11"

    if avatar_mp4 is not None:
        avatar_mp4 = Path(avatar_mp4).resolve()
        if not avatar_mp4.exists():
            raise FileNotFoundError(f"Avatar not found: {avatar_mp4}")
        filt = f"[1:v]scale={aw}:-1[av];[0:v][av]overlay=W-w-{margin}:H-h-{margin}{sub}"
        cmd = [get_ffmpeg(), "-y", "-loop", "1", "-i", str(visual_png),
               "-i", str(avatar_mp4), "-i", str(audio_wav),
               "-filter_complex", filt, "-map", "2:a", "-map", "0:v",
               "-c:v", "libx264", "-tune", "stillimage", "-shortest",
               "-pix_fmt", pf, "-movflags", "+faststart"]
        if loudnorm:
            cmd += ["-af", "anull" + loudnorm]
        cmd.append(str(output_mp4))
    else:
        cmd = [get_ffmpeg(), "-y", "-loop", "1", "-i", str(visual_png),
               "-i", str(audio_wav), "-c:v", "libx264", "-tune", "stillimage",
               "-c:a", "aac", "-b:a", "192k", "-shortest", "-pix_fmt", pf,
               "-movflags", "+faststart"]
        if sub:
            cmd += ["-vf", sub[1:]]  # strip leading comma
        if loudnorm:
            cmd += ["-af", loudnorm[1:]]  # strip leading comma
        cmd.append(str(output_mp4))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-300:]}")
    return str(output_mp4)