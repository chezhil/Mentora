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
        "[0:v][av]overlay=W-w-40:H-h-40:shortest=1[vout]",
        "-map", "[vout]", "-map", "1:a?", "-map", "2:a?",
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
                title, "Mentora · AI Teacher", duration=4.0)
            all_parts.append(title_card)
            temp_files.append(Path(title_card))
        
        # Lesson segments
        all_parts.extend(segment_paths)
        
        # Closing card
        closing_card = _make_text_card(
            "End of lesson", "Open the Report tab for your feedback",
            duration=3.0, bg_color="#4A7DFF", text_color="#FFFFFF")
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
    bg_color: str = "#FFD400",
    text_color: str = "#12100E",
) -> str:
    """Create a title/closing card as a short MP4, exactly 1280x720.

    The size matters more than it looks. This used to save the PNG with
    bbox_inches="tight", which crops to the ink and gave a 1012x574 card. The
    concat demuxer then took its parameters from the FIRST input, so the whole
    lesson video came out 1012x574 and the 1280x720 segments after it were
    dropped — a 16-second "lesson" of a title card, a fragment, and a thank
    you. Nothing warned; the file played.

    So: no tight bounding box, an explicit figure size, and stitch() normalises
    every part anyway. Belt and braces, because this is the deliverable.
    """
    import uuid
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    png_path = COMPOSE_OUTPUT_DIR / f"card_{uuid.uuid4().hex[:8]}.png"
    fig, ax = plt.subplots(1, 1, figsize=(12.8, 7.2), dpi=100)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.set_facecolor("#F5F1E8")
    fig.patch.set_facecolor("#F5F1E8")
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Same language as the visuals: flat colour, black keyline, hard shadow.
    ax.add_patch(Rectangle((0.09, 0.335), 0.82, 0.33, facecolor="#12100E",
                           edgecolor="none", transform=ax.transAxes, zorder=1))
    ax.add_patch(Rectangle((0.08, 0.35), 0.82, 0.33, facecolor=bg_color,
                           edgecolor="#12100E", linewidth=4,
                           transform=ax.transAxes, zorder=2))

    ax.text(0.49, 0.545, heading[:44], fontsize=52, fontweight="bold",
            ha="center", va="center", color=text_color, zorder=3)
    if subtext:
        ax.text(0.49, 0.44, subtext[:60], fontsize=22, fontweight="bold",
                ha="center", va="center", color=text_color, alpha=0.75,
                zorder=3)

    fig.savefig(str(png_path), dpi=100, facecolor=fig.get_facecolor(),
                edgecolor="none")
    plt.close(fig)

    mp4_path = str(COMPOSE_OUTPUT_DIR / f"card_{uuid.uuid4().hex[:8]}.mp4")
    silent = create_silent_audio(duration, COMPOSE_OUTPUT_DIR)

    cmd = [
        get_ffmpeg_exe(), "-y",
        "-loop", "1", "-i", str(png_path),
        "-i", silent,
        "-c:v", "libx264", "-t", str(duration),
        "-vf", f"scale={TARGET_W}:{TARGET_H}",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-shortest",
        mp4_path,
    ]
    _run_ffmpeg(cmd)

    png_path.unlink(missing_ok=True)
    Path(silent).unlink(missing_ok=True)
    return mp4_path


TARGET_W, TARGET_H, TARGET_FPS = 1280, 720, 25
TARGET_RATE, TARGET_CH = 44100, 1


def _has_audio(path: str) -> bool:
    """True when the file carries an audio stream.

    ffprobe is not shipped by imageio-ffmpeg, so this reads ffmpeg's own report
    of the input rather than adding a dependency for one boolean.
    """
    result = subprocess.run([get_ffmpeg_exe(), "-i", str(path)],
                            capture_output=True, text=True)
    return "Audio:" in result.stderr


def _normalise(path: str, index: int) -> str:
    """Re-encode one part to the exact stream parameters concat requires.

    The concat demuxer copies streams, which means every input must already
    agree on resolution, pixel format, frame rate, sample rate and channel
    count. Ours did not: the title card was a different size from the
    segments, and a segment built from a silent placeholder could arrive with
    no audio stream at all. Concat does not fail on that — it produces a file
    that plays and is missing most of the lesson.

    Anything that does not fit is letterboxed rather than stretched, so a
    16:9 lesson never comes out with the teacher squashed.
    """
    out = COMPOSE_OUTPUT_DIR / f"norm_{index:03d}_{Path(path).stem[:8]}.mp4"
    video = (f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
             f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:color=0x12100E,"
             f"setsar=1,fps={TARGET_FPS},format=yuv420p")

    cmd = [get_ffmpeg_exe(), "-y", "-i", str(path)]
    if _has_audio(path):
        cmd += ["-map", "0:v:0", "-map", "0:a:0"]
    else:
        # Give it silence, so every part has the audio stream concat expects.
        cmd += ["-f", "lavfi", "-i",
                f"anullsrc=r={TARGET_RATE}:cl=mono",
                "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += [
        "-vf", video,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-ar", str(TARGET_RATE), "-ac", str(TARGET_CH),
        "-movflags", "+faststart", str(out),
    ]
    _run_ffmpeg(cmd)
    return str(out)


def stitch(segments: List[str], output_path: Optional[str] = None) -> str:
    """Concatenate segment MP4s into the final lesson video.

    Every part is normalised first — see _normalise. That costs one re-encode
    per segment and buys a video that is actually the whole lesson.

    Args:
        segments: List of paths to segment MP4s (in order)
        output_path: Optional custom output path

    Returns:
        Path to the final stitched MP4
    """
    if not segments:
        raise ValueError("No segments to stitch")

    if output_path is None:
        output_path = str(COMPOSE_OUTPUT_DIR / "final_lesson.mp4")

    import tempfile

    normalised = [_normalise(seg, i) for i, seg in enumerate(segments)]
    concat_list = Path(tempfile.mktemp(suffix=".txt"))

    try:
        with open(concat_list, "w") as f:
            for seg in normalised:
                f.write(f"file '{Path(seg).resolve().as_posix()}'\n")

        _run_ffmpeg([
            get_ffmpeg_exe(), "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ])
        return output_path
    finally:
        concat_list.unlink(missing_ok=True)
        for seg in normalised:
            Path(seg).unlink(missing_ok=True)


def _run_ffmpeg(cmd: List[str]) -> None:
    """Run an ffmpeg command and handle errors."""
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg timed out after 5 minutes")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed: {e.stderr}")
