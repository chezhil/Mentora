"""Gemini access. One place that talks to the SDK, everything else uses it.

Contract rule: the current SDK is `google-genai` (NOT google-generativeai).
Usage: set GEMINI_API_KEY (or GOOGLE_API_KEY) as an environment variable.

For offline testing without an API key, call `set_handler(fn)` with a
function that maps a prompt to its JSON text. Tests use this.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable

from google import genai
from google.genai import types

_PROVIDER_EARLY = os.environ.get("AI_TEACHER_PROVIDER", "gemini").strip().lower()
_MODEL_DEFAULTS = {
    "gemini": "gemini-3.6-flash",
    "groq": "openai/gpt-oss-120b",
    "ollama": "llama3.1:8b",
}
_MODEL_PREFIX = {"gemini": ("gemini",)}


def _pick_model() -> str:
    """Honour AI_TEACHER_MODEL, but not when it belongs to another provider.

    A model id left in .env from a previous provider produces a 404 that reads
    like the provider is broken. It is not — it is the wrong model name. So a
    mismatch falls back to the provider's default rather than failing.
    """
    default = _MODEL_DEFAULTS.get(_PROVIDER_EARLY, "gemini-3.6-flash")
    wanted = os.environ.get("AI_TEACHER_MODEL", "").strip()
    if not wanted:
        return default
    prefixes = _MODEL_PREFIX.get(_PROVIDER_EARLY)
    if prefixes and not wanted.startswith(prefixes):
        return default
    if _PROVIDER_EARLY != "gemini" and wanted.startswith("gemini"):
        return default
    return wanted


MODEL = _pick_model()

# Milliseconds. One segment is a few seconds normally; 60s is generous and
# still bounded. Override with AI_TEACHER_TIMEOUT_MS if a slow link needs it.
REQUEST_TIMEOUT_MS = int(os.environ.get("AI_TEACHER_TIMEOUT_MS", "60000"))
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


# ---------------------------------------------------------------------------
# Response cache
#
# The free tier is 20 requests PER DAY per key per model, and one lesson costs
# 10 to 15. Without this, rehearsing a demo twice in a day is impossible.
#
# Keyed on the exact prompt AND model, so editing a prompt or switching model
# invalidates by construction — there is no stale-cache trap. A cached run
# costs nothing and returns instantly, which also makes rehearsal pleasant.
#
# AI_TEACHER_CACHE=0 disables it. AI_TEACHER_CACHE=<dir> moves it.
# ---------------------------------------------------------------------------

_CACHE_SETTING = os.environ.get("AI_TEACHER_CACHE", "")
CACHE_DIR = (
    None if _CACHE_SETTING == "0"
    else Path(_CACHE_SETTING or ".cache/llm")
)


def _cache_key(prompt: str) -> str:
    return hashlib.sha256(f"{MODEL}\x00{prompt}".encode("utf-8")).hexdigest()[:32]


def _cache_get(prompt: str) -> str | None:
    if CACHE_DIR is None:
        return None
    f = CACHE_DIR / f"{_cache_key(prompt)}.txt"
    try:
        return f.read_text(encoding="utf-8")
    except Exception:
        return None


def _cache_put(prompt: str, response: str) -> None:
    if CACHE_DIR is None or not response:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{_cache_key(prompt)}.txt").write_text(
            response, encoding="utf-8")
    except Exception:
        pass          # a cache failure must never break a lesson


def cache_stats() -> dict:
    """For the UI: how much of a lesson can be replayed for free."""
    if CACHE_DIR is None or not CACHE_DIR.is_dir():
        return {"enabled": CACHE_DIR is not None, "entries": 0}
    return {"enabled": True, "entries": len(list(CACHE_DIR.glob("*.txt")))}


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


# ---------------------------------------------------------------------------
# Provider
#
# Gemini's free tier is 20 requests per day, per key, per model. One lesson
# costs 22 — measured — so a single lesson cannot finish on one key. Groq's
# free tier is thousands a day and serves Llama 3.3 70B, which is close enough
# in quality for teaching content and misconception naming.
#
#   AI_TEACHER_PROVIDER=gemini   (default) needs GEMINI_API_KEY
#   AI_TEACHER_PROVIDER=groq               needs GROQ_API_KEY
#   AI_TEACHER_PROVIDER=ollama             needs ollama running locally
#
# Groq and Ollama both speak the OpenAI API, so one client covers both. The
# cache, the timeout and the JSON parsing are shared by every provider.
# ---------------------------------------------------------------------------

PROVIDER = os.environ.get("AI_TEACHER_PROVIDER", "gemini").strip().lower()

DEFAULT_MODELS = {
    "gemini": "gemini-3.6-flash",
    "groq": "openai/gpt-oss-120b",
    "ollama": "llama3.1:8b",
}

OPENAI_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "ollama": os.environ.get("OLLAMA_HOST", "http://localhost:11434") + "/v1",
}

_openai_client = None


def _openai_key() -> str:
    if PROVIDER == "groq":
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise LLMError(
                "No Groq API key found. Create a free one at "
                "console.groq.com/keys and set GROQ_API_KEY, or paste it into "
                "the APIs panel in the sidebar."
            )
        return key
    return "ollama"          # Ollama ignores the key but the SDK wants one


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(
            api_key=_openai_key(),
            base_url=OPENAI_BASE_URLS[PROVIDER],
            timeout=REQUEST_TIMEOUT_MS / 1000,
            max_retries=1,          # a daily-quota 429 will not recover
        )
    return _openai_client


def _complete_openai(prompt: str) -> str:
    resp = _get_openai_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.4,
        max_tokens=8192,
    )
    return resp.choices[0].message.content or ""


def _get_client():
    global _client
    if _client is None:
        if not API_KEY:
            raise LLMError(
                "No Gemini API key found. Set the environment variable "
                "GEMINI_API_KEY (or GOOGLE_API_KEY) and try again. "
                "Each team member uses their own key."
            )
        # A request with no timeout hangs forever. It did: the app sat on
        # plan() with an open socket to Google, 0% CPU, and no way out but
        # killing the server. On demo day that is fatal, so cap it.
        _client = genai.Client(
            api_key=API_KEY,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_MS,
                # Retry genuinely transient server errors, but NOT 429.
                #
                # The SDK retries 429 by default with exponential backoff. Our
                # 429 is a DAILY quota — it will not recover in seconds, so the
                # retries just sit there. That is what "the server got stuck
                # after I clicked start lesson": an open socket to Google, 0%
                # CPU, and no error, when the actual response had come back in
                # 0.6 seconds saying the quota was gone.
                #
                # Excluding 429 lets it surface at once, so the app can say so
                # and offer another key.
                retry_options=types.HttpRetryOptions(
                    attempts=2,
                    initial_delay=1.0,
                    max_delay=4.0,
                    http_status_codes=[500, 502, 503, 504],
                ),
            ),
        )
    return _client


def _complete(prompt: str) -> str:
    if _handler is not None:
        return _handler(prompt)
    replay = _mock_response(prompt)
    if replay is not None:
        return replay

    cached = _cache_get(prompt)
    if cached is not None:
        return cached

    if PROVIDER in OPENAI_BASE_URLS:
        text = _complete_openai(prompt)
        _cache_put(prompt, text)
        return text

    resp = _get_client().models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
            max_output_tokens=8192,
        ),
    )
    _cache_put(prompt, resp.text)
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


# A 429 is two completely different problems wearing the same number.
#
#   Groq, tokens-per-minute:  "Please try again in 4.24s"   -> waiting works
#   Gemini, requests-per-day: resets at midnight US Pacific -> waiting is futile
#
# Both used to end the lesson identically, and the message said "daily quota
# exhausted" either way — so a four-second hiccup mid-demo looked like the key
# was spent for the day. Wait out the short ones; surface the long ones at once.
# Groq writes the wait in whichever unit is shortest: "82.499999ms" as
# readily as "22.44s". Matching only seconds meant an 82-MILLISECOND throttle
# ended the lesson.
_RETRY_AFTER = re.compile(r"(?:retry|try again) in ([\d.]+)\s*(ms|s)\b", re.I)
# 30, because Groq's tokens-per-minute throttle asks for up to ~23s in
# practice and a 20s ceiling declined to wait for exactly the case this
# exists to absorb. Capped at two waits, so a genuinely stuck provider
# still surfaces rather than hanging the lesson.
MAX_RATE_WAIT = float(os.environ.get("AI_TEACHER_MAX_RATE_WAIT", "30"))


def _retry_delay(exc: Exception) -> float | None:
    """Seconds to wait, or None if waiting will not help."""
    message = str(exc)
    if "429" not in message and "RESOURCE_EXHAUSTED" not in message:
        return None
    # A daily cap does not recover, however long we sit here.
    if "PerDay" in message or "free_tier_requests" in message or "per day" in message.lower():
        return None
    found = _RETRY_AFTER.search(message)
    if not found:
        return None
    delay = float(found.group(1))
    if found.group(2).lower() == "ms":
        delay /= 1000.0
    return delay + 0.5 if delay <= MAX_RATE_WAIT else None


def generate_json(prompt: str, tries: int = 2) -> dict:
    """Ask the model for a JSON object.

    Retries once on unparseable output, and separately waits out a
    per-minute rate limit, which is a different failure with a different fix.
    """
    import time

    last: Exception | None = None
    rate_waits = 0
    attempt = 0
    while attempt < tries:
        try:
            text = _complete(prompt)
            return _parse_json(text)
        except LLMError as exc:
            last = exc
            attempt += 1
        except Exception as exc:
            delay = _retry_delay(exc)
            if delay is None or rate_waits >= 2:
                raise
            rate_waits += 1
            time.sleep(delay)          # does not count as an attempt
    assert last is not None
    raise last