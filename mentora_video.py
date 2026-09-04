"""Mentora -> HF Wan text-to-video bridge.

Mentora (an AI teacher) plans a lesson into TeachingSegments, each with a
spoken `script` and a `VisualSpec` (equation/graph/diagram/timeline/code/
concept_map). This bridge turns one such segment into a visual-scene prompt
and renders an MP4 with the free Hugging Face Wan text-to-video pipeline
(fal-ai provider), so the "video" matches the teaching content.

Run:
    python mentora_video.py "Photosynthesis" beginner 20

Or set HF_TOKEN / HF_WAN_MODEL to override defaults:
    set HF_TOKEN=hf_xxx
    set HF_WAN_MODEL=Wan-AI/Wan2.2-TI2V-5B
"""

from __future__ import annotations

import os
import sys
from typing import Optional

# Mentora shared shape (kept local so this bridge runs without the app import).
from shared.models import TeachingSegment, VisualSpec


# ---------------------------------------------------------------------------
# 1. Build a Mentora-style lesson plan for a topic (rule-based stand-in for
#    the LLM planner so the bridge is self-contained and free to run).
# ---------------------------------------------------------------------------

def build_segments(topic: str) -> list[TeachingSegment]:
    """Three Mentora-style teaching segments for a topic (rule-based stand-in
    for the LLM planner, so the bridge is self-contained and free to run)."""
    return [
        TeachingSegment(
            concept_id="c1",
            script=f"An introduction to {topic}. Here is what {topic} means and why it matters.",
            visual=VisualSpec(kind="concept_map", payload=topic, caption=f"What is {topic}?"),
        ),
        TeachingSegment(
            concept_id="c2",
            script=f"Let us break {topic} down into its key parts and see how they connect.",
            visual=VisualSpec(kind="diagram", payload=topic, caption=f"Structure of {topic}"),
        ),
        TeachingSegment(
            concept_id="c3",
            script=f"A real example of {topic} in action, so it is easy to remember.",
            visual=VisualSpec(kind="timeline", payload=topic, caption=f"{topic} in context"),
        ),
    ]


# ---------------------------------------------------------------------------
# 2. VisualSpec -> Wan visual-scene prompt
# ---------------------------------------------------------------------------

_SCENE_HINTS = {
    "equation":  "a clean whiteboard with a large, legible mathematical equation drawn neatly",
    "graph":     "an animated chart plotting a smooth curve on grid paper, informative and clear",
    "diagram":   "a labeled, animated explanatory diagram with boxes and arrows showing relations",
    "timeline":  "a horizontal timeline with key markers lighting up one by one",
    "code":      "a screen showing slow, highlighted code being typed with syntax colouring",
    "concept_map": "a colorful concept map with a central idea and connected branch nodes radiating outward",
    "none":      "a calm instructional classroom scene with the topic text as a title",
}

STYLE = ("cinematic education video, warm studio lighting, gentle camera movement, "
         "clean readable typography, high quality, 24fps, professional explainer aesthetic")


def segment_to_prompt(segment: TeachingSegment, topic: str) -> str:
    hint = _SCENE_HINTS.get(segment.visual.kind, _SCENE_HINTS["none"])
    return f"{hint} explaining '{topic}'. {STYLE}"


# ---------------------------------------------------------------------------
# 3. Render with HF Wan (free fal-ai provider)
# ---------------------------------------------------------------------------

def render_video(prompt: str, out_path: str) -> str:
    """Render a Wan text-to-video MP4 via HF inference providers.

    Raises on any failure (quota 402, network, unsupported model) so the
    caller can fall back to the avatar path.
    """
    from huggingface_hub import InferenceClient
    from huggingface_hub.errors import HfHubHTTPError

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        raise RuntimeError("No HF token set. Set HF_TOKEN (huggingface.co/settings/tokens).")
    model = os.environ.get("HF_WAN_MODEL", "Wan-AI/Wan2.2-TI2V-5B")
    provider = os.environ.get("HF_WAN_PROVIDER", "fal-ai")

    client = InferenceClient(token=token, provider=provider)
    print(f"[wan] model={model} provider={provider}")
    print(f"[wan] prompt: {prompt}")
    print("[wan] generating video...")
    try:
        video = client.text_to_video(prompt, model=model)
    except HfHubHTTPError as e:
        # 402 = free credits exhausted; surface clearly for fallback.
        raise RuntimeError(f"Wan video failed ({e.response.status_code}): "
                           f"{getattr(e, 'server_message', e)}") from e
    with open(out_path, "wb") as f:
        f.write(video)
    print(f"[wan] saved {len(video)} bytes -> {out_path}")
    return out_path


def render_avatar_fallback(topic: str, out_path: str) -> str:
    """Fallback: generate a talking-head avatar video (Piper TTS + Wav2Lip)."""
    import mentora_avatar as avatar
    out_dir = os.path.dirname(out_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    slug = os.path.splitext(os.path.basename(out_path))[0]
    wav = os.path.join(out_dir, f"{slug}.wav")

    script = avatar.make_script(topic, "beginner")
    print(f"[avatar] script ({len(script)} chars)")
    avatar.speak(script, wav)
    avatar.render_avatar_mp4(wav, out_path)
    print(f"[avatar] DONE -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------

def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "Photosynthesis"
    level = sys.argv[2] if len(sys.argv) > 2 else "beginner"
    index = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    build_segments(topic)  # validate shapes
    segment = TeachingSegment(
        concept_id=f"c{index+1}",
        script=f"A visual lesson segment for {topic}.",
        visual=VisualSpec(kind="concept_map", payload=topic, caption=topic),
    )
    prompt = segment_to_prompt(segment, topic)
    out = f"mentora_{topic.lower().replace(' ','_')}_{index+1}.mp4"

    try:
        render_video(prompt, out)
        print(f"\nRESULT: Wan video -> {out}")
    except Exception as e:
        print(f"\n[wan] fallback triggered: {e}")
        render_avatar_fallback(topic, out)
        print(f"\nRESULT: avatar fallback video -> {out}")


if __name__ == "__main__":
    main()
