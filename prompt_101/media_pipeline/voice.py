"""Voice synthesis service with hash-based caching.

Supports two providers:
- Piper: Local CPU-based TTS for development (free, unlimited, Indian language voices)
- Google Cloud TTS WaveNet: High-quality TTS for final demo (free monthly allowance)

Both go behind the same speak() function. Provider is controlled by config.
"""
import subprocess
from pathlib import Path
from typing import Optional

from .config import (
    TTS_OUTPUT_DIR,
    TTS_PROVIDER,
    PIPER_BIN,
    PIPER_MODEL_DIR,
    GOOGLE_TTS_CREDENTIALS,
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
    # to go through Google Cloud TTS (see GOOGLE_VOICES below), which is the
    # final-demo backend anyway.
}

# Languages that require Google Cloud TTS (no Piper model available)
GOOGLE_ONLY_LANGUAGES = {"ta", "kn", "bn", "mr"}

# Google Cloud TTS voices
GOOGLE_VOICES = {
    "en": "en-US-Wavenet-D",
    "hi": "hi-IN-Wavenet-A",
    "ta": "ta-IN-Wavenet-A",
    "kn": "kn-IN-Wavenet-A",
    "te": "te-IN-Wavenet-A",
    "bn": "bn-IN-Wavenet-A",
    "mr": "mr-IN-Wavenet-A",
}


def _resolve_provider(lang: str) -> str:
    """Determine the TTS provider for a language.
    
    When TTS_PROVIDER is "auto" (default):
      - Languages with Piper models use "piper"
      - Languages without Piper models (ta, kn) use "google"
    When TTS_PROVIDER is "piper" or "google", that provider is forced.
    
    Returns:
        "piper" or "google"
    """
    if TTS_PROVIDER == "auto":
        if lang in GOOGLE_ONLY_LANGUAGES or lang not in PIPER_VOICES:
            return "google"
        return "piper"
    return TTS_PROVIDER


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
    
    # Resolve which provider to use for this language
    provider = _resolve_provider(lang)
    
    # Generate speech
    if provider == "piper":
        path = _speak_piper(text, lang, cache_path)
    elif provider == "google":
        path = _speak_google(text, lang, cache_path)
    else:
        raise ValueError(f"Unknown TTS provider: {provider}")
    
    return str(path)


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


# ── Google Cloud TTS Implementation ──

def _speak_google(text: str, lang: str, output_path: Path) -> Path:
    """Generate speech using Google Cloud TTS WaveNet."""
    try:
        from google.cloud import texttospeech
    except ImportError:
        raise ImportError(
            "google-cloud-texttospeech is required for Google TTS. "
            "Install with: pip install google-cloud-texttospeech"
        )
    
    if not GOOGLE_TTS_CREDENTIALS:
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS not set. "
            "Set it in your environment or .env file."
        )
    
    client = texttospeech.TextToSpeechClient()
    
    voice_name = GOOGLE_VOICES.get(lang, GOOGLE_VOICES["en"])
    
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=f"{lang}-IN" if lang != "en" else "en-US",
        name=voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=24000,
    )
    
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    
    # Save response audio
    output_path.write_bytes(response.audio_content)
    return output_path


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
