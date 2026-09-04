"""Wav2Lip avatar fallback for Mentora.

When HF Wan text-to-video fails (e.g. free quota exhausted / 402), fall back
to a talking-head avatar video: a still photo + synthesized speech, where the
photo's mouth is lip-synced (Wav2Lip) so it looks like a real teacher talking.

Pipeline:
  1. Script generation  -> local Gemini  (falls back to template if Gemini down)
  2. Speech synthesis   -> Piper (local, free)
  3. Avatar render      -> Wav2Lip photo + audio -> talking-head MP4

Run:
    python mentora_avatar.py "Photosynthesis" beginner
"""

from __future__ import annotations

import os
import sys
import json
import wave
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FACE_IMAGE = ROOT / "assets" / "teacher.jpg"
PIPER_VOICE = ROOT / "prompt_101" / "media_pipeline" / "piper_models" / "en_US-lessac-medium.onnx"

GEMINI_URL = os.environ.get("GEMINI_URL", "http://127.0.0.1:8010")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "sk-gemini")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")


# ---------------------------------------------------------------------------
# 1. Teaching script: try local Gemini, fall back to a deterministic template.
# ---------------------------------------------------------------------------

def _gemini_script(topic: str, level: str) -> str:
    prompt = (
        f"You are a friendly teacher. Write a short spoken narration to teach "
        f"'{topic}' to a {level} student. Keep it to 3-4 clear, simple spoken "
        f"sentences. Speak directly to the student. No markdown, no headers."
    )
    body = json.dumps({
        "model": GEMINI_MODEL,
        "input": prompt,
        "max_output_tokens": 200,
    }).encode()
    req = urllib.request.Request(
        f"{GEMINI_URL}/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {GEMINI_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return _extract_text(data)
    except Exception as e:
        print(f"[avatar] Gemini unavailable ({type(e).__name__}: {e}); "
              f"using template script")
        return ""


def _extract_text(data: dict) -> str:
    out = data.get("output_text") or ""
    if out:
        return out.strip()
    for item in data.get("output", []) or []:
        for c in item.get("content", []) or []:
            for p in c.get("text", []) or []:
                out += p.get("text", "")
    return out.strip()


def _template_script(topic: str, level: str) -> str:
    return (
        f"Today we are going to learn about {topic}. "
        f"Let us begin with the most important idea about {topic}. "
        f"Think of it as building blocks that fit together. "
        f"Take a moment, and let us look at one clear example together. "
        f"Great. Now you understand the basics of {topic}."
    )


def make_script(topic: str, level: str) -> str:
    script = _gemini_script(topic, level)
    return script or _template_script(topic, level)


# ---------------------------------------------------------------------------
# 2. Speech synthesis with Piper (local, free).
# ---------------------------------------------------------------------------

def speak(script: str, out_wav: str) -> str:
    from piper import PiperVoice
    voice = PiperVoice.load(str(PIPER_VOICE))
    sr = voice.config.sample_rate
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for chunk in voice.synthesize(script):
            w.writeframes(chunk.audio_int16_bytes)
    print(f"[avatar] wrote speech WAV ({os.path.getsize(out_wav)} bytes) -> {out_wav}")
    return out_wav


# ---------------------------------------------------------------------------
# 3. Avatar render via local Wav2Lip.
# ---------------------------------------------------------------------------

def render_avatar_mp4(audio_wav: str, out_mp4: str) -> str:
    if not audio_wav or not os.path.exists(audio_wav):
        raise FileNotFoundError(f"audio WAV missing: {audio_wav}")
    sys.path.insert(0, str(ROOT))
    from local_avatar.wav2lip import render_avatar as wl_render
    produced = wl_render(audio_wav, str(FACE_IMAGE))
    # copy/rename to requested output path
    if produced and Path(produced).exists() and Path(produced) != Path(out_mp4):
        Path(produced).replace(out_mp4)
    return out_mp4


# ---------------------------------------------------------------------------

def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "Photosynthesis"
    level = sys.argv[2] if len(sys.argv) > 2 else "beginner"

    out_dir = ROOT / "out" / "avatar"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = topic.lower().replace(" ", "_")

    script = make_script(topic, level)
    print(f"[avatar] script ({len(script)} chars)\n  {script}\n")

    wav = str(out_dir / f"mentora_{slug}.wav")
    speak(script, wav)

    mp4 = str(out_dir / f"mentora_{slug}.mp4")
    render_avatar_mp4(wav, mp4)
    print(f"[avatar] DONE -> {mp4}")


if __name__ == "__main__":
    main()
