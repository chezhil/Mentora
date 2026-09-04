import pytest
from utils_gesture import parse_gestures

def test_parse_gestures_no_tags():
    text = "Hello world! This is a test."
    clean_text, gestures = parse_gestures(text)
    assert clean_text == "Hello world! This is a test."
    assert len(gestures) == 0

def test_parse_gestures_single_tag():
    text = "Welcome! [smile] Today we learn about voltage."
    clean_text, gestures = parse_gestures(text)
    assert clean_text == "Welcome!  Today we learn about voltage."
    assert len(gestures) == 1
    assert gestures[0]["type"] == "smile"
    assert gestures[0]["index"] == 9

def test_parse_gestures_multiple_tags():
    text = "[nod] Yes, that makes sense. [point_board] Look at this equation. [smile]"
    clean_text, gestures = parse_gestures(text)
    assert clean_text == "Yes, that makes sense.  Look at this equation."
    assert len(gestures) == 3
    assert gestures[0]["type"] == "nod"
    assert gestures[0]["index"] == 0
    assert gestures[1]["type"] == "point_board"
    assert gestures[1]["index"] == 24
    assert gestures[2]["type"] == "smile"
    # index of smile is at the end of the clean text

def test_parse_gestures_invalid_tags():
    # Only alphanumeric and underscores are allowed.
    text = "This [invalid-tag] and [1] are not gestures, but [smile_2] is."
    clean_text, gestures = parse_gestures(text)
    # The regex in utils_gesture matches [1] and [smile_2] but not [invalid-tag]
    assert len(gestures) == 2
    assert gestures[0]["type"] == "1"
    assert gestures[1]["type"] == "smile_2"
    assert "invalid-tag" in clean_text
