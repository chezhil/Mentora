"""Mentora — the student-facing app. Chezhil owns this file.

    streamlit run app.py

STREAMLIT, IN ONE PARAGRAPH: this whole file re-runs top to bottom on every
single interaction. Nothing survives a rerun except st.session_state. So all
real state lives in st.session_state, and every branch below has to work when
the script starts again from line 1.
"""

import os
import re
from datetime import datetime, timezone

import streamlit as st

try:                       # load .env if present; it holds GROQ_API_KEY
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import orchestrator as orch
import ui
import ui.animations as animations
import wiring
from screens import exam as exam_screen
from screens import flashcards as flashcards_screen
from screens import learning as learning_screen
from screens import library as library_screen
from screens import path as path_screen
from screens import planner as planner_screen
from screens import quiz as quiz_screen
from shared import languages
from ui.i18n import t

# Shared state helpers — the single source of _lang, _t, _busy, etc.
# Screen modules import from here too, which avoids circular imports.
from screens._state import (
    _lang, _t, _set_language, _busy, _claim, _release, _friendly,
    save_upload, UPLOAD_DIR,
)

# Screen imports
from screens.setup import screen_setup
from screens.lesson import screen_lesson
from screens.history import screen_history
from screens.report import screen_report

# Every language Mentora offers is defined in shared/languages.py — one place
# holding its voice, its font and its script direction, because a language
# added to only two of those three is how we shipped Tamil that rendered as
# empty boxes and Kannada that narrated in silence.
LANGUAGES = {code: languages.label(code) for code in languages.codes()}

ROLES = ("student", "teacher")

st.set_page_config(
    page_title="Mentora — AI Teacher", page_icon="🎓", layout="wide",
    menu_items={
        "About": "**Mentora** — AI Teacher.\n\nTo change the API key "
                 "or switch to offline mode, use the **⚙️ APIs** panel at the "
                 "bottom of the sidebar. (Streamlit does not allow custom "
                 "controls in this menu.)",
    },
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def init_state() -> None:
    st.session_state.setdefault("phase", "setup")
    st.session_state.setdefault("session", None)
    st.session_state.setdefault("segment", None)
    st.session_state.setdefault("report", None)
    st.session_state.setdefault("last_feedback", None)
    st.session_state.setdefault("student_id", "student")
    st.session_state.setdefault("ui_lang", languages.DEFAULT)
    st.session_state.setdefault("role", "student")
    st.session_state.setdefault("busy", None)
    st.session_state.setdefault("last_followup", None)
    st.session_state.setdefault("done_tokens", set())

    # Bridge: read preferences from DB on first run, so settings saved
    # on the brutalist /config page take effect here.
    if "_db_prefs_loaded" not in st.session_state:
        st.session_state._db_prefs_loaded = True
        try:
            import history.db as _hdb
            sid = st.session_state.student_id
            prefs = _hdb.get_preferences(sid)
            if prefs.get("language") and prefs["language"] != languages.DEFAULT:
                st.session_state.ui_lang = prefs["language"]
            if prefs.get("difficulty"):
                st.session_state.setdefault("level", prefs["difficulty"])
            if prefs.get("persona"):
                st.session_state.setdefault("persona", prefs["persona"])
        except Exception:
            pass


init_state()

# Styling comes from ui/style.css and .streamlit/config.toml; this is the only
# line joining presentation to the rest of app.py.
ui.apply_theme(_lang(), hide_nav=True)
animations.inject_animations()


# ---------------------------------------------------------------------------
# API Panel — swap the API key without restarting
# ---------------------------------------------------------------------------

ENV_PATH = ".env"

# Two providers: Groq hosted, Ollama on this machine. Gemini was removed --
# its configured model never existed, so every call 404'd -- and with it the
# private "local" proxy, which only ever resolved on one developer's laptop.
PROVIDERS = ["groq", "ollama"]

PROVIDER_MODELS = {
    "groq": ['openai/gpt-oss-120b', 'qwen/qwen3.8-27b', 'groq/compound', 'groq/compound-mini', 'openai/gpt-oss-20b'],
    "ollama": ["llama3.1:8b", "qwen2.5:7b", "gemma2:9b"],
}

PROVIDER_KEY_ENV = {"groq": "GROQ_API_KEY"}


def _mask(value: str | None) -> str:
    if not value:
        return "not set"
    return f"{value[:6]}…{value[-4:]}" if len(value) > 14 else "set"


def _write_env(updates: dict) -> None:
    """Persist keys to .env, which is gitignored. Never goes near the repo."""
    lines, seen = [], set()
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH).read().splitlines():
            k = line.split("=", 1)[0].strip()
            if k in updates:
                lines.append(f"{k}={updates[k]}")
                seen.add(k)
            else:
                lines.append(line)
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    with open(ENV_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(ENV_PATH, 0o600)


def api_panel() -> None:
    """Swap the API key without restarting — for when quota runs out mid-demo."""
    import llm

    opened = st.session_state.pop("api_panel_open", False)
    with st.sidebar.expander("⚙️ APIs", expanded=opened):
        offline = os.environ.get("AI_TEACHER_MOCK") is not None
        avatar_mod = getattr(wiring.render_avatar, "__module__", "?")
        if avatar_mod.startswith("local_avatar"):
            avatar_line = "🟢 local Wav2Lip (free, no account needed)"
        elif "prompt_101" in avatar_mod:
            avatar_line = "🟡 Replicate — needs a paid token"
        else:
            avatar_line = "🟡 placeholder (still image)"

        active_key = os.environ.get("GROQ_API_KEY", "") if llm.PROVIDER == "groq" else ""
        active_endpoint = llm.OPENAI_BASE_URLS.get(llm.PROVIDER, llm.PROVIDER)
        st.caption(
            f"Provider: `{llm.PROVIDER}`  \n"
            f"Model: `{llm.MODEL}`  \n"
            f"Endpoint: `{active_endpoint}`  \n"
            f"Key: `{_mask(active_key)}`  \n"
            f"Mode: {'🟡 offline (mock)' if offline else '🟢 live'}  \n"
            f"Avatar: {avatar_line}"
        )

        provider = st.selectbox(
            "Provider", PROVIDERS,
            index=PROVIDERS.index(llm.PROVIDER) if llm.PROVIDER in PROVIDERS else 0,
            help="Groq is a hosted API and needs a free key. "
                 "Ollama runs on this machine and needs none."
        )

        key_env = PROVIDER_KEY_ENV.get(provider)
        key = ""
        if key_env:
            key = st.text_input(
                f"{provider.title()} API key", type="password",
                placeholder="free key from console.groq.com/keys")
        else:
            st.caption("Ollama needs no key — just `ollama serve` running.")

        models = PROVIDER_MODELS.get(provider, PROVIDER_MODELS["groq"])
        model = st.selectbox(
            "Model", models,
            index=models.index(llm.MODEL) if llm.MODEL in models else 0)


        new_offline = st.toggle("Offline mode (no API calls)", value=offline,
                                help="Replays canned answers. Free, but every "
                                     "answer is marked wrong.")
        remember = st.checkbox("Remember in .env", value=True,
                               help=".env is gitignored — it never reaches GitHub.")

        if st.button("Apply", type="primary"):
            saved = {}
            if provider != llm.PROVIDER:
                saved["AI_TEACHER_PROVIDER"] = provider
            if key and key_env:
                saved[key_env] = key

            if model != llm.MODEL:
                saved["AI_TEACHER_MODEL"] = model
            # One call: it sets the globals, updates the environment AND drops
            # both cached SDK clients, which hold the old key and base URL.
            llm.configure(provider=provider, api_key=key or None, model=model)
            if new_offline:
                os.environ["AI_TEACHER_MOCK"] = "mocks/fixture_mock.json"
            else:
                os.environ.pop("AI_TEACHER_MOCK", None)
            llm._mock = None
            if remember and saved:
                try:
                    _write_env(saved)
                except Exception as exc:
                    st.warning(f"Could not write .env: {exc}")
            st.success("Applied.")
            st.rerun()

        if st.button("Test key (uses 1 request)"):
            try:
                llm.generate_json('Reply with JSON only: {"ok": true}')
                st.success(f"{llm.MODEL} responded.")
            except Exception as exc:
                st.error(_friendly(exc))


# ---------------------------------------------------------------------------
# Adaptation Panel — sidebar showing Pair B's inner state
# ---------------------------------------------------------------------------

def _asset_warning() -> None:
    """Say plainly when the downloaded assets are missing."""
    missing = []
    try:
        import local_avatar
        if not local_avatar.available():
            missing.append("avatar weights (talking head)")
    except Exception:
        missing.append("avatar weights (talking head)")

    try:
        from pathlib import Path
        from prompt_101.media_pipeline.config import PIPER_MODEL_DIR
        if not list(Path(PIPER_MODEL_DIR).glob("*.onnx")):
            missing.append("Piper voices (en, hi, te narration)")
    except Exception:
        pass

    if missing:
        st.sidebar.warning(
            "Missing downloads: " + "; ".join(missing) +
            ".\n\nRun `python setup_assets.py` — about 500MB, once."
        )


def adaptation_panel() -> None:
    st.sidebar.header(_t("panel.title"))

    session = st.session_state.session
    if session is None:
        st.sidebar.caption(_t("panel.starts_with_lesson"))
        return

    panel = orch.runtime(session).panel

    if panel.concept_name:
        st.sidebar.caption(_t("panel.now_teaching"))
        st.sidebar.write(f"**{panel.concept_name}**")

    if panel.retrieved:
        pages = ", ".join(str(p) for p in panel.grounded_pages) or "—"
        st.sidebar.caption(_t("panel.grounding"))
        st.sidebar.write(f"{panel.retrieved} chunks · pages {pages}")
    elif session.doc_id:
        st.sidebar.caption(_t("panel.grounding"))
        st.sidebar.write("nothing relevant in the document")

    st.sidebar.divider()

    if not panel.answered:
        st.sidebar.caption(_t("panel.waiting"))
    else:
        verdict = _t("panel.correct") if panel.correct else _t("panel.incorrect")
        st.sidebar.write(f"**{_t('panel.answer')}:** {verdict}")
        if panel.misconception:
            st.sidebar.write(f"**{_t('panel.misconception')}**")
            st.sidebar.warning(panel.misconception)
        if panel.action_taken:
            line = f"**{_t('panel.action')}:** {panel.action_taken}"
            if panel.escalated:
                line += f"  \n_(Pair B said {panel.action_from_pair_b}; "
                line += f"escalated on attempt {panel.attempt})_"
            st.sidebar.write(line)
        if panel.analogy:
            st.sidebar.write(f"**{_t('panel.analogy')}:** {panel.analogy}")
        if panel.difficulty:
            st.sidebar.write(f"**{_t('panel.difficulty')}:** {panel.difficulty}")
        if panel.attempt:
            st.sidebar.write(f"**{_t('panel.attempt')}:** {panel.attempt}")

    st.sidebar.divider()
    st.sidebar.caption("Module status")
    for pair, state in wiring.summary().items():
        icon = "🟢" if state == "LIVE" else "🟡"
        st.sidebar.write(f"{icon} {pair} — {state}")

    _asset_warning()


# ---------------------------------------------------------------------------
# Main routing

# ---------------------------------------------------------------------------

adaptation_panel()
api_panel()

# Guard: if phase is past setup but session was cleared, reset gracefully.
if st.session_state.phase != "setup" and st.session_state.session is None:
    st.session_state.phase = "setup"
    init_state()
    st.rerun()

if st.session_state.phase == "setup":
    screen_setup()
else:
    names = ["nav.lesson", "nav.history", "nav.quiz", "nav.flashcards",
             "nav.path", "nav.report", "nav.exam", "nav.learning",
             "nav.library", "nav.planner"]
    if st.session_state.get("role") == "teacher":
        names.append("nav.classroom")

    tabs = dict(zip(names, st.tabs([_t(n) for n in names])))

    with tabs["nav.lesson"]:
        screen_lesson()
    with tabs["nav.history"]:
        screen_history()
    with tabs["nav.quiz"]:
        quiz_screen.render_quiz(st.session_state.session, _lang())
    with tabs["nav.flashcards"]:
        flashcards_screen.render_flashcards(st.session_state.session, _lang())
    with tabs["nav.path"]:
        path_screen.render_path(st.session_state.session, _lang())
    with tabs["nav.report"]:
        screen_report()
    with tabs["nav.exam"]:
        exam_screen.render_exam(st.session_state.session, _lang())
    with tabs["nav.learning"]:
        learning_screen.render_learning(st.session_state.session, _lang())
    with tabs["nav.library"]:
        library_screen.render_library(st.session_state.session, _lang())
    with tabs["nav.planner"]:
        planner_screen.render_planner(st.session_state.session, _lang())
    if "nav.classroom" in tabs:
        with tabs["nav.classroom"]:
            from screens import classroom as classroom_screen
            classroom_screen.render_classroom(_lang())
