"""Full end-to-end demo — voice + visuals + composition.

Generates audio with Piper, creates visual title cards,
composes them into video segments, and stitches them together.

Run: py -X utf8 demo_full.py
"""

import sys
import os
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from freebuff.config import get_config
from freebuff.voice.cache import make_cache_key, get_cache_path
from freebuff.pipeline import _make_title_card


def synthesize_piper(text: str, output_path: str) -> float:
    """Synthesize speech and return duration in seconds."""
    from piper import PiperVoice

    voice = PiperVoice.load("voices/en_US-lessac-medium.onnx")
    chunks = list(voice.synthesize(text))
    audio_data = b""
    for chunk in chunks:
        audio_data += chunk.audio_int16_bytes

    with wave.open(output_path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(voice.config.sample_rate)
        wav_file.writeframes(audio_data)

    return len(audio_data) / (voice.config.sample_rate * 2)


def main():
    output = Path("output")
    output.mkdir(exist_ok=True)

    print("=" * 60)
    print("FREEBUFF DESKTOP - Full Pipeline Demo")
    print("=" * 60)

    # Define a 3-segment lesson
    segments = [
        {
            "text": "Welcome to todays physics lesson. We will learn about Ohms Law.",
            "kind": "none",
            "concept": "Ohms Law",
            "subject": "physics",
        },
        {
            "text": "Ohms Law states that voltage equals current times resistance. The formula is V equals I times R.",
            "kind": "equation",
            "concept": "V = I x R",
            "subject": "physics",
        },
        {
            "text": "This means that if you increase the current through a resistor, the voltage across it increases proportionally. Thank you for watching.",
            "kind": "graph",
            "concept": "Voltage vs Current",
            "subject": "physics",
        },
    ]

    audio_files = []
    visual_files = []
    segment_files = []

    for i, seg in enumerate(segments):
        print(f"\n--- Segment {i+1}: {seg['concept']} ---")

        # 1. Generate audio
        audio_path = str(output / f"audio_{i:03d}.wav")
        print(f"  Generating audio: \"{seg['text'][:50]}...\"")
        duration = synthesize_piper(seg["text"], audio_path)
        print(f"  Audio: {audio_path} ({duration:.1f}s)")

        # 2. Generate visual
        visual_path = str(output / f"visual_{i:03d}.png")
        spec = {"kind": seg["kind"], "concept_name": seg["concept"], "subject": seg["subject"]}
        tmp_path = _make_title_card(spec, i)
        import shutil
        shutil.copy2(tmp_path, visual_path)
        os.unlink(tmp_path)
        print(f"  Visual: {visual_path}")

        audio_files.append(audio_path)
        visual_files.append(visual_path)

    # 3. Compose segments (visual + audio, no avatar since we don't have a photo)
    print("\n--- Composing Video Segments ---")
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"
    import subprocess

    for i in range(len(segments)):
        seg_path = str(output / f"segment_{i:03d}.mp4")
        cmd = [
            ffmpeg_exe, "-y",
            "-loop", "1", "-i", visual_files[i],
            "-i", audio_files[i],
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            seg_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR composing segment {i}: {result.stderr[-200:]}")
            continue
        size = os.path.getsize(seg_path)
        print(f"  Segment {i}: {seg_path} ({size} bytes)")
        segment_files.append(seg_path)

    # 4. Stitch segments
    if len(segment_files) >= 2:
        print("\n--- Stitching Final Video ---")
        list_file = str(output / "concat_list.txt")
        with open(list_file, "w") as f:
            for seg in segment_files:
                f.write(f"file '{os.path.abspath(seg)}'\n")

        final_path = str(output / "lesson_final.mp4")
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            "-movflags", "+faststart",
            final_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        os.unlink(list_file)

        if result.returncode == 0:
            size = os.path.getsize(final_path)
            print(f"  Final video: {final_path} ({size} bytes)")
        else:
            print(f"  ERROR: {result.stderr[-200:]}")

    # 5. Show cache behavior
    print("\n--- Cache Demo ---")
    for seg in segments:
        key = make_cache_key(seg["text"], "en")
        path = get_cache_path(seg["text"], "en")
        print(f"  \"{seg['text'][:40]}...\"")
        print(f"    hash: {key[:16]}...  path: {path}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print(f"\nFiles in output/:")
    for f in sorted(output.iterdir()):
        if f.suffix in (".wav", ".mp4", ".png", ".html"):
            size = f.stat().st_size
            print(f"  {f.name:30s} {size:>10,} bytes")
    print(f"\nOpen output/lesson_final.mp4 to watch the video.")


if __name__ == "__main__":
    main()
