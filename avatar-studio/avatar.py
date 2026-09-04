"""Photoreal talking-head engine: SadTalker on Replicate.

This is the OPT-IN implementation of the RenderEngine interface jobs.py
drives — never the default. The free on-device engine (wav2lip_engine.py)
is; switch with AVATAR_ENGINE=replicate in app.py.

Replicate runs in the cloud, so it cannot fetch http://localhost/...: the
audio travels as a base64 data URI, which the API accepts directly.
Renders are billed to REPLICATE_API_TOKEN at roughly $0.05 each.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import httpx

from jobs import EngineUnavailable

try:
    import replicate
except ImportError:  # pip install -r requirements.txt fixes this
    replicate = None

MODEL = "cjwbw/sadtalker"
IMAGE_PATH = Path(__file__).parent / "assets" / "avatar.jpg"

# SadTalker knobs. `still_mode` keeps the head mostly steady (best for a plain
# photo); `preprocess="crop"` frames the face the way the model expects;
# `size=512` is the sharper output. Flip still_mode off for full head motion.
DEFAULT_PARAMS: dict = {
    "preprocess": "crop",
    "still_mode": True,
    "size": 512,
}


def token() -> str:
    return os.environ.get("REPLICATE_API_TOKEN", "").strip()


def _data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


class ReplicateEngine:
    """Drives cjwbw/sadtalker through the Replicate API."""

    name = "sadtalker-replicate"

    def __init__(self, image_path: Path = IMAGE_PATH,
                 params: dict | None = None) -> None:
        self.image_path = Path(image_path)
        self.params = dict(DEFAULT_PARAMS if params is None else params)

    # ------------------------------------------------------------- protocol
    def available(self) -> bool:
        return replicate is not None and bool(token())

    def setup_hint(self) -> str:
        if self.available():
            return ""
        if replicate is None:
            return ("The `replicate` package is not installed. "
                    "Run: pip install -r requirements.txt")
        return ("REPLICATE_API_TOKEN is missing. Create a .env file in this "
                "project from .env.example with your token, then restart.")

    def submit(self, audio_path: Path, overrides: dict | None = None):
        if replicate is None:
            raise EngineUnavailable(
                "The `replicate` package is not installed. "
                "Run: pip install -r requirements.txt")
        if not token():
            raise EngineUnavailable(
                "REPLICATE_API_TOKEN is missing. Create a .env file in this "
                "project from .env.example, put your token from "
                "https://replicate.com/account/api-tokens in it, then "
                "restart the server.")
        if not self.image_path.is_file():
            raise EngineUnavailable(
                f"Avatar photo not found at {self.image_path}")

        params = dict(self.params)
        params.update(overrides or {})
        params["driven_audio"] = _data_uri(audio_path, "audio/wav")
        params["source_image"] = _data_uri(self.image_path, "image/jpeg")

        return replicate.predictions.create(model=MODEL, input=params)

    def poll(self, prediction_id: str):
        if replicate is None:
            raise EngineUnavailable("`replicate` package is not installed")
        return replicate.predictions.get(prediction_id)

    def output_url(self, prediction) -> str | None:
        """The rendered mp4 URL, or None while still processing."""
        out = prediction.output
        if isinstance(out, str):
            return out
        if isinstance(out, (list, tuple)) and out:
            return str(out[0])
        return None

    def download(self, url: str, dest: Path) -> Path:
        """Fetch the rendered video into the local output dir."""
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_bytes(1 << 16):
                    fh.write(chunk)
        return Path(dest)