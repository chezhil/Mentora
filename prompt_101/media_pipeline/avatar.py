"""Fallback avatar: a colour card carrying the narration.

The real talking head is local_avatar/ (Wav2Lip on this machine, free, no
account). wiring._resolve_avatar prefers it whenever the weights are present,
so this module is only reached when they are missing or MENTORA_LOCAL_AVATAR=0.

This used to call LivePortrait on Replicate at about $0.40 per 60s render.
That path was removed because it could never run: it needed the `replicate`
package, which the root requirements.txt deliberately does not install, so
even with a token set it raised ModuleNotFoundError and fell through to the
placeholder below. It was dead code advertising a paid service.

The 60-second cap is kept — it is the contract the orchestrator checks against
before calling, and long clips are a planning bug worth surfacing.
"""
from pathlib import Path
from typing import Optional

from .config import AVATAR_OUTPUT_DIR, MAX_AVATAR_DURATION_SECONDS
from .utils import get_cached_path, get_audio_duration


def render_avatar(audio_path: str, photo_path: str,
                  output_path: Optional[str] = None) -> str:
    """A placeholder talking head: a colour card with the narration on it.

    Args:
        audio_path: Path to WAV audio file
        photo_path: Kept for signature compatibility with the real backend
        output_path: Optional custom output path; if None, uses cache

    Returns:
        Path to the generated MP4 file

    Raises:
        ValueError: If audio is longer than MAX_AVATAR_DURATION_SECONDS
    """
    audio_path = str(audio_path)
    photo_path = str(photo_path)

    # Non-negotiable, and enforced here as well as requested upstream.
    duration = get_audio_duration(audio_path)
    if duration > MAX_AVATAR_DURATION_SECONDS:
        raise ValueError(
            f"Segment too long ({duration:.1f}s) - split it first. "
            f"Maximum allowed: {MAX_AVATAR_DURATION_SECONDS}s"
        )

    cache_path = get_cached_path(
        Path(AVATAR_OUTPUT_DIR), "avatar", ".mp4", audio_path, photo_path
    )
    if cache_path.exists():
        return str(cache_path)

    print("[avatar] no local Wav2Lip weights; using a still placeholder. "
          "Run setup_assets.py for the real talking head.")
    return str(_create_placeholder_avatar(audio_path, cache_path))


def _create_placeholder_avatar(audio_path: str, output_path: Path) -> Path:
    """Create a placeholder avatar video when the local backend is unavailable.

    A flat colour card carrying the real audio, so the compositor still has a
    video stream and the lesson keeps its narration.

    The ffmpeg call used to sit INSIDE `except ImportError`, so on the normal
    path -- imageio-ffmpeg installed, which requirements.txt pins -- the
    function ran no ffmpeg at all and fell off the end returning None. The
    caller tests the result with `if mp4:`, so a clone without the Wav2Lip
    weights produced no video and reported nothing. Verified: it returned None
    and created no file.
    """
    import subprocess

    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_exe = "ffmpeg"

    duration = get_audio_duration(audio_path)
    base = [ffmpeg_exe, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=0x667eea:s=320x240:d={duration}",
            "-i", str(audio_path)]
    tail = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(output_path)]
    captioned = base + [
        "-vf", "drawtext=text='AI Teacher':fontsize=24:fontcolor=white:"
               "x=(w-text_w)/2:y=(h-text_h)/2"] + tail

    # drawtext needs libfreetype, which some ffmpeg builds omit; a plain card
    # with the narration on it is still a usable segment.
    for cmd in (captioned, base + tail):
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=120)
            if output_path.exists() and output_path.stat().st_size > 0:
                return output_path
        except Exception as exc:
            print(f"[avatar] placeholder attempt failed: {exc}")

    # Never leave a zero-byte MP4: it exists, so every `if mp4:` and
    # os.path.exists() downstream treats it as a real video.
    output_path.unlink(missing_ok=True)
    raise RuntimeError("could not build a placeholder avatar")


def validate_photo(photo_path: str) -> dict:
    """Validate that a photo meets avatar requirements.
    
    Front-facing, evenly lit, high resolution, neutral expression.
    
    Args:
        photo_path: Path to the photo to validate
    
    Returns:
        Dict with 'valid' bool and 'issues' list
    """
    issues = []
    photo = Path(photo_path)
    
    if not photo.exists():
        return {"valid": False, "issues": ["File does not exist"]}
    
    # Check file size (should be > 100KB for reasonable resolution)
    file_size = photo.stat().st_size
    if file_size < 100 * 1024:
        issues.append(f"File too small ({file_size / 1024:.1f}KB). Use a higher resolution image.")
    
    # Check dimensions if PIL is available
    try:
        from PIL import Image
        img = Image.open(photo)
        width, height = img.size
        
        if width < 512 or height < 512:
            issues.append(f"Image too small ({width}x{height}). Minimum recommended: 512x512")
        
        if width / height < 0.8 or width / height > 1.2:
            issues.append(f"Image not square-ish ({width}x{height}). Prefer 1:1 to 4:3 ratio.")
        
    except ImportError:
        pass  # PIL not available, skip dimension check
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
    }
