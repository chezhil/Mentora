"""Abstract base class for avatar animation backends.

All avatar backends implement the same interface, making it trivial
to swap models (SadTalker → LivePortrait → Hallo3) without changing
the calling code in render_avatar().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class AvatarBackend(ABC):
    """Abstract interface for audio-driven face animation."""

    @abstractmethod
    def animate(self, photo_path: str | Path, audio_path: str | Path) -> str:
        """Animate a face photo with audio to produce a talking-head video.

        Args:
            photo_path: Path to a front-facing teacher photo (JPEG/PNG).
            audio_path: Path to a WAV file (must be ≤60s).

        Returns:
            Path to the generated MP4 video file.

        Raises:
            RuntimeError: If the animation fails.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this backend (e.g., 'SadTalker')."""
        ...
