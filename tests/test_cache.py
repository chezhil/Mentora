"""Tests for the unified cache module."""

import hashlib
from unittest.mock import patch
from freebuff.cache import cache_key, cache_path, get_cached


def test_cache_key_deterministic():
    assert cache_key("a", "b") == cache_key("a", "b")


def test_cache_key_different():
    assert cache_key("a", "b") != cache_key("c", "d")


def test_cache_key_is_sha256():
    expected = hashlib.sha256("a:b".encode()).hexdigest()
    assert cache_key("a", "b") == expected


def test_cache_path_section_and_ext(tmp_path):
    with patch("freebuff.cache.get_config") as m:
        m.return_value = {"test": {"output_dir": str(tmp_path)}}
        p = cache_path("test", ".wav", "hello")
        assert p.suffix == ".wav"
        assert str(tmp_path) in str(p)


def test_get_cached_miss(tmp_path):
    with patch("freebuff.cache.get_config") as m:
        m.return_value = {"test": {"output_dir": str(tmp_path)}}
        assert get_cached("test", ".wav", "x") is None


def test_get_cached_hit(tmp_path):
    with patch("freebuff.cache.get_config") as m:
        m.return_value = {"test": {"output_dir": str(tmp_path)}}
        p = cache_path("test", ".wav", "x")
        p.write_bytes(b"data")
        assert get_cached("test", ".wav", "x") == str(p)
