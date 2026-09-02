"""Hash-based cache for generated media files."""

from __future__ import annotations
import hashlib
from pathlib import Path
from freebuff.config import get_config


def _cache_dir(section):
    cfg = get_config().get(section, {})
    d = Path(cfg.get("output_dir", f"cache/{section}"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(*parts):
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


def cache_path(section, ext, *parts):
    return _cache_dir(section) / f"{cache_key(*parts)}{ext}"


def get_cached(section, ext, *parts):
    p = cache_path(section, ext, *parts)
    return str(p) if p.exists() else None
