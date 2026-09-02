"""Tests for the avatar module."""

import pytest
from unittest.mock import patch
from freebuff.avatar.render_avatar import render_avatar
from freebuff.voice.speak import audio_duration
import wave


def _make_wav(path, duration_sec=5.0, sr=22050):
    n = int(duration_sec * sr)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(n * 2))


def testaudio_duration(tmp_path):
    wav = tmp_path / "test.wav"
    _make_wav(wav, 3.0)
    assert abs(audio_duration(wav) - 3.0) < 0.1


def test_60s_guard(tmp_path):
    wav = tmp_path / "long.wav"
    _make_wav(wav, 61.0)
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    with pytest.raises(ValueError, match="must be <="):
        render_avatar(wav, photo)


def test_missing_audio():
    with pytest.raises(FileNotFoundError, match="Audio"):
        render_avatar("nope.wav", "nope.jpg")


def test_missing_photo(tmp_path):
    wav = tmp_path / "a.wav"
    _make_wav(wav)
    with pytest.raises(FileNotFoundError, match="Photo"):
        render_avatar(wav, "nope.jpg")


def test_cache_hit(tmp_path):
    wav = tmp_path / "a.wav"
    _make_wav(wav)
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    cached = str(tmp_path / "cached.mp4")
    with patch("freebuff.avatar.render_avatar.get_cached", return_value=cached):
        assert render_avatar(wav, photo) == cached


def test_unknown_backend():
    from freebuff.avatar.render_avatar import _get_backend
    with pytest.raises(ValueError, match="Unknown"):
        _get_backend("bad/model")
