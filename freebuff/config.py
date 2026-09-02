"""Configuration loader for the media pipeline.

Loads config.yaml and allows environment variable overrides.
All modules import get_config() to access settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Project root is one level up from freebuff/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "config.yaml"

_config_cache: dict[str, Any] | None = None


def get_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load and cache the configuration.

    Args:
        config_path: Optional path to a config.yaml file.
                     Defaults to the project-root config.yaml.

    Returns:
        Merged configuration dictionary.
    """
    global _config_cache
    if _config_cache is not None and config_path is None:
        return _config_cache

    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Environment variable overrides
    _apply_env_overrides(cfg)

    _config_cache = cfg
    return cfg


def _apply_env_overrides(cfg: dict[str, Any]) -> None:
    """Override config values from environment variables.

    Convention: FREEBUFF_<SECTION>_<KEY> (uppercase, underscores).
    Example: FREEBUFF_VOICE_ENGINE=cloud_tts
    """
    env_prefix = "FREEBUFF_"
    for key, value in os.environ.items():
        if not key.startswith(env_prefix):
            continue
        parts = key[len(env_prefix) :].lower().split("_", 1)
        if len(parts) == 2:
            section, field = parts
            if section in cfg and isinstance(cfg[section], dict):
                cfg[section][field] = value
