"""Fetch the local Wav2Lip weights (one-time, ~436 MB total).

Safe to re-run: files already present and the right size are skipped.

    python setup_models.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent / "models"

# (url, filename, expected_min_bytes) — pth is ~436 MB, yunet ~230 KB.
FILES = [
    (
        "https://huggingface.co/camenduru/Wav2Lip/resolve/main/"
        "checkpoints/wav2lip_gan.pth",
        "wav2lip_gan.pth",
        400 * 1024 * 1024,
    ),
    (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "face_detection_yunet.onnx",
        200 * 1024,
    ),
]


def _download(url: str, dest: Path) -> None:
    print(f"Downloading {dest.name} …", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "avatar-studio"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = 100.0 * done / total
                print(f"  {done / 1e6:.0f}/{total / 1e6:.0f} MB ({pct:.0f}%)",
                      end="\r", flush=True)
    print(f"  done ({dest.stat().st_size / 1e6:.0f} MB)", flush=True)


def main() -> int:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for url, name, minimum in FILES:
        dest = MODELS_DIR / name
        if dest.is_file() and dest.stat().st_size >= minimum:
            print(f"{name}: already present, skipping")
            continue
        try:
            _download(url, dest)
        except Exception as exc:
            dest.unlink(missing_ok=True)
            print(f"Failed to download {name}: {exc}", file=sys.stderr)
            return 1
    print("All set — restart the server and generate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())