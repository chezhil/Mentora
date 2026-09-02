"""End-to-end lesson renderer."""

from __future__ import annotations
import logging
from pathlib import Path
from freebuff.composite.compose import compose
from freebuff.composite.stitch import stitch
from freebuff.voice.speak import speak, split_audio, audio_duration

logger = logging.getLogger(__name__)


def render_lesson(segments, output_path="output/lesson.mp4", render_visual_fn=None,
                  photo_path=None, max_segment_seconds=60):
    """Render a lesson from segment specs.

    Each segment dict should have:
      - text: narration text
      - lang: language code (default "en")
      - visual_spec: dict for render_visual_fn
      - show_avatar: bool (default True if photo_path given)
      - subtitle: optional subtitle text overlay
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if render_visual_fn is None:
        raise ValueError("render_visual_fn required")

    seg_files = []
    for i, seg in enumerate(segments):
        text = seg["text"]
        lang = seg.get("lang", "en")
        show_avatar = seg.get("show_avatar", photo_path is not None)
        subtitle = seg.get("subtitle", None)

        # Synthesize audio
        audio_wav = speak(text, lang)

        # Split if too long for avatar
        if show_avatar and photo_path:
            if audio_duration(Path(audio_wav)) > max_segment_seconds:
                chunks = split_audio(audio_wav, max_segment_seconds)
            else:
                chunks = [audio_wav]
        else:
            chunks = [audio_wav]

        # Render visual
        visual_png = render_visual_fn(seg.get("visual_spec", {}))

        # Compose each chunk
        for j, chunk in enumerate(chunks):
            avatar = photo_path if show_avatar else None
            sub = subtitle if j == 0 else None  # subtitle on first chunk only
            seg_mp4 = str(output_path.parent / f"segment_{i:03d}_{j:03d}.mp4")
            compose(visual_png, chunk, seg_mp4, avatar_mp4=avatar, subtitle_text=sub)
            seg_files.append(seg_mp4)

    return stitch(seg_files, output_path)