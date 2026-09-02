# Synthesise text to speech with automatic caching.

from __future__ import annotations
import logging
import wave
import shutil
from freebuff.cache import cache_path, get_cached, cache_key, _cache_dir
from pathlib import Path
from freebuff.config import get_config

logger = logging.getLogger(__name__)


def to_ssml(text):
    """Wrap text in SSML with pauses for teaching cadence."""
    import re
    def _sent(m):
        return m.group(1) + " <break time=\"500ms\"/> "
    text = re.sub(r"([.!?]) +", _sent, text)
    text = re.sub(r", +", ", <break time=\"300ms\"/> ", text)
    return "<speak>" + text + "</speak>"


def speak(text, lang="en", use_ssml=False):
    if not text or not text.strip():
        raise ValueError("Cannot synthesise empty text")

    # Apply SSML wrapping before caching
    ssml_text = to_ssml(text) if use_ssml else text

    cached = get_cached("voice", ".wav", ssml_text, lang)
    if cached:
        return cached

    cfg = get_config().get("voice", {})
    engine = cfg.get("engine", "piper")
    output = cache_path("voice", ".wav", ssml_text, lang)

    if engine == "piper":
        from freebuff.voice.piper_backend import synthesize_piper
        synthesize_piper(ssml_text, lang, output)
    else:
        raise ValueError(f"Unknown engine: {engine}")
    return str(output)




def split_audio(path, max_seconds=60, output_dir=None):
    """Split a WAV file into chunks of max_seconds each.

    Args:
        path: Path to the input WAV file.
        max_seconds: Maximum duration per chunk (default 60).
        output_dir: Directory for output files. Defaults to cache/voice/.

    Returns:
        List of paths to the split WAV files (in order).
    """

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Audio not found: {path}")

    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        total_frames = wf.getnframes()
        frames_per_chunk = int(sr * max_seconds)
        all_frames = wf.readframes(total_frames)

    duration = total_frames / sr
    if duration <= max_seconds:
        # Short enough - return single file (copy if needed)
        if output_dir:
            out = Path(output_dir) / path.name
            if out != path:
                shutil.copy2(str(path), str(out))
            return [str(out)]
        return [str(path)]

    if output_dir is None:
        output_dir = _cache_dir("voice")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate a base name from the content hash
    ck = cache_key(path.stem, str(max_seconds))

    parts = []
    offset = 0
    idx = 0
    while offset < total_frames:
        chunk_size = min(frames_per_chunk, total_frames - offset)
        chunk_data = all_frames[offset * n_channels * sampwidth:
                                (offset + chunk_size) * n_channels * sampwidth]

        out_path = output_dir / f"{ck}_part{idx:03d}.wav"
        with wave.open(str(out_path), "wb") as out:
            out.setnchannels(n_channels)
            out.setsampwidth(sampwidth)
            out.setframerate(sr)
            out.writeframes(chunk_data)

        parts.append(str(out_path))
        offset += chunk_size
        idx += 1

    return parts


def audio_duration(path):
    """Return duration of a WAV file in seconds."""
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()

