"""Video compositing and stitching service.

Assembles visual slides, avatar video, and audio into segment MP4s,
then stitches segments into final video.

Uses imageio-ffmpeg for cross-platform ffmpeg binary.

Public API:
    compose()             - Visual + audio + optional avatar → segment MP4
    stitch()              - Concatenate segments → final MP4
    build_lesson_video()  - Title card + segments + closing card → lesson MP4
"""
import subprocess
from pathlib import Path
from typing import List, Optional

from .config import COMPOSE_OUTPUT_DIR, USE_IMAGEIO_FFMPEG
from .utils import create_silent_audio


def get_ffmpeg_exe() -> str:
    """Get ffmpeg executable path.
    
    Uses imageio-ffmpeg for cross-platform compatibility.
    The pip package ships one static binary for all platforms.
    """
    if USE_IMAGEIO_FFMPEG:
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    return "ffmpeg"


def compose(
    visual_path: str,
    audio_path: Optional[str] = None,
    avatar_path: Optional[str] = None,
    show_avatar: bool = True,
    output_path: Optional[str] = None,
) -> str:
    """Compose visual slide + audio (+ optional avatar) into a segment MP4.
    
    The avatar (if present) appears in the bottom-right corner of the visual.
    
    Supports two calling conventions:
      compose(visual_path, audio_path)  - visual + audio, no avatar
      compose(visual_path, audio_path, avatar_path) - visual + audio + avatar
    
    Args:
        visual_path: Path to the PNG visual slide
        audio_path: Path to the WAV audio (or None for visual-only)
        avatar_path: Optional path to the avatar MP4 video
        show_avatar: Whether to show the avatar overlay (can be False for visual-only sections)
        output_path: Optional custom output path
    
    Returns:
        Path to the composed MP4 segment
    """
    visual_path = str(visual_path)
    
    # Handle None audio - create silent audio if needed
    if audio_path is None or audio_path == "None":
        audio_path = create_silent_audio(3.0, COMPOSE_OUTPUT_DIR)
    else:
        audio_path = str(audio_path)
    
    if output_path is None:
        import uuid
        output_path = str(COMPOSE_OUTPUT_DIR / f"segment_{uuid.uuid4().hex[:8]}.mp4")
    output_path = str(output_path)
    
    ffmpeg_exe = get_ffmpeg_exe()
    
    if avatar_path and avatar_path != "None" and show_avatar and Path(avatar_path).exists():
        return _compose_with_avatar(ffmpeg_exe, visual_path, audio_path, avatar_path, output_path)
    else:
        return _compose_visual_only(ffmpeg_exe, visual_path, audio_path, output_path)


def _compose_with_avatar(
    ffmpeg_exe: str, visual_path: str, audio_path: str,
    avatar_path: str, output_path: str,
) -> str:
    """Compose visual + avatar overlay + audio.
    
    Input order: [0] visual PNG, [1] avatar MP4, [2] audio WAV
    Filter: scale avatar, overlay on visual bottom-right
    Map: video from overlay, audio from WAV
    """
    cmd = [
        ffmpeg_exe, "-y",
        "-loop", "1", "-i", visual_path,  # Input 0: visual
        "-i", avatar_path,                 # Input 1: avatar
        "-i", audio_path,                  # Input 2: audio
        "-filter_complex",
        "[1:v]scale=320:-1[av];"
        "[0:v][av]overlay=W-w-40:H-h-40[vout]",
        "-map", "[vout]", "-map", "2:a",
        "-c:v", "libx264", "-shortest",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        output_path,
    ]
    _run_ffmpeg(cmd)
    return output_path


def _compose_visual_only(
    ffmpeg_exe: str, visual_path: str, audio_path: str, output_path: str,
) -> str:
    """Compose visual-only (no avatar overlay)."""
    cmd = [
        ffmpeg_exe, "-y",
        "-loop", "1", "-i", visual_path,
        "-i", audio_path,
        "-c:v", "libx264", "-shortest",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        output_path,
    ]
    _run_ffmpeg(cmd)
    return output_path


def build_lesson_video(
    segment_paths: List[str],
    title: str = "",
    output_path: Optional[str] = None,
) -> str:
    """Build a complete lesson video from segment MP4s.
    
    Prepends a title card and appends a closing card, then stitches
    everything into a single MP4. The single entry point for producing
    the final lesson video.
    
    Args:
        segment_paths: List of segment MP4 paths in order
        title: Lesson title for the opening card (empty = no title card)
        output_path: Optional custom output path
    
    Returns:
        Path to the final lesson MP4, or "" if segment_paths is empty.
    """
    if not segment_paths:
        return ""
    
    if output_path is None:
        output_path = str(COMPOSE_OUTPUT_DIR / "lesson_video.mp4")
    
    # Build the full sequence: title card + segments + closing card
    all_parts: List[str] = []
    temp_files: List[Path] = []
    
    try:
        # Title card
        if title:
            title_card = _make_text_card(
                title, "AI Teacher", duration=4.0,
                bg_color="#1a1a2e", text_color="#ffffff",
            )
            all_parts.append(title_card)
            temp_files.append(Path(title_card))
        
        # Lesson segments
        all_parts.extend(segment_paths)
        
        # Closing card
        closing_card = _make_text_card(
            "Thank You", "End of Lesson",
            duration=3.0, bg_color="#1a1a2e", text_color="#ffffff",
        )
        all_parts.append(closing_card)
        temp_files.append(Path(closing_card))
        
        # Stitch all parts together
        return stitch(all_parts, output_path)
    finally:
        # Clean up temporary title/closing card videos
        for f in temp_files:
            if f.exists():
                f.unlink(missing_ok=True)


def _make_text_card(
    heading: str, subtext: str = "",
    duration: float = 3.0,
    bg_color: str = "#1a1a2e",
    text_color: str = "#ffffff",
) -> str:
    """Create a title/closing card as a short MP4.
    
    Renders a PNG with matplotlib, then wraps it in a silent video.
    
    Returns:
        Path to the temporary MP4 card file.
    """
    import uuid
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    
    # Render card as PNG
    png_path = COMPOSE_OUTPUT_DIR / f"card_{uuid.uuid4().hex[:8]}.png"
    fig, ax = plt.subplots(1, 1, figsize=(12.8, 7.2), dpi=100)
    ax.set_facecolor(bg_color)
    fig.patch.set_facecolor(bg_color)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    
    # Heading
    ax.text(0.5, 0.58, heading, fontsize=48, fontweight="bold",
            ha="center", va="center", color=text_color,
            fontfamily="sans-serif")
    
    # Subtext
    if subtext:
        ax.text(0.5, 0.38, subtext, fontsize=24,
                ha="center", va="center", color="#aaaaaa",
                fontfamily="sans-serif")
    
    # Accent line
    ax.plot([0.3, 0.7], [0.48, 0.48], color="#667eea",
            linewidth=3, alpha=0.8, transform=ax.transAxes)
    
    fig.savefig(str(png_path), dpi=100, facecolor=fig.get_facecolor(),
                edgecolor="none", bbox_inches="tight")
    plt.close(fig)
    
    # Wrap PNG into a silent MP4 of specified duration
    mp4_path = str(COMPOSE_OUTPUT_DIR / f"card_{uuid.uuid4().hex[:8]}.mp4")
    silent = create_silent_audio(duration, COMPOSE_OUTPUT_DIR)
    
    ffmpeg_exe = get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe, "-y",
        "-loop", "1", "-i", str(png_path),
        "-i", silent,
        "-c:v", "libx264", "-t", str(duration),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-shortest",
        mp4_path,
    ]
    _run_ffmpeg(cmd)
    
    # Clean up intermediate files
    png_path.unlink(missing_ok=True)
    Path(silent).unlink(missing_ok=True)
    
    return mp4_path


def stitch(segments: List[str], output_path: Optional[str] = None) -> str:
    """Concatenate multiple segment MP4s into final video.
    
    All segments must be encoded the same way for lossless stream copy.
    
    Args:
        segments: List of paths to segment MP4s (in order)
        output_path: Optional custom output path
    
    Returns:
        Path to the final stitched MP4
    """
    if not segments:
        raise ValueError("No segments to stitch")
    
    if len(segments) == 1:
        if output_path is None:
            output_path = str(COMPOSE_OUTPUT_DIR / "final_lesson.mp4")
        import shutil
        shutil.copy2(segments[0], output_path)
        return output_path
    
    import tempfile
    concat_list = Path(tempfile.mktemp(suffix=".txt"))
    
    try:
        with open(concat_list, "w") as f:
            for seg in segments:
                seg_path = Path(seg).resolve().as_posix()
                f.write(f"file '{seg_path}'\n")
        
        ffmpeg_exe = get_ffmpeg_exe()
        
        if output_path is None:
            output_path = str(COMPOSE_OUTPUT_DIR / "final_lesson.mp4")
        
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        _run_ffmpeg(cmd)
        return output_path
        
    finally:
        if concat_list.exists():
            concat_list.unlink()


def _run_ffmpeg(cmd: List[str]) -> None:
    """Run an ffmpeg command and handle errors."""
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg timed out after 5 minutes")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed: {e.stderr}")
