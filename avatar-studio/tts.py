"""Text-to-speech: edge-tts (free, neural, no keys) -> 16 kHz mono WAV.

SadTalker expects clean 16 kHz audio. edge-tts streams MP3, so we pass the
bytes through ffmpeg (bundled by imageio-ffmpeg) once.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import edge_tts
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# A curated set of good neural voices. Add any edge-tts voice id here.
VOICES: list[dict] = [
    {"id": "en-US-AriaNeural", "label": "Aria", "gender": "Female", "language": "English (US)"},
    {"id": "en-US-GuyNeural", "label": "Guy", "gender": "Male", "language": "English (US)"},
    {"id": "en-US-JennyNeural", "label": "Jenny", "gender": "Female", "language": "English (US)"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia", "gender": "Female", "language": "English (UK)"},
    {"id": "en-GB-RyanNeural", "label": "Ryan", "gender": "Male", "language": "English (UK)"},
    {"id": "en-IN-NeerjaNeural", "label": "Neerja", "gender": "Female", "language": "English (India)"},
    {"id": "en-IN-PrabhatNeural", "label": "Prabhat", "gender": "Male", "language": "English (India)"},
    {"id": "hi-IN-SwaraNeural", "label": "Swara", "gender": "Female", "language": "Hindi"},
    {"id": "hi-IN-MadhurNeural", "label": "Madhur", "gender": "Male", "language": "Hindi"},
]

DEFAULT_VOICE = "en-US-AriaNeural"


def list_voices() -> list[dict]:
    return VOICES


async def synthesize(text: str, voice: str, out_path: Path) -> Path:
    """Write neural speech to `out_path` as 16 kHz mono WAV. Returns the path."""
    mp3 = out_path.with_suffix(".mp3")
    await edge_tts.Communicate(text, voice).save(str(mp3))
    try:
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error",
             "-i", str(mp3), "-ar", "16000", "-ac", "1", str(out_path)],
            check=True, capture_output=True,
        )
    finally:
        mp3.unlink(missing_ok=True)
    return out_path