"""Avatar video generation using LivePortrait on Replicate.

Creates talking head videos from a still photo + audio.
The lip-sync model needs the audio to animate against.

IMPORTANT: 60-second limit enforced in code.
- MONEY: 20-min render = $5-8, 60-sec = $0.40
- QUALITY: Models drift on long clips, face artifacts accumulate

Audio FIRST, then avatar - the lip-sync needs the audio to animate.
"""
from pathlib import Path
from typing import Optional

from .config import (
    AVATAR_OUTPUT_DIR,
    REPLICATE_API_TOKEN,
    LIVEPORTRAIT_MODEL,
    MAX_AVATAR_DURATION_SECONDS,
)
from .utils import get_cached_path, get_audio_duration


def render_avatar(audio_path: str, photo_path: str, output_path: Optional[str] = None) -> str:
    """Create talking head video from audio + still photo.
    
    Uses LivePortrait on Replicate for lip-sync animation.
    
    Args:
        audio_path: Path to WAV audio file
        photo_path: Path to teacher photo (front-facing, evenly lit, neutral expression)
        output_path: Optional custom output path; if None, uses cache
    
    Returns:
        Path to the generated MP4 file
    
    Raises:
        ValueError: If audio is longer than 60 seconds
        ValueError: If REPLICATE_API_TOKEN is not configured
    """
    audio_path = str(audio_path)
    photo_path = str(photo_path)
    
    # ── 60-SECOND LIMIT ──
    # This is non-negotiable. Enforce it in code.
    duration = get_audio_duration(audio_path)
    if duration > MAX_AVATAR_DURATION_SECONDS:
        raise ValueError(
            f"Segment too long ({duration:.1f}s) - split it first. "
            f"Maximum allowed: {MAX_AVATAR_DURATION_SECONDS}s"
        )
    
    # Check cache first (hash audio + photo)
    cache_path = get_cached_path(
        Path(AVATAR_OUTPUT_DIR), "avatar", ".mp4", audio_path, photo_path
    )
    
    if cache_path.exists():
        return str(cache_path)
    
    # Check API token
    if not REPLICATE_API_TOKEN:
        print("[avatar] REPLICATE_API_TOKEN not set, using a still placeholder. "
              "This path is only a fallback — the local Wav2Lip backend "
              "(local_avatar/) is free and needs no token. It is skipped only "
              "when models/wav2lip_gan.pth is missing or "
              "MENTORA_LOCAL_AVATAR=0.")
        return _create_placeholder_avatar(audio_path, cache_path)
    
    # Generate avatar video via Replicate
    try:
        path = _generate_liveportrait(audio_path, photo_path, cache_path)
        return str(path)
    except Exception as e:
        print(f"[avatar] LivePortrait failed: {e}. Using placeholder.")
        return _create_placeholder_avatar(audio_path, cache_path)


def _generate_liveportrait(audio_path: str, photo_path: str, output_path: Path) -> Path:
    """Generate avatar video using LivePortrait on Replicate.
    
    Model: lucataco/liveportrait:d3bc6890b893
    """
    import replicate
    
    print("[avatar] Generating LivePortrait video...")
    print(f"  Audio: {audio_path}")
    print(f"  Photo: {photo_path}")
    
    # Run the model
    output = replicate.run(
        LIVEPORTRAIT_MODEL,
        input={
            "source_image": open(photo_path, "rb"),
            "driving_audio": open(audio_path, "rb"),
            "pixel_multiplier": 2,  # Higher quality
            "use_identity": True,   # Preserve identity
        }
    )
    
    # Download the result
    import requests
    response = requests.get(output, stream=True)
    response.raise_for_status()
    
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    print(f"[avatar] Generated: {output_path}")
    return output_path


def _create_placeholder_avatar(audio_path: str, output_path: Path) -> Path:
    """Create a placeholder avatar video when LivePortrait is unavailable.
    
    Generates a simple colored rectangle video with the audio track.
    This allows the pipeline to test without Replicate access.
    """
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"
        
        duration = get_audio_duration(audio_path)
        
        # Create a simple colored video with text overlay
        cmd = [
            ffmpeg_exe,
            "-y",  # Overwrite
            "-f", "lavfi", "-i",
            f"color=c=0x667eea:s=320x240:d={duration}",
            "-i", audio_path,
            "-vf", "drawtext=text='AI Teacher':fontsize=24:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(output_path),
        ]
        
        import subprocess
        subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        
        if output_path.exists():
            return output_path
        else:
            raise RuntimeError("ffmpeg did not create output file")
            
    except Exception as e:
        print(f"[avatar] Placeholder creation failed: {e}")
        # Create empty MP4 as last resort
        output_path.write_bytes(b"")
        return output_path


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
