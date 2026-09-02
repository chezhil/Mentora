"""Piper TTS backend -- local, free, unlimited."""

from __future__ import annotations
import wave
from pathlib import Path
from freebuff.config import get_config


def synthesize_piper(text, lang, output):
    voices = get_config().get("voice", {}).get("piper_voices", {})
    if lang not in voices:
        raise ValueError(f"No Piper voice for '{lang}'. Available: {list(voices)}")

    from piper import PiperVoice
    model = Path(f"voices/{voices[lang]}.onnx")
    voice = PiperVoice.load(str(model))

    audio = b""
    for chunk in voice.synthesize(text):
        audio += chunk.audio_int16_bytes

    with wave.open(str(output), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(voice.config.sample_rate)
        wf.writeframes(audio)
