"""Download everything the repo cannot carry.

The model weights are 500MB and cannot live in git, so a fresh clone starts
without them. Without this script you still get a lesson, but a degraded one:

    no models/wav2lip_gan.pth   -> avatar is a still image, not a talking head
    no piper_models/*.onnx      -> narration is silent
    no face_detection_yunet     -> no face detection

Run it once after installing requirements:

    .venv/bin/python setup_assets.py

Safe to re-run; anything already present and the right size is skipped.
"""

from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
PIPER = ROOT / "prompt_101" / "media_pipeline" / "piper_models"
HF = "https://huggingface.co"

ASSETS = [
    # (destination, url, approx bytes, what it buys you)
    (ROOT / "models" / "wav2lip_gan.pth",
     f"{HF}/camenduru/Wav2Lip/resolve/main/checkpoints/wav2lip_gan.pth",
     435_801_865, "talking-head avatar"),
    (ROOT / "models" / "face_detection_yunet.onnx",
     "https://github.com/opencv/opencv_zoo/raw/main/models/"
     "face_detection_yunet/face_detection_yunet_2023mar.onnx",
     232_589, "face detection for the avatar"),
    (PIPER / "en_US-lessac-medium.onnx",
     f"{HF}/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/"
     "en_US-lessac-medium.onnx", 63_201_294, "English voice"),
    (PIPER / "en_US-lessac-medium.onnx.json",
     f"{HF}/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/"
     "en_US-lessac-medium.onnx.json", 4_885, "English voice config"),
    (PIPER / "hi_IN-pratham-medium.onnx",
     f"{HF}/rhasspy/piper-voices/resolve/main/hi/hi_IN/pratham/medium/"
     "hi_IN-pratham-medium.onnx", 63_516_050, "Hindi voice"),
    (PIPER / "hi_IN-pratham-medium.onnx.json",
     f"{HF}/rhasspy/piper-voices/resolve/main/hi/hi_IN/pratham/medium/"
     "hi_IN-pratham-medium.onnx.json", 4_970, "Hindi voice config"),
    (PIPER / "te_IN-maya-medium.onnx",
     f"{HF}/rhasspy/piper-voices/resolve/main/te/te_IN/maya/medium/"
     "te_IN-maya-medium.onnx", 62_950_044, "Telugu voice"),
    (PIPER / "te_IN-maya-medium.onnx.json",
     f"{HF}/rhasspy/piper-voices/resolve/main/te/te_IN/maya/medium/"
     "te_IN-maya-medium.onnx.json", 5_040, "Telugu voice config"),
]

# Tamil, Kannada, Bengali and Marathi need no download — Piper has no voices
# for them and they go through edge-tts, which streams on demand.


def _progress(done: int, total: int, name: str) -> None:
    if total <= 0:
        return
    pct = min(100, done * 100 // total)
    bar = "#" * (pct // 4)
    sys.stdout.write(f"\r  {name:34} [{bar:<25}] {pct:3d}%")
    sys.stdout.flush()


def fetch(dest: Path, url: str, size: int, what: str) -> bool:
    if dest.exists() and dest.stat().st_size >= size * 0.95:
        print(f"  {dest.name:34} already present")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
            total = int(r.headers.get("content-length") or size)
            done = 0
            while chunk := r.read(1 << 16):
                f.write(chunk)
                done += len(chunk)
                _progress(done, total, dest.name)
        print()
        return True
    except Exception as exc:
        print(f"\n  FAILED {dest.name}: {exc}\n    (needed for: {what})")
        dest.unlink(missing_ok=True)
        return False


def main() -> int:
    print("Downloading model weights (~500MB, once).\n")
    ok = all([fetch(*a) for a in ASSETS])
    print()
    if ok:
        print("All assets present. Video and voice will work.")
    else:
        print("Some downloads failed. The app still runs — the avatar falls "
              "back to a still image and narration to silence — but re-run "
              "this before recording anything.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
