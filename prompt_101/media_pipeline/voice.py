"""Voice synthesis, with hash-based caching.

Two backends, both free, no key anywhere:

    edge-tts   Microsoft's neural voices. Leads everywhere, because the
               quality gap is not subtle — Piper's medium models are clearly
               synthetic, and a teacher who sounds like a train announcement
               is a teacher nobody listens to. Needs a network connection.
    piper      Local, offline, and instant. Covers en, hi and te. Used when
               edge is unreachable, which is the case the demo has to survive.

That order is the opposite of what it used to be. Piper led because it works
offline; the result was that the three most-used languages had the worst
narration in the app while five better voices sat unused.

Every voice comes from shared/languages.py, so adding a language is one edit
in one file.

MENTORA_VOICE=male picks the male voice, TTS_PROVIDER=piper forces offline.
"""
import os
import subprocess
from pathlib import Path
from typing import Optional

from shared import languages

from .config import (
    TTS_OUTPUT_DIR,
    TTS_PROVIDER,
    PIPER_BIN,
    PIPER_MODEL_DIR,
)
from .utils import get_cached_path


# Delivery. A teacher explaining something new speaks a little below
# conversational pace; the default rate reads as rushed against a diagram the
# student is still taking in. -8% is enough to hear and not enough to drag.
SPEECH_RATE = os.getenv("MENTORA_SPEECH_RATE", "-8%")
SPEECH_PITCH = os.getenv("MENTORA_SPEECH_PITCH", "+0Hz")


def _gender() -> str:
    return "male" if os.getenv("MENTORA_VOICE", "female").lower() == "male" else "female"


def _provider_order(lang: str) -> list[str]:
    """Which backends to try, best first.

    Edge leads on quality and covers every language we offer. Piper backs it
    up for the three languages it has voices for, so a lesson still narrates
    with the network unplugged.
    """
    if TTS_PROVIDER != "auto":
        return [TTS_PROVIDER, "edge", "piper"]
    return ["edge", "piper"] if languages.get(lang).piper else ["edge"]


def speak(text: str, lang: str = "en", output_path: Optional[str] = None) -> str:
    """Generate speech audio from text with hash-based caching.
    
    Same text + language = same hash = same file, never regenerated.
    
    Args:
        text: The text to speak
        lang: Language code — any key in shared/languages.py
        output_path: Optional custom output path; if None, uses cache
    
    Returns:
        Path to the generated WAV file
    """
    if not text or not text.strip():
        raise ValueError("Cannot speak empty text")
    
    # Check cache first
    # The gender is part of the key: without it, switching voice replays the
    # previous one out of cache and looks like the setting does nothing.
    cache_path = get_cached_path(
        Path(TTS_OUTPUT_DIR), "tts", ".wav", text, f"{lang}:{_gender()}"
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
# Microsoft Edge's neural voices. Free, no key, no account, and a voice for
# every language in shared/languages.py — including Tamil, Kannada, Malayalam
# and Gujarati, which Piper has no model for at all.
#
# The only cost is a network connection. That is the whole reason Piper is
# still here as the fallback.

def _speak_edge(text: str, lang: str, output_path: Path) -> Path:
    """Free neural TTS via Edge. Returns a WAV so the rest of the pipeline
    (duration checks, ffmpeg mux, Wav2Lip) is unchanged."""
    import asyncio

    import edge_tts
    import imageio_ffmpeg

    voice = languages.voice(lang, _gender())
    mp3_path = output_path.with_suffix(".edge.mp3")

    async def _run() -> None:
        await edge_tts.Communicate(
            text, voice, rate=SPEECH_RATE, pitch=SPEECH_PITCH
        ).save(str(mp3_path))

    # asyncio.run() refuses to start a loop inside a running one, and under
    # uvicorn there always is one. That raised
    #     asyncio.run() cannot be called from a running event loop
    # for every segment, so the FastAPI server silently fell through to Piper
    # — fine for en, hi and te, and SILENT for the other fifteen languages.
    # Streamlit never hit it because it has no loop of its own.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_run())                  # no loop here: the normal path
    else:
        # A loop is already running. Give the coroutine a thread with a loop
        # of its own and wait for it; speak() is synchronous by contract and
        # every caller depends on that.
        import threading

        failure: list[BaseException] = []

        def _worker() -> None:
            try:
                asyncio.run(_run())
            except BaseException as exc:     # re-raised on the calling thread
                failure.append(exc)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        if failure:
            raise failure[0]

    # 22050 mono is what Wav2Lip and the compositor both expect.
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
    
    voice_name = languages.get(lang).piper or languages.get("en").piper
    
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
