"""Shared state helpers — extracted from app.py to avoid circular imports.

Screen modules import from here; app.py re-exports from here.
"""

import os
import re

import streamlit as st

import orchestrator as orch
from shared import languages
from ui.i18n import t

UPLOAD_DIR = "out/uploads"


def _lang() -> str:
    """The language the interface is currently drawn in."""
    return st.session_state.get("ui_lang", languages.DEFAULT)


def _t(key: str) -> str:
    return t(key, _lang())


def _set_language(code: str) -> None:
    """Switch the interface, everywhere, on the next frame."""
    st.session_state.ui_lang = code
    # Bridge: persist to DB so the brutalist UI picks it up
    try:
        import history.db as _hdb
        _hdb.set_preferences(st.session_state.student_id, {"language": code})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Double-click protection
# ---------------------------------------------------------------------------

def _busy() -> bool:
    return st.session_state.get("busy") is not None


def _claim(token: str) -> bool:
    """Claim the right to run `token` once. False if busy or already done."""
    if _busy():
        return False
    if token in st.session_state.setdefault("done_tokens", set()):
        return False
    st.session_state.busy = token
    return True


def _release(token: str, completed: bool) -> None:
    st.session_state.busy = None
    if completed:
        st.session_state.done_tokens.add(token)


def _friendly(exc: Exception) -> str:
    """Turn provider errors into something readable, and open the APIs panel."""
    msg = str(exc)
    st.session_state.api_panel_open = True

    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        per_day = ("PerDay" in msg or "free_tier_requests" in msg
                   or "per day" in msg.lower())
        retry = re.search(r"(?:retry|try again) in ([\d.]+)\s*s", msg, re.I)

        if not per_day and retry:
            return (
                f"**Rate limited for {float(retry.group(1)):.0f} seconds** — "
                f"this is a per-minute limit, not your daily quota. Press the "
                f"button again in a moment and it will go through."
            )
        return (
            "**Quota exhausted.**"
            + (" This is the *daily* free-tier cap, which resets on its own "
               "window — not in a few seconds." if per_day else "")
            + "\n\nFix it in **⚙️ APIs** in the sidebar: paste another team "
              "member's Groq key, switch provider to Ollama (local, no cap), "
              "or switch on *Offline mode*."
        )
    if "API key not valid" in msg or "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg:
        return ("**The provider rejected that API key.** Paste a valid one in "
                "**⚙️ APIs** in the sidebar. Groq keys start with `gsk_`.")
    if "no longer available" in msg or "NOT_FOUND" in msg:
        return (f"**That model is not available to this key.** Pick a "
                f"different one in **⚙️ APIs** in the sidebar.\n\n`{msg[:200]}`")
    if "No Groq API key" in msg:
        return ("**No Groq API key set.** Add one in **⚙️ APIs** in the "
                "sidebar, switch provider to Ollama, or switch on *Offline mode*.")
    if "deadline" in msg.lower() or "timeout" in msg.lower():
        return "**The model timed out.** Try again, or use *Offline mode* in **⚙️ APIs**."
    return f"**{type(exc).__name__}**\n\n```\n{msg[:400]}\n```"


def save_upload(uploaded) -> str | None:
    if uploaded is None:
        return None
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, uploaded.name)
    with open(path, "wb") as f:
        f.write(uploaded.getbuffer())
    return path
