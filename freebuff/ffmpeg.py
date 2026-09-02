"""Shared ffmpeg binary accessor."""

from __future__ import annotations
import imageio_ffmpeg

_ffmpeg: str | None = None


def get_ffmpeg() -> str:
    global _ffmpeg
    if _ffmpeg is None:
        _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    return _ffmpeg
