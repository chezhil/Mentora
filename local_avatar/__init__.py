"""Local talking-head avatar. No Replicate, no per-render cost.

Pair C's avatar path calls Replicate (~$0.40 per 60s render). This runs
Wav2Lip on this machine instead: free, offline, and cross-platform, because it
is plain PyTorch plus OpenCV.

It exposes the CONTRACT signature, so wiring can prefer it over the paid path:

    render_avatar(audio_path: str, face_image: str) -> str

available() reports whether the weights are present, so a teammate who has not
downloaded them falls back to Pair C's placeholder instead of crashing.
"""

from .wav2lip import available, render_avatar

__all__ = ["available", "render_avatar"]
