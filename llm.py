"""Model access. One place that talks to the provider, everything else uses it.

Contract rule: the current SDK is `google-genai` (NOT google-generativeai).
Usage: set GROQ_API_KEY, or run ollama locally and set
AI_TEACHER_PROVIDER=ollama.

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

# Two providers, both speaking the OpenAI API: Groq (hosted, free tier) and
# Ollama (on this machine, no key). Gemini and the private "local" proxy were
# removed -- Gemini's default model never existed so every call 404'd, and
# "local" pointed at a port on one developer's laptop. One client, one code
# path, and nothing that only works on someone else's machine.
_PROVIDER_EARLY = os.environ.get("AI_TEACHER_PROVIDER", "groq").strip().lower()
_MODEL_DEFAULTS = {
    "groq": "openai/gpt-oss-120b",
    "ollama": "llama3.1:8b",
}
PROVIDERS = ("groq", "ollama")


def _pick_model() -> str:
    """Honour AI_TEACHER_MODEL, falling back to the provider's default."""
    default = _MODEL_DEFAULTS.get(_PROVIDER_EARLY, _MODEL_DEFAULTS["groq"])
    return os.environ.get("AI_TEACHER_MODEL", "").strip() or default


MODEL = _pick_model()

# Milliseconds. One segment is a few seconds normally; 60s is generous and
# still bounded. Override with AI_TEACHER_TIMEOUT_MS if a slow link needs it.
REQUEST_TIMEOUT_MS = int(os.environ.get("AI_TEACHER_TIMEOUT_MS", "60000"))

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


def configure(provider: str | None = None, api_key: str | None = None,
              model: str | None = None) -> None:
    """Change provider / key / model at runtime, correctly.

    PROVIDER, MODEL and the key are read once at import and the client is
    built once and cached. So setting os.environ["GROQ_API_KEY"] after import
    — which is what the web form's key field did — changed nothing at all:
    the request still went out on whatever was present at startup.

    app.py did the whole dance by hand, reaching into llm._openai_client.
    One place to get it right, so the two callers cannot drift apart.
    """
    global PROVIDER, MODEL, _openai_client

    if provider:
        provider = provider.strip().lower()
        if provider in PROVIDERS and provider != PROVIDER:
            PROVIDER = provider
            os.environ["AI_TEACHER_PROVIDER"] = provider

    if api_key and PROVIDER == "groq":
        os.environ["GROQ_API_KEY"] = api_key

    if model:
        MODEL = model
        os.environ["AI_TEACHER_MODEL"] = model

    # Both clients bake the key and base URL in at construction time.
    _openai_client = None


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
# Groq is the hosted option: a free tier measured in thousands of requests a
# day, capped on tokens rather than requests, serving a model good enough for
# teaching content and misconception naming. Ollama is the offline one: no
# key, no cap, whatever the machine can run.
#
#   AI_TEACHER_PROVIDER=groq     (default) needs GROQ_API_KEY
#   AI_TEACHER_PROVIDER=ollama             needs ollama running locally
#
# The default was "local", which points at http://127.0.0.1:8010 -- a private
# proxy that exists on one developer's machine and nowhere else. Every fresh
# clone therefore failed on its first LLM call with a bare connection-refused
# to a localhost port the README never mentions, and the comment here claimed
# Defaulting to groq means a clone with no key gets the actionable message in
# _openai_key() instead, pointing at the free tier the README recommends.
#
# Groq and Ollama both speak the OpenAI API, so one client covers both. The
# cache, the timeout and the JSON parsing are shared by every provider.
# ---------------------------------------------------------------------------

PROVIDER = os.environ.get("AI_TEACHER_PROVIDER", "groq").strip().lower()

DEFAULT_MODELS = dict(_MODEL_DEFAULTS)

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


def _complete(prompt: str) -> str:
    if _handler is not None:
        return _handler(prompt)
    replay = _mock_response(prompt)
    if replay is not None:
        return replay

    cached = _cache_get(prompt)
    if cached is not None:
        return cached

    if PROVIDER not in OPENAI_BASE_URLS:
        raise LLMError(
            f"Unknown provider {PROVIDER!r}. Set AI_TEACHER_PROVIDER to "
            "'groq' or 'ollama'."
        )
    text = _complete_openai(prompt)
    _cache_put(prompt, text)
    return text


def _parse_json(text: str) -> dict:
    if not text:
        raise LLMError("The model returned an empty response.")
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
#   Groq, tokens-per-day: resets on its own daily window -> waiting is futile
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

    # Transient server-side failures. A provider saying "currently
    # experiencing high demand" is asking to be asked again -- it is not a
    # quota, and it is not a bug in the prompt. Untreated, a single 503 spike
    # killed a teaching step outright and the student lost the segment.
    if any(k in message for k in ("503", "UNAVAILABLE", "overloaded",
                                  "high demand", "502", "504",
                                  "Internal error", "INTERNAL")):
        return 2.0

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