"""Animate a face photo with audio to produce a talking-head MP4."""

from __future__ import annotations
import logging
import shutil
from pathlib import Path
from freebuff.cache import cache_path, get_cached
from freebuff.voice.speak import audio_duration
from freebuff.config import get_config

logger = logging.getLogger(__name__)
MAX_DURATION_SECONDS = 60


def render_avatar(audio_path, photo_path, backend_name=None):
    audio_path = Path(audio_path).resolve()
    photo_path = Path(photo_path).resolve()
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio not found: {audio_path}")
    if not photo_path.exists():
        raise FileNotFoundError(f"Photo not found: {photo_path}")

    cached = get_cached("avatar", ".mp4", str(audio_path), str(photo_path))
    if cached:
        return cached

    duration = audio_duration(audio_path)
    if duration > MAX_DURATION_SECONDS:
        raise ValueError(f"Audio is {duration:.1f}s -- must be <= {MAX_DURATION_SECONDS}s")

    backend = _get_backend(backend_name)
    tmp = backend.animate(photo_path, audio_path)
    dest = cache_path("avatar", ".mp4", str(audio_path), str(photo_path))
    shutil.move(tmp, str(dest))
    return str(dest)


def _get_backend(name=None):
    cfg = get_config().get("avatar", {})
    model = name or cfg.get("model", "cjwbw/sadtalker")
    if "sadtalker" in model.lower():
        from freebuff.avatar.models.sadtalker import SadTalkerBackend
        return SadTalkerBackend()
    raise ValueError(f"Unknown avatar model: {model}")
