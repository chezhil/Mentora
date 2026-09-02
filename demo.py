"""Quick demo — generate visuals and show the pipeline working.

Run: py demo.py
Output goes to output/ directory.
"""

import sys
from pathlib import Path

# Ensure freebuff is importable
sys.path.insert(0, str(Path(__file__).parent))

from freebuff.config import get_config
from freebuff.voice.cache import make_cache_key, get_cache_path
from freebuff.avatar.cache import make_cache_key as avatar_key
from freebuff.pipeline import _make_title_card
import shutil


def main():
    output = Path("output")
    output.mkdir(exist_ok=True)

    print("=" * 60)
    print("FREEBUFF DESKTOP — Media Pipeline Demo")
    print("=" * 60)

    # 1. Show config
    cfg = get_config()
    print(f"\n[OK] Config loaded")
    print(f"  Voice engine:  {cfg['voice']['engine']}")
    print(f"  Avatar model:  {cfg['avatar']['model']}")
    print(f"  Max duration:  {cfg['avatar']['max_duration_seconds']}s")

    # 2. Demonstrate caching (hashing)
    print(f"\n--- Voice Cache Demo ---")
    text = "Ohm's Law states that V equals I times R"
    lang = "en"
    key = make_cache_key(text, lang)
    path = get_cache_path(text, lang)
    print(f'  Text:  "{text}"')
    print(f"  Lang:  {lang}")
    print(f"  Hash:  {key[:16]}...")
    print(f"  Path:  {path}")

    key2 = make_cache_key(text, "hi")
    print(f'\n  Same text, Hindi:  hash={key2[:16]}...  (different!)')

    # 3. Generate title cards for different visual kinds
    print(f"\n--- Visual Rendering Demo ---")
    concepts = [
        {"kind": "equation",  "concept_name": "V = I × R",       "subject": "physics"},
        {"kind": "graph",     "concept_name": "Quadratic Functions", "subject": "maths"},
        {"kind": "timeline",  "concept_name": "French Revolution", "subject": "history"},
        {"kind": "code",      "concept_name": "Binary Search",    "subject": "programming"},
        {"kind": "diagram",   "concept_name": "Cell Structure",   "subject": "biology"},
        {"kind": "concept_map", "concept_name": "Machine Learning", "subject": "cs"},
        {"kind": "none",      "concept_name": "Ohm's Law",        "subject": "physics"},
    ]

    for i, spec in enumerate(concepts):
        path = _make_title_card(spec, i)
        out = output / f"demo_{spec['kind']}.png"
        shutil.copy2(path, out)
        print(f"  [{spec['kind']:12s}] {spec['concept_name']:25s} -> {out}")

    # 4. Show the 60-second guard
    print(f"\n--- 60-Second Guard Demo ---")
    from freebuff.avatar.render_avatar import MAX_DURATION_SECONDS
    print(f"  Max avatar audio: {MAX_DURATION_SECONDS} seconds")
    print(f"  Cost at 60s:  ~$0.40")
    print(f"  Cost at 20m:  ~$5-8")

    # 5. Show what's needed for full pipeline
    print(f"\n--- Full Pipeline Requirements ---")
    print(f"  Voice:   pip install piper-tts  (then run speak())")
    print(f"  Avatar:  REPLICATE_API_TOKEN env var + run render_avatar()")
    print(f"  Video:   imageio-ffmpeg (already installed)")
    print(f"\n  To run full pipeline:")
    print(f"    from freebuff.pipeline import render_lesson")
    print(f"    render_lesson(segments, photo_path='teacher.jpg')")

    print(f"\n[OK] Demo complete. Check output/ directory for PNG files.")
    print(f"  Open output/demo_equation.png to see the equation title card.")


if __name__ == "__main__":
    main()
