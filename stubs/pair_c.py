"""STUB for Pair C (Santosh + Hamza) — visuals/ and media/.

Real signatures, placeholder output. Santosh and Hamza: match these shapes.

Two behaviours here are NOT placeholders and must survive into the real code:
  - render() never crashes, including kind="none"
  - render_avatar() REFUSES audio longer than MAX_AVATAR_SECONDS
"""

import hashlib
import os
import wave

from shared.config import MAX_AVATAR_SECONDS, WORDS_PER_SECOND
from shared.models import VisualSpec

# A 1x1 transparent PNG, used only if matplotlib is unavailable. render()
# must never crash, so there is always something to fall back to.
_BLANK_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae4260"
    "82"
)

SUBJECT_VISUALS = {
    "mathematics": "equation",
    "physics": "diagram",
    "biology": "diagram",
    "history": "timeline",
    "programming": "code",
    "computer science": "code",
}


def render(spec: VisualSpec, out_dir: str) -> str:
    """MUST handle every kind. MUST never crash. MUST be drawn by code."""
    os.makedirs(out_dir, exist_ok=True)
    name = hashlib.sha1(f"{spec.kind}{spec.payload}".encode()).hexdigest()[:12]
    path = os.path.join(out_dir, f"visual_{name}.png")
    if os.path.exists(path):
        return path

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6, 3.4))
        ax.axis("off")
        ax.text(0.5, 0.68, spec.kind.upper(), ha="center", va="center",
                fontsize=22, fontweight="bold", color="#333333")
        ax.text(0.5, 0.44, (spec.caption or "")[:60], ha="center", va="center",
                fontsize=11, color="#555555")
        ax.text(0.5, 0.22, "[ Pair C stub — real visual pending ]",
                ha="center", va="center", fontsize=9, color="#999999")
        fig.savefig(path, dpi=110, bbox_inches="tight")
        plt.close(fig)
    except Exception:
        with open(path, "wb") as f:
            f.write(_BLANK_PNG)
    return path


def choose_visual(concept_name: str, subject: str) -> str:
    """Subject-aware visual routing. Worth marks on its own — document it."""
    return SUBJECT_VISUALS.get(subject.strip().lower(), "diagram")


def speak(text: str, lang: str) -> str:
    """MUST cache by hash of (text + lang). Stub writes silence of the right length."""
    os.makedirs("out/audio", exist_ok=True)
    key = hashlib.sha1(f"{text}{lang}".encode()).hexdigest()[:12]
    path = f"out/audio/{key}.wav"
    if os.path.exists(path):
        return path

    seconds = max(1.0, len(text.split()) / WORDS_PER_SECOND)
    frames = int(16000 * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * frames)
    return path


def audio_seconds(path: str) -> float:
    """Helper the orchestrator uses to check length before paying for a render."""
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


def render_avatar(audio_path: str, face_image: str) -> str:
    """MUST refuse audio over 60s. A 20-min render costs $5-8; 60s costs $0.40.

    The stub returns "" — meaning "no video yet". The orchestrator treats an
    empty path as 'fall back to the visual and the script', which is exactly
    what it should do on demo day if the avatar service is down.
    """
    seconds = audio_seconds(audio_path)
    if seconds > MAX_AVATAR_SECONDS:
        raise ValueError(
            f"refusing to render {seconds:.0f}s of audio; "
            f"cap is {MAX_AVATAR_SECONDS}s"
        )
    return ""


def compose(avatar_mp4: str, visual_png: str, audio_wav: str) -> str:
    """Overlay avatar on the visual and mux the audio. Stub: no video yet."""
    return avatar_mp4 or ""


def stitch(segment_paths: list[str]) -> str:
    """Concatenate finished segments into one lesson video."""
    return ""
