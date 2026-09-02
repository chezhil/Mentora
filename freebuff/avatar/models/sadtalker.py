"""SadTalker backend — audio-driven face animation via Replicate.

Model: cjwbw/sadtalker
Cost: ~$0.01/second of audio
Quality: Proven (180K+ runs), uses GFPGAN face enhancement by default.

This is the default avatar backend for development and demo.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import requests

from freebuff.avatar.models.base import AvatarBackend
from freebuff.config import get_avatar_config

logger = logging.getLogger(__name__)


class SadTalkerBackend(AvatarBackend):
    """Audio-driven face animation using SadTalker on Replicate."""

    @property
    def name(self) -> str:
        return "SadTalker"

    def animate(self, photo_path: str | Path, audio_path: str | Path) -> str:
        """Run SadTalker on Replicate to animate the photo with audio.

        Args:
            photo_path: Path to a face photo.
            audio_path: Path to a WAV file.

        Returns:
            Path to the generated MP4 file.
        """
        photo_path = Path(photo_path)
        audio_path = Path(audio_path)

        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        cfg = get_avatar_config()
        enhancer = cfg.get("enhancer", "gfpgan")

        logger.info("SadTalker: animating photo=%s audio=%s", photo_path, audio_path)

        try:
            import replicate
        except ImportError:
            raise RuntimeError(
                "replicate is not installed. Run: pip install replicate"
            )

        try:
            # Replicate expects file objects for uploads
            with open(photo_path, "rb") as photo_f, open(audio_path, "rb") as audio_f:
                output = replicate.run(
                    "cjwbw/sadtalker",
                    input={
                        "source_image": photo_f,
                        "driven_audio": audio_f,
                        "enhancer": enhancer,
                    },
                )

            # Output is a URL or FileOutput — download it
            video_url = str(output)
            logger.info("SadTalker: downloading result from %s", video_url)

            resp = requests.get(video_url, timeout=120)
            resp.raise_for_status()

            # Write to a temp file and return its path
            # Caller (render_avatar) will move it to the cache
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(resp.content)
            tmp.close()

            logger.info(
                "SadTalker: produced %d bytes", len(resp.content)
            )
            return tmp.name

        except Exception as e:
            raise RuntimeError(f"SadTalker animation failed: {e}") from e
