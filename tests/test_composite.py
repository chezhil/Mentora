"""Tests for compose and stitch."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from freebuff.composite.compose import compose
from freebuff.composite.stitch import stitch


def test_missing_visual():
    with pytest.raises(FileNotFoundError, match="Visual"):
        compose("nope.png", "a.wav", "out.mp4")


def test_missing_audio(tmp_path):
    p = tmp_path / "v.png"; p.write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="Audio"):
        compose(p, "nope.wav", "out.mp4")


def test_missing_avatar(tmp_path):
    v = tmp_path / "v.png"; v.write_bytes(b"x")
    a = tmp_path / "a.wav"; a.write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="Avatar"):
        compose(v, a, "out.mp4", avatar_mp4="nope.mp4")


def test_compose_visual_only(tmp_path):
    v = tmp_path / "v.png"; v.write_bytes(b"x")
    a = tmp_path / "a.wav"; a.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    mock_r = MagicMock(returncode=0)
    with patch("freebuff.composite.compose.get_ffmpeg", return_value="ff"),              patch("freebuff.composite.compose.subprocess.run", return_value=mock_r),              patch("freebuff.composite.compose.get_config", return_value={"composite": {"pixel_format": "yuv420p"}}):
        result = compose(v, a, out)
        assert result == str(out)


def test_stitch_empty():
    with pytest.raises(ValueError):
        stitch([], "out.mp4")


def test_stitch_single(tmp_path):
    seg = tmp_path / "seg.mp4"; seg.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    result = stitch([seg], out)
    assert Path(result).exists()


def test_stitch_multi(tmp_path):
    s1 = tmp_path / "s1.mp4"; s1.write_bytes(b"x")
    s2 = tmp_path / "s2.mp4"; s2.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    mock_r = MagicMock(returncode=0)
    with patch("freebuff.composite.stitch.get_ffmpeg", return_value="ff"),              patch("freebuff.composite.stitch.subprocess.run", return_value=mock_r):
        result = stitch([s1, s2], out)
        assert result == str(out)



def test_compose_loudnorm_included(tmp_path):
    """loudnorm filter is included when normalize_audio=True (default)."""
    v = tmp_path / "v.png"; v.write_bytes(b"x")
    a = tmp_path / "a.wav"; a.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    mock_r = MagicMock(returncode=0)
    with patch("freebuff.composite.compose.get_ffmpeg", return_value="ff"),          patch("freebuff.composite.compose.subprocess.run", return_value=mock_r) as mock_run,          patch("freebuff.composite.compose.get_config", return_value={"composite": {"pixel_format": "yuv420p"}}):
        compose(v, a, out, normalize_audio=True)
        cmd = mock_run.call_args[0][0]
        assert "-af" in cmd
        af_idx = cmd.index("-af")
        assert "loudnorm=I=-16:TP=-1.5:LRA=11" in cmd[af_idx + 1]


def test_compose_loudnorm_excluded(tmp_path):
    """loudnorm filter is excluded when normalize_audio=False."""
    v = tmp_path / "v.png"; v.write_bytes(b"x")
    a = tmp_path / "a.wav"; a.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    mock_r = MagicMock(returncode=0)
    with patch("freebuff.composite.compose.get_ffmpeg", return_value="ff"),          patch("freebuff.composite.compose.subprocess.run", return_value=mock_r) as mock_run,          patch("freebuff.composite.compose.get_config", return_value={"composite": {"pixel_format": "yuv420p"}}):
        compose(v, a, out, normalize_audio=False)
        cmd = mock_run.call_args[0][0]
        # No -af flag when normalization is off and no subtitle
        af_args = [cmd[i] for i in range(len(cmd)) if cmd[i] == "-af"]
        assert len(af_args) == 0
