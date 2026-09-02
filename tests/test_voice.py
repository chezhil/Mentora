"""Tests for the voice module."""

import pytest
from unittest.mock import patch
from freebuff.voice.speak import speak


def test_empty_text_raises():
    with pytest.raises(ValueError):
        speak("")

def test_whitespace_raises():
    with pytest.raises(ValueError):
        speak("   ")

def test_cache_hit(tmp_path):
    cached = str(tmp_path / "cached.wav")
    with patch("freebuff.voice.speak.get_cached", return_value=cached):
        assert speak("hello", "en") == cached

def test_unknown_engine_raises(tmp_path):
    with patch("freebuff.voice.speak.get_config", return_value={"voice": {"engine": "bad"}}),              patch("freebuff.voice.speak.get_cached", return_value=None),              patch("freebuff.voice.speak.cache_path") as m:
        m.return_value = tmp_path / "out.wav"
        with pytest.raises(ValueError, match="Unknown engine"):
            speak("hello", "en")


def test_piper_missing_voice_raises():
    from freebuff.voice.piper_backend import synthesize_piper
    with pytest.raises(ValueError, match="No Piper voice"):
        synthesize_piper("hello", "xx", "/tmp/out.wav")



def test_to_ssml_wraps_in_speak_tags():
    from freebuff.voice.speak import to_ssml
    result = to_ssml("Hello world.")
    assert result.startswith("<speak>")
    assert result.endswith("</speak>")


def test_to_ssml_adds_sentence_pause():
    from freebuff.voice.speak import to_ssml
    result = to_ssml("Hello world. How are you?")
    assert "500ms" in result
    # Pause should be after the period
    assert '. <break time="500ms"/>' in result


def test_to_ssml_adds_comma_pause():
    from freebuff.voice.speak import to_ssml
    result = to_ssml("I am fine, thank you.")
    assert "300ms" in result
    assert ', <break time="300ms"/>' in result


def test_speak_ssml_produces_different_cache_key(tmp_path):
    from freebuff.voice.speak import speak
    from unittest.mock import patch
    # SSML and non-SSML should produce different cache keys
    with patch("freebuff.voice.speak.get_cached", return_value=None),          patch("freebuff.voice.speak.cache_path") as mock_cp,          patch("freebuff.voice.speak.get_config", return_value={"voice": {"engine": "bad"}}):
        mock_cp.return_value = tmp_path / "out.wav"
        # Non-SSML call
        try: speak("Hello.", use_ssml=False)
        except ValueError: pass
        call1 = mock_cp.call_args[0]
        # SSML call
        try: speak("Hello.", use_ssml=True)
        except ValueError: pass
        call2 = mock_cp.call_args[0]
        # Cache keys should differ because ssml_text differs
        assert call1 != call2


def test_speak_use_ssml_false_skips_ssml():
    from freebuff.voice.speak import speak, to_ssml
    from unittest.mock import patch
    plain = "Hello world."
    ssml = to_ssml(plain)
    with patch("freebuff.voice.speak.get_cached", return_value=None),          patch("freebuff.voice.speak.cache_path") as mock_cp,          patch("freebuff.voice.speak.get_config", return_value={"voice": {"engine": "bad"}}):
        mock_cp.return_value = "/tmp/out.wav"
        try: speak(plain, use_ssml=False)
        except ValueError: pass
        # Should cache with plain text, not SSML
        assert mock_cp.call_args[0][2] == plain
