"""Hashing, caching, and audio utilities for the media pipeline."""
import hashlib
import uuid
import wave
from pathlib import Path


def hash_content(text: str, extra: str = "") -> str:
    """Hash text content (and optional extra salt) to create a cache key.
    
    Args:
        text: The primary content to hash (e.g., TTS text, audio path)
        extra: Optional additional salt (e.g., photo path for avatar)
    
    Returns:
        SHA256 hex digest (first 16 chars for brevity)
    """
    content = f"{text}||{extra}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def get_cached_path(cache_dir: Path, prefix: str, extension: str, text: str, extra: str = "") -> Path:
    """Get a cached file path, creating it from content hash.
    
    Args:
        cache_dir: Directory to store cached files
        prefix: Filename prefix (e.g., "tts", "avatar")
        extension: File extension (e.g., ".wav", ".mp4")
        text: Content to hash for cache key
        extra: Optional additional salt for hash
    
    Returns:
        Path object for the cached file
    """
    h = hash_content(text, extra)
    filename = f"{prefix}_{h}{extension}"
    return cache_dir / filename


def is_cached(cache_dir: Path, prefix: str, extension: str, text: str, extra: str = "") -> bool:
    """Check if a cached file exists.
    
    Args:
        cache_dir: Directory to check for cached files
        prefix: Filename prefix
        extension: File extension
        text: Content to hash
        extra: Optional additional salt
    
    Returns:
        True if the cached file exists
    """
    path = get_cached_path(cache_dir, prefix, extension, text, extra)
    return path.exists()


def get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds.
    
    For WAV files, uses the wave module directly (no ffprobe needed).
    Falls back to file-size estimation for other formats.
    
    Args:
        audio_path: Path to the audio file
    
    Returns:
        Duration in seconds
    """
    audio_path = str(audio_path)
    
    # For WAV files, use the wave module directly - always works
    if audio_path.lower().endswith(".wav"):
        try:
            with wave.open(audio_path, "r") as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                return frames / rate
        except Exception:
            pass
    
    # Fallback: estimate from file size
    file_size = Path(audio_path).stat().st_size
    return file_size / 44100  # WAV at 22050 Hz, 16-bit mono = ~44100 bytes/sec


def create_silent_audio(duration: float, output_dir: Path) -> str:
    """Create a silent WAV file.
    
    Args:
        duration: Duration in seconds
        output_dir: Directory to write the WAV file
    
    Returns:
        Path to the created WAV file
    """
    wav_path = str(output_dir / f"silent_{uuid.uuid4().hex[:8]}.wav")
    sample_rate = 44100
    num_samples = int(duration * sample_rate)
    
    with wave.open(wav_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b'\x00\x00' * num_samples)
    
    return wav_path
