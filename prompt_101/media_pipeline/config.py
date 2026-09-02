"""Configuration for the media pipeline."""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── Directories ──
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

VISUAL_OUTPUT_DIR = OUTPUT_DIR / "visuals"
VISUAL_OUTPUT_DIR.mkdir(exist_ok=True)

TTS_OUTPUT_DIR = OUTPUT_DIR / "tts"
TTS_OUTPUT_DIR.mkdir(exist_ok=True)

AVATAR_OUTPUT_DIR = OUTPUT_DIR / "avatar"
AVATAR_OUTPUT_DIR.mkdir(exist_ok=True)

COMPOSE_OUTPUT_DIR = OUTPUT_DIR / "composed"
COMPOSE_OUTPUT_DIR.mkdir(exist_ok=True)

# ── Image Settings ──
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720
DPI = 100

# ── TTS Settings ──
# Provider: "piper" for development, "google" for final demo
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "piper")

# Piper settings
def _default_piper() -> str:
    """Piper ships into the venv's bin/, which is not on PATH when you run
    .venv/bin/streamlit directly. Look next to the running interpreter."""
    candidate = Path(sys.executable).parent / "piper"
    return str(candidate) if candidate.exists() else "piper"


PIPER_BIN = os.getenv("PIPER_BIN", _default_piper())
PIPER_MODEL_DIR = os.getenv("PIPER_MODEL_DIR", str(BASE_DIR / "piper_models"))

# Google Cloud TTS settings
GOOGLE_TTS_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
GOOGLE_TTS_VOICE_PREFIX = "en-US-Wavenet"

# ── Avatar Settings ──
# LivePortrait on Replicate
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
LIVEPORTRAIT_MODEL = "lucataco/liveportrait:d3bc6890b893"
MAX_AVATAR_DURATION_SECONDS = 60

# ── Visual Kinds ──
# The 7 supported visual types
VISUAL_KINDS = ["equation", "graph", "diagram", "timeline", "code", "concept_map", "none"]

# ── FFmpeg Settings ──
# Use imageio-ffmpeg for cross-platform compatibility
USE_IMAGEIO_FFMPEG = True


@dataclass
class PipelineConfig:
    """Central configuration for the media pipeline.
    
    Use this instead of scattered module-level constants.
    Pass an instance to pipeline functions for testability.
    """
    output_dir: Path = field(default_factory=lambda: Path(__file__).parent / "output")
    tts_provider: str = "piper"  # 'piper' or 'google'
    avatar_provider: str = "replicate"  # 'replicate' or 'none'
    max_segment_duration: int = 60
    image_width: int = 1280
    image_height: int = 720
    dpi: int = 100
    use_imageio_ffmpeg: bool = True

    def __post_init__(self):
        """Ensure output directories exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "visuals").mkdir(exist_ok=True)
        (self.output_dir / "tts").mkdir(exist_ok=True)
        (self.output_dir / "avatar").mkdir(exist_ok=True)
        (self.output_dir / "composed").mkdir(exist_ok=True)


# Singleton config instance
PIPELINE_CONFIG = PipelineConfig()
