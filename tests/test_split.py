"""Tests for split_audio."""

import wave
import os
from pathlib import Path
from unittest.mock import patch
from freebuff.voice.speak import split_audio


def _make_wav(path, duration_sec, sr=22050):
    """Create a WAV file of given duration."""
    n = int(duration_sec * sr)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(n * 2))


def test_split_short_file_returns_single(tmp_path):
    """File shorter than max_seconds returns single path."""
    wav = tmp_path / "short.wav"
    _make_wav(wav, 5.0)
    result = split_audio(wav, max_seconds=60)
    assert len(result) == 1
    assert result[0] == str(wav)
    assert os.path.exists(result[0])


def test_split_long_file(tmp_path):
    """File longer than max_seconds is split into chunks."""
    wav = tmp_path / "long.wav"
    _make_wav(wav, 25.0)
    out_dir = tmp_path / "split"
    result = split_audio(wav, max_seconds=10, output_dir=out_dir)
    assert len(result) == 3
    # Each chunk should exist and be valid WAV
    for p in result:
        assert os.path.exists(p)
        with wave.open(p, "rb") as wf:
            dur = wf.getnframes() / wf.getframerate()
            assert dur <= 10.1  # small tolerance


def test_split_preserves_audio_content(tmp_path):
    """Split chunks concatenated should equal original."""
    wav = tmp_path / "test.wav"
    _make_wav(wav, 15.0)
    out_dir = tmp_path / "out"
    parts = split_audio(wav, max_seconds=5, output_dir=out_dir)
    assert len(parts) == 3

    # Read all frames from parts
    all_frames = b""
    for p in parts:
        with wave.open(p, "rb") as wf:
            all_frames += wf.readframes(wf.getnframes())

    # Read original
    with wave.open(str(wav), "rb") as wf:
        orig_frames = wf.readframes(wf.getnframes())

    assert all_frames == orig_frames


def test_split_missing_file():
    """Missing input file raises FileNotFoundError."""
    import pytest
    with pytest.raises(FileNotFoundError):
        split_audio("nonexistent.wav")


def test_split_exact_boundary(tmp_path):
    """File exactly at max_seconds returns single path."""
    wav = tmp_path / "exact.wav"
    _make_wav(wav, 60.0)
    result = split_audio(wav, max_seconds=60)
    assert len(result) == 1


def test_split_empty_output_dir(tmp_path):
    """Output dir is created if it does not exist."""
    wav = tmp_path / "long.wav"
    _make_wav(wav, 15.0)
    out_dir = tmp_path / "new" / "dir"
    result = split_audio(wav, max_seconds=5, output_dir=out_dir)
    assert len(result) == 3
    assert out_dir.exists()