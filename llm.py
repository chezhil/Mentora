"""Gemini access. One place that talks to the SDK, everything else uses it.

Contract rule: the current SDK is `google-genai` (NOT google-generativeai).
Usage: set GEMINI_API_KEY (or GOOGLE_API_KEY) as an environment variable.

For offline testing without an API key, call `set_handler(fn)` with a
function that maps a prompt to its JSON text. Tests use this.
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable

from google import genai
from google.genai import types

MODEL = os.environ.get("AI_TEACHER_MODEL", "gemini-3.6-flash")
API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

_client = None
_handler: Callable[[str], str] | None = None
_mock: dict | None = None


class LLMError(RuntimeError):
    pass


def set_handler(fn: Callable[[str], str] | None) -> None:
    """Install a fake 'LLM' for tests: fn(prompt) -> raw text response."""
    global _handler
    _handler = fn


def _mock_response(prompt: str) -> str | None:
    """Offline replay: AI_TEACHER_MOCK=<json file> maps a prompt substring
    to the JSON response the model should 'return'. Lets the contract's
    `python -m ... fixtures/...` commands run with no API key."""
    global _mock
    path = os.environ.get("AI_TEACHER_MOCK")
    if not path:
        return None
    if _mock is None:
        with open(path, encoding="utf-8") as f:
            _mock = json.load(f)
    for key, value in _mock.items():
        if key in prompt:
            return value if isinstance(value, str) else json.dumps(value)
    return None


def _get_client():
    global _client
    if _client is None:
        if not API_KEY:
            raise LLMError(
                "No Gemini API key found. Set the environment variable "
                "GEMINI_API_KEY (or GOOGLE_API_KEY) and try again. "
                "Each team member uses their own key."
            )
        _client = genai.Client(api_key=API_KEY)
    return _client


def _complete(prompt: str) -> str:
    if _handler is not None:
        return _handler(prompt)
    replay = _mock_response(prompt)
    if replay is not None:
        return replay
    resp = _get_client().models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
            max_output_tokens=8192,
        ),
    )
    return resp.text


def _parse_json(text: str) -> dict:
    if not text:
        raise LLMError("Gemini returned an empty response.")
    text = text.strip()
    if re.match(r"^```", text):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise LLMError("No JSON object found in model response.")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except json.JSONDecodeError as exc:
        raise LLMError(f"Could not parse model output as JSON: {exc}") from exc


def generate_json(prompt: str, tries: int = 2) -> dict:
    """Ask Gemini for a JSON object. Retries once if the output is bad."""
    last: LLMError | None = None
    for attempt in range(tries):
        try:
            text = _complete(prompt)
            return _parse_json(text)
        except LLMError as exc:
            last = exc
    assert last is not None
    raise last