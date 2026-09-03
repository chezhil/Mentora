"""Voice synthesis service with hash-based caching.

Supports two providers:
- Piper: Local CPU-based TTS for development (free, unlimited, Indian language voices)
- edge-tts: free neural voices, no key, for everything Piper cannot speak

Both go behind the same speak() function. Provider is controlled by config.
"""
import os
import subprocess
from pathlib import Path
from typing import Optional

from .config import (
    TTS_OUTPUT_DIR,
    TTS_PROVIDER,
    PIPER_BIN,
    PIPER_MODEL_DIR,
)
from .utils import get_cached_path


# ── Language to Voice Mapping ──

# Piper voice models (model_name, sample_rate)
PIPER_VOICES = {
    # Verified against huggingface.co/rhasspy/piper-voices on 2 Sep.
    # The previous names (swara, dhivya, jessica, shaurya, tanmayee) do not
    # exist, so every Indian language silently produced a silent placeholder.
    "en": ("en_US-lessac-medium", 22050),
    "hi": ("hi_IN-pratham-medium", 22050),
    "te": ("te_IN-maya-medium", 22050),
    # Piper has NO voice for Tamil, Kannada or Bengali. Those languages have
    # to go through edge-tts, which is free and needs no key.
}

def _provider_order(lang: str) -> list[str]:
    """Which backends to try, best first.

    Piper is local and needs no network, so it leads wherever it has a voice
    installed (en, hi, te). Edge is free, needs no key, and covers every
    language we offer, so it takes the rest and backs up the others.

    There is no third option. Google Cloud TTS was wired in but needs a paid
    account we do not have, and selecting Tamil used to raise ImportError in
    the middle of a lesson. Dead paths that can only fail are worse than no
    path at all.
    """
    if TTS_PROVIDER != "auto":
        return [TTS_PROVIDER, "edge", "piper"]
    return (["piper", "edge"] if lang in PIPER_VOICES else ["edge"])


def speak(text: str, lang: str = "en", output_path: Optional[str] = None) -> str:
    """Generate speech audio from text with hash-based caching.
    
    Same text + language = same hash = same file, never regenerated.
    
    Args:
        text: The text to speak
        lang: Language code (en, hi, ta, kn, te, bn, mr)
        output_path: Optional custom output path; if None, uses cache
    
    Returns:
        Path to the generated WAV file
    """
    if not text or not text.strip():
        raise ValueError("Cannot speak empty text")
    
    # Check cache first
    cache_path = get_cached_path(
        Path(TTS_OUTPUT_DIR), "tts", ".wav", text, lang
    )
    
    if cache_path.exists():
        return str(cache_path)
    
    # Try providers in order and never raise: a lesson must keep going even if
    # every backend is unavailable. Selecting Tamil used to raise ImportError
    # here, which ended the lesson rather than degrading it.
    backends = {"piper": _speak_piper, "edge": _speak_edge}
    for name in _provider_order(lang):
        fn = backends.get(name)
        if fn is None:
            continue
        try:
            path = fn(text, lang, cache_path)
            if path and Path(path).exists() and Path(path).stat().st_size > 1024:
                return str(path)
        except Exception as exc:
            print(f"[voice] {name} failed for {lang}: {exc}. Trying the next backend.")

    print(f"[voice] no TTS backend produced audio for {lang}; using a silent "
          f"placeholder so the lesson can continue.")
    return str(_generate_placeholder_wav(text, cache_path))


# ── Edge TTS ─────────────────────────────────────────────────────────────────
#
# Piper has no voices for Tamil or Kannada — I checked rhasspy/piper-voices
# directly, those language directories do not exist. The routing sent them to
# Google Cloud TTS, which needed a paid account we do not have, so selecting
# Tamil raised ImportError in the middle of a lesson. That path is gone.
#
# Microsoft Edge's TTS is free, needs no key or account, and has neural voices
# for every language we offer. It is used for anything Piper cannot speak, and
# as the fallback whenever a local Piper voice is missing.
#
# The only cost is that it needs a network connection, where Piper does not.
# That is why Piper still wins for the languages it covers.

EDGE_VOICES = {
    "en": "en-IN-NeerjaNeural",       # Indian English suits the audience
    "hi": "hi-IN-SwaraNeural",
    "ta": "ta-IN-PallaviNeural",
    "kn": "kn-IN-SapnaNeural",
    "te": "te-IN-ShrutiNeural",
    "bn": "bn-IN-TanishaaNeural",
    "mr": "mr-IN-AarohiNeural",
    "hinglish": "hi-IN-SwaraNeural",
}


def _speak_edge(text: str, lang: str, output_path: Path) -> Path:
    """Free neural TTS via Edge. Returns a WAV so the rest of the pipeline
    (duration checks, ffmpeg mux) is unchanged."""
    import asyncio
    import subprocess

    import edge_tts
    import imageio_ffmpeg

    voice = EDGE_VOICES.get(lang, EDGE_VOICES["en"])
    mp3_path = output_path.with_suffix(".edge.mp3")

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(mp3_path))

    asyncio.run(_run())

    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
         "-i", str(mp3_path), "-ar", "22050", "-ac", "1", str(output_path)],
        check=True, capture_output=True,
    )
    mp3_path.unlink(missing_ok=True)
    return output_path


# ── Piper Implementation ──

def _speak_piper(text: str, lang: str, output_path: Path) -> Path:
    """Generate speech using Piper TTS (local, free).
    
    Uses the piper-tts Python API (PiperVoice.load + synthesize)
    instead of the subprocess CLI, which is more portable.
    """
    import wave as wave_mod
    
    voice_name, sample_rate = PIPER_VOICES.get(lang, PIPER_VOICES["en"])
    
    model_path = Path(PIPER_MODEL_DIR) / f"{voice_name}.onnx"
    if not model_path.exists():
        alt_path = Path(PIPER_MODEL_DIR) / voice_name / f"{voice_name}.onnx"
        if alt_path.exists():
            model_path = alt_path
        else:
            print(f"[voice] Warning: Piper model {voice_name} not found at {model_path}. Using placeholder.")
            return _generate_placeholder_wav(text, output_path)
    
    # Method 1: Python API (preferred)
    try:
        from piper import PiperVoice
        
        voice = PiperVoice.load(str(model_path))
        audio_chunks = list(voice.synthesize(text))
        
        with wave_mod.open(str(output_path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(voice.config.sample_rate)
            for chunk in audio_chunks:
                wav_file.writeframes(chunk.audio_int16_bytes)
        
        if output_path.exists() and output_path.stat().st_size > 44:
            return output_path
        raise RuntimeError("Piper Python API produced empty output")
    except ImportError:
        print("[voice] Warning: piper Python package not installed.")
    except Exception as e:
        print(f"[voice] Piper Python API error: {e}")
    
    # Method 2: CLI subprocess (fallback)
    import subprocess
    piper_path = Path(PIPER_BIN)
    if piper_path.exists():
        try:
            cmd = [str(piper_path), "--model", str(model_path),
                   "--output_file", str(output_path)]
            result = subprocess.run(
                cmd, input=text.encode("utf-8"),
                capture_output=True, check=True, timeout=60
            )
            if output_path.exists():
                return output_path
        except Exception as e:
            print(f"[voice] Piper CLI error: {e}")
    
    print(f"[voice] All Piper methods failed for {lang}. Using placeholder.")
    return _generate_placeholder_wav(text, output_path)



# ── Placeholder Generator ──

def _generate_placeholder_wav(text: str, output_path: Path) -> Path:
    """Generate a silent WAV file as placeholder when TTS is unavailable.
    
    Creates a valid WAV file with silence proportional to text length.
    This ensures the pipeline can still test without a working TTS.
    """
    import struct
    import wave
    
    # Estimate duration: ~5 words per second, ~5 chars per word
    word_count = len(text.split()) if text else 1
    duration_seconds = max(1.0, word_count / 5.0)
    
    sample_rate = 22050
    num_samples = int(duration_seconds * sample_rate)
    
    # Write WAV file
    with wave.open(str(output_path), "w") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        # Write silence (zeros)
        wav_file.writeframes(b"\x00\x00" * num_samples)
    
    return output_path
