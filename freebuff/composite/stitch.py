"""Concatenate segment MP4s into a final video."""

from __future__ import annotations
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from freebuff.ffmpeg import get_ffmpeg

logger = logging.getLogger(__name__)


def stitch(segment_paths, output_path):
    if not segment_paths:
        raise ValueError("Need at least 1 segment")
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    segments = []
    for sp in segment_paths:
        p = Path(sp).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Segment not found: {p}")
        segments.append(p)

    if len(segments) == 1:
        shutil.copy2(str(segments[0]), str(output_path))
        return str(output_path)

    lf = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    try:
        for seg in segments:
            lf.write("file '" + str(seg) + "'\n")
        lf.close()
        cmd = [get_ffmpeg(), "-y", "-f", "concat", "-safe", "0",
               "-i", lf.name, "-c", "copy", "-movflags", "+faststart",
               str(output_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-300:]}")
        return str(output_path)
    finally:
        Path(lf.name).unlink(missing_ok=True)
