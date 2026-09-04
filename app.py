"""Mentora — the student-facing app. Chezhil owns this file.

    streamlit run app.py

Four screens (Setup, Lesson, History, Report) and the adaptation panel.

STREAMLIT, IN ONE PARAGRAPH: this whole file re-runs top to bottom on every
single interaction. Nothing survives a rerun except st.session_state. So all
real state lives in st.session_state, and every branch below has to work when
the script starts again from line 1.
"""

import os
import re

import streamlit as st

try:                       # load .env if present; it holds GEMINI_API_KEY
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import orchestrator as orch
import ui
import wiring
from screens import classroom as classroom_screen
from screens import flashcards as flashcards_screen
from screens import path as path_screen
from screens import quiz as quiz_screen
from shared import languages
from shared.models import LearnerProfile, StudentResponse
from ui.i18n import t

UPLOAD_DIR = "out/uploads"

# Every language Mentora offers is defined in shared/languages.py — one place
# holding its voice, its font and its script direction, because a language
# added to only two of those three is how we shipped Tamil that rendered as
# empty boxes and Kannada that narrated in silence.
LANGUAGES = {code: languages.label(code) for code in languages.codes()}

ROLES = ("student", "teacher")

st.set_page_config(
    page_title="Mentora — AI Teacher", page_icon="🎓", layout="wide",
    menu_items={
        "About": "**Mentora** — AI Teacher.\n\nTo change the Gemini API key "
                 "or switch to offline mode, use the **⚙️ APIs** panel at the "
                 "bottom of the sidebar. (Streamlit does not allow custom "
                 "controls in this menu.)",
    },
)



def _lang() -> str:
    """The language the interface is currently drawn in."""
    return st.session_state.get("ui_lang", languages.DEFAULT)


def _t(key: str) -> str:
    return t(key, _lang())


def _set_language(code: str) -> None:
    """Switch the interface, everywhere, on the next frame.

    Streamlit reruns this whole file on every interaction, so there is nothing
    to re-render by hand: writing the code into session state is enough, and
    the rerun below draws the entire app in the new language. That is what
    makes the switch feel instant rather than like a page load.
    """
    st.session_state.ui_lang = code


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
    # The interface language, which is separate from the teaching language
    # only until the student picks one — see _set_language().
    st.session_state.setdefault("ui_lang", languages.DEFAULT)
    st.session_state.setdefault("role", "student")
    st.session_state.setdefault("busy", None)
    st.session_state.setdefault("last_followup", None)
    st.session_state.setdefault("done_tokens", set())


init_state()

# Styling comes from ui/style.css and .streamlit/config.toml; this is the only
# line joining presentation to the rest of app.py. The language goes with it so
# Urdu and Arabic get dir="rtl" — Streamlit has no right-to-left mode of its
# own, and an Arabic interface laid out left-to-right is not an Arabic
# interface.
ui.apply_theme(_lang(), hide_nav=True)


# ---------------------------------------------------------------------------
# Double-click protection
#
# Streamlit queues a rerun for every click. Without this, hammering "Answer"
# fires orch.answer() once per click, and each one costs 10-15 Gemini requests
# against a 20/day free-tier cap — the whole quota gone before the first call
# returns.
#
# Two layers, because either alone is not enough:
#   busy flag   - blocks a second run while one is in flight, and greys the
#                 buttons out so it is visible
#   done tokens - an action already completed can never run twice, even if the
#                 flag were lost to a cancelled script run
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

        # A per-minute limit and a per-day cap are both 429 and want opposite
        # advice. Saying "your daily quota is gone, swap keys" over a
        # four-second throttle sends someone hunting for a new API key in the
        # middle of a demo that would have recovered on its own.
        if not per_day and retry:
            return (
                f"**Rate limited for {float(retry.group(1)):.0f} seconds** — "
                f"this is a per-minute limit, not your daily quota. Press the "
                f"button again in a moment and it will go through."
            )
        return (
            "**Quota exhausted.**"
            + (" This is the *daily* free-tier cap (Gemini allows 20 "
               "requests/day), which resets at midnight US Pacific — not in a "
               "few seconds." if per_day else "")
            + "\n\nOne lesson costs 10-15 requests. Fix it in **⚙️ APIs** in the "
              "sidebar: paste another team member's key, switch provider to "
              "Groq (thousands/day, free), or switch on *Offline mode*."
        )
    if "API key not valid" in msg or "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg:
        return ("**Gemini rejected that API key.** Paste a valid one in "
                "**⚙️ APIs** in the sidebar. Keys from Google AI Studio start "
                "with `AIza`.")
    if "no longer available" in msg or "NOT_FOUND" in msg:
        return (f"**That Gemini model is not available to this key.** Pick a "
                f"different one in **⚙️ APIs** in the sidebar.\n\n`{msg[:200]}`")
    if "No Gemini API key" in msg:
        return ("**No Gemini API key set.** Add one in **⚙️ APIs** in the "
                "sidebar, or switch on *Offline mode*.")
    if "deadline" in msg.lower() or "timeout" in msg.lower():
        return "**Gemini timed out.** Try again, or use *Offline mode* in **⚙️ APIs**."
    return f"**{type(exc).__name__}**\n\n```\n{msg[:400]}\n```"


def save_upload(uploaded) -> str | None:
    if uploaded is None:
        return None
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, uploaded.name)
    with open(path, "wb") as f:
        f.write(uploaded.getbuffer())
    return path


# ---------------------------------------------------------------------------
# THE ADAPTATION PANEL
#
# 20 marks of Pair B's work is invisible without this. Every field below is
# copied straight off an Evaluation or off a decision the orchestrator made.
# Nothing here is invented for display.
# ---------------------------------------------------------------------------

# Free-tier quota is per-project-PER-MODEL, so switching model gives a fresh
# daily allowance. Ordered cheapest-first: our calls are structured JSON
# against a fixed schema, which is what Flash-Lite is built for.
PROVIDERS = ["local", "gemini", "groq", "ollama"]

PROVIDER_MODELS = {
    "local": ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"],
    # Groq's free tier is thousands of requests a day against Gemini's 20,
    # and one lesson costs 22 — so Groq is the practical default for building
    # and rehearsing. Keep Gemini for the final recording if you prefer it.
    "groq": ['openai/gpt-oss-120b', 'qwen/qwen3.8-27b', 'groq/compound', 'groq/compound-mini', 'openai/gpt-oss-20b'],

    "ollama": ["llama3.1:8b", "qwen2.5:7b", "gemma2:9b"],
}

PROVIDER_KEY_ENV = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "local": "GEMINI_KEY"}

GEMINI_MODELS = [
    "gemini-2.5-flash-lite",   # ~$0.004/lesson
    "gemini-3.1-flash-lite",   # ~$0.012/lesson
    "gemini-3.5-flash-lite",   # ~$0.018/lesson
    "gemini-3.6-flash",        # ~$0.032/lesson
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]
ENV_PATH = ".env"


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
    """Swap the Gemini key without restarting — for when quota runs out mid-demo."""
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

        active_key = llm.LOCAL_KEY if llm.PROVIDER == "local" else (llm.API_KEY or "")
        active_endpoint = llm.LOCAL_BASE_URL if llm.PROVIDER == "local" else "Google Cloud / API"
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
            help="Local proxy runs on http://127.0.0.1:8010. Groq/Gemini use cloud APIs."
        )

        local_url = ""
        if provider == "local":
            local_url = st.text_input("Local LLM Base URL", value=llm.LOCAL_BASE_URL)
            key = st.text_input("Local API Key", value=llm.LOCAL_KEY, type="password")
            key_env = "GEMINI_KEY"
        else:
            key_env = PROVIDER_KEY_ENV.get(provider)
            key = ""
            if key_env:
                key = st.text_input(
                    f"{provider.title()} API key", type="password",
                    placeholder="free key from console.groq.com/keys"
                                if provider == "groq" else "paste a key")
            else:
                st.caption("Ollama needs no key — just `ollama serve` running.")

        models = PROVIDER_MODELS.get(provider, GEMINI_MODELS)
        model = st.selectbox(
            "Model", models,
            index=models.index(llm.MODEL) if llm.MODEL in models else 0)

        replicate = st.text_input(
            "Replicate token", type="password",
            placeholder="not needed — the avatar runs locally",
            help="Only used if the local Wav2Lip weights are missing, or you "
                 "set MENTORA_LOCAL_AVATAR=0. The local backend is free and "
                 "needs no account.")

        new_offline = st.toggle("Offline mode (no API calls)", value=offline,
                                help="Replays canned answers. Free, but every "
                                     "answer is marked wrong.")
        remember = st.checkbox("Remember in .env", value=True,
                               help=".env is gitignored — it never reaches GitHub.")

        if st.button("Apply", type="primary"):
            saved = {}
            if provider != llm.PROVIDER:
                os.environ["AI_TEACHER_PROVIDER"] = provider
                llm.PROVIDER = provider
                saved["AI_TEACHER_PROVIDER"] = provider
            if provider == "local" and local_url:
                os.environ["GEMINI_URL"] = local_url
                llm.LOCAL_BASE_URL = local_url
                saved["GEMINI_URL"] = local_url
            if key and key_env:
                os.environ[key_env] = key
                if provider == "gemini":
                    llm.API_KEY = key
                elif provider == "local":
                    llm.LOCAL_KEY = key
                saved[key_env] = key
            # both clients are cached; drop them so the new choice takes effect
            llm._client = None
            llm._openai_client = None
            if model != llm.MODEL:
                os.environ["AI_TEACHER_MODEL"] = model
                llm.MODEL = model
                saved["AI_TEACHER_MODEL"] = model
            if replicate:
                os.environ["REPLICATE_API_TOKEN"] = replicate
                saved["REPLICATE_API_TOKEN"] = replicate
            if new_offline:
                os.environ["AI_TEACHER_MOCK"] = "mocks/fixture_mock.json"
            else:
                os.environ.pop("AI_TEACHER_MOCK", None)
            llm._mock = None                  # drop the cached fixture
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


def _asset_warning() -> None:
    """Say plainly when the downloaded assets are missing.

    They are ~500MB and cannot live in git, so a fresh clone has none of them.
    Everything still runs, which is the problem: the avatar quietly becomes a
    still image and narration quietly becomes silence, and the only clue is
    that the demo looks worse than it did on someone else's laptop.
    """
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


# ---------------------------------------------------------------------------
# Screen 1 — Setup
# ---------------------------------------------------------------------------

def screen_setup() -> None:
    st.title("Mentora")
    st.write(_t("app.tagline"))

    # Role and language first, above everything else, because both change what
    # the rest of this screen says. The language one in particular: leaving it
    # in the right-hand column meant a Tamil student read an English form all
    # the way down before finding the control that would have translated it.
    role_col, lang_col = st.columns([1, 1])
    with role_col:
        # No `key=` here, and none on the language picker below. A Streamlit
        # widget given both a key and an index takes its value from the key
        # and ignores the index — so when the language switch rerun redrew
        # this radio, it came back with NOTHING selected while
        # st.session_state.role still said "student". The control and the app
        # disagreed, visibly. Index-only keeps session state the single source
        # of truth for both.
        role = st.radio(
            _t("setup.role"), ROLES, horizontal=True,
            format_func=lambda r: _t(f"role.{r}"),
            index=ROLES.index(st.session_state.get("role", "student")),
        )
        if role != st.session_state.get("role"):
            st.session_state.role = role
            st.rerun()
    with lang_col:
        _interface_language()

    if st.session_state.role == "teacher":
        _teacher_setup()
        return

    _student_setup()


def _interface_language() -> None:
    """The language picker. Changes the whole interface on the same click.

    There is deliberately only ONE language control, not an interface language
    and a teaching language. A student who reads Tamil wants to be taught in
    Tamil; asking them to set the same thing twice is a settings screen
    pretending to be a feature. The lesson can still be switched mid-flow from
    the lesson screen, and that moves the interface with it.
    """
    codes = languages.codes()
    current = _lang()
    chosen = st.selectbox(
        _t("setup.language"), codes,
        index=codes.index(current) if current in codes else 0,
        format_func=languages.label,
    )
    if chosen != current:
        _set_language(chosen)
        st.rerun()

    from ui.i18n import coverage
    done = coverage().get(chosen, 0)
    if done < 100:
        # Say so rather than letting a half-translated screen look like a bug.
        st.caption(f"Interface {done}% translated — the rest falls back to English. "
                   f"The lesson itself is fully in {languages.get(chosen).english_name}.")


def _student_setup() -> None:
    left, right = st.columns([3, 2])

    with left:
        uploaded = st.file_uploader(
            _t("setup.material"), type=["pdf", "docx", "pptx", "txt"],
        )
        topic = st.text_input(_t("setup.topic"), placeholder=_t("setup.topic_ph"))
        goal = st.text_input(_t("setup.goal"), placeholder=_t("setup.goal_ph"))
        student_id = st.text_input(
            _t("setup.name"), value=st.session_state.get("student_id", "student"),
            help="Used to remember what you struggled with last time.",
        )
        st.session_state.student_id = student_id

        seen = orch.past_reports(student_id)
        if seen:
            weak = list(dict.fromkeys(w for r in seen for w in r.weak))[:3]
            st.info(
                f"{_t('setup.welcome_back')} — {len(seen)} previous lesson"
                f"{'s' if len(seen) > 1 else ''}. "
                + (f"Last time you struggled with {', '.join(weak)}."
                   if weak else "")
            )

    with right:
        levels = ["beginner", "intermediate", "advanced"]
        level = st.selectbox(_t("setup.level"), levels,
                             format_func=lambda v: _t(f"level.{v}"))
        minutes = st.slider(_t("setup.time"), min_value=5, max_value=60,
                            value=20, step=1)

    if st.button(_t("setup.start"), type="primary",
                 disabled=not topic or _busy()):
        _begin_lesson(topic, level, minutes, goal, uploaded)


def _begin_lesson(topic, level, minutes, goal, uploaded) -> None:
    """Plan the lesson and open it. Shared by the student and teacher setups."""
    # Auto-infer the topic from the uploaded file name when nothing was typed.
    final_topic = (topic or "").strip()
    if not final_topic and uploaded:
        final_topic = os.path.splitext(uploaded.name)[0] \
            .replace("_", " ").replace("-", " ").title()
    if not final_topic:
        st.warning("⚠️ Enter a topic or upload your material first.")
        return

    language = _lang()
    token = f"start:{final_topic}:{level}:{language}:{minutes}"
    if not _claim(token):
        st.info("Already starting that lesson…")
        st.stop()
    profile = LearnerProfile(
        level=level, language=language, time_minutes=minutes,
        goal=goal or None,
    )
    try:
        with st.spinner(_t("lesson.planning")):
            session = orch.start_session(
                final_topic, profile, save_upload(uploaded),
                student_id=st.session_state.student_id)
            segment = orch.step(session)
    except Exception as exc:
        _release(token, completed=False)   # let them retry after fixing the key
        st.error(_friendly(exc))
        st.stop()
    _release(token, completed=True)
    st.session_state.session = session
    st.session_state.segment = segment
    st.session_state.phase = "lesson"
    st.rerun()


def _teacher_setup() -> None:
    """The teacher gets the classroom first, and lesson-building second.

    Deliberate ordering. A teacher opening this app mid-term wants to know how
    the class did, not to build another lesson; a teacher building a lesson
    knows they are doing it and will scroll. The student's setup form is the
    same one underneath — a teacher previewing a lesson should see exactly what
    the class will see, not a teacher-flavoured approximation of it.
    """
    classroom_screen.render_classroom(_lang())

    st.divider()
    st.markdown(f"### {_t('teacher.preview')}")

    left, right = st.columns([3, 2])
    with left:
        uploaded = st.file_uploader(
            _t("setup.material"), type=["pdf", "docx", "pptx", "txt"],
            key="teacher_upload")
        topic = st.text_input(_t("setup.topic"), key="teacher_topic",
                              placeholder=_t("setup.topic_ph"))
    with right:
        levels = ["beginner", "intermediate", "advanced"]
        level = st.selectbox(_t("setup.level"), levels, key="teacher_level",
                             format_func=lambda v: _t(f"level.{v}"))
        minutes = st.slider(_t("setup.time"), min_value=5, max_value=60,
                            value=20, step=1, key="teacher_minutes")

    # The teacher previews as a named test student so their run does not land
    # in the class average as if a real student had sat it.
    st.session_state.student_id = "teacher preview"

    if st.button(_t("setup.start"), type="primary",
                 disabled=not topic or _busy(), key="teacher_start"):
        _begin_lesson(topic, level, minutes, None, uploaded)



# ---------------------------------------------------------------------------
# Screen 2 — Lesson
# ---------------------------------------------------------------------------

def _language_switch(session) -> None:
    """Change the teaching language immediately mid-lesson.

    The brief asks for this explicitly — "now explain it in English" mid
    conversation — and the lesson has to survive it: same plan, same progress,
    same history. The current segment is re-rendered in the new language by
    orch.switch_language(), and the interface moves with it.
    """
    codes = languages.codes()
    current = session.profile.language
    index = codes.index(current) if current in codes else 0

    chosen = st.selectbox(
        _t("setup.language"), codes, index=index,
        format_func=languages.label,
        key=f"lang_switch_{session.session_id}",
        label_visibility="collapsed",
        help="Switch mid-lesson. Updates the current explanation immediately.",
    )
    if chosen != current:
        token = f"lang:{session.session_id}:{chosen}"
        if _claim(token):
            with st.spinner(f"{_t('lesson.preparing')}…"):
                try:
                    new_seg = orch.switch_language(
                        session, chosen, current_segment=st.session_state.segment
                    )
                    if new_seg:
                        st.session_state.segment = new_seg
                    st.session_state.lang_note = (
                        f"Switched to {languages.label(chosen)}."
                    )
                except Exception as exc:
                    st.error(_friendly(exc))
                finally:
                    _release(token, completed=True)
            _set_language(chosen)   # the interface moves with the teaching
            st.rerun()


def _followup_box(session) -> None:
    """Let the student ask their own question mid-lesson.

    Task 2 of the brief: answer follow-ups while holding lesson context.
    orchestrator.ask() does the retrieval, the logging and the failure
    handling; this is only the input and the reply.
    """
    with st.expander(_t("lesson.ask")):
        with st.form(f"followup_{session.session_id}", clear_on_submit=True):
            question = st.text_input(
                _t("lesson.ask"), label_visibility="collapsed",
                placeholder=_t("lesson.ask_ph"))
            asked = st.form_submit_button(_t("lesson.ask_button"),
                                          disabled=_busy())

        if asked and question.strip():
            token = f"ask:{session.session_id}:{len(session.turns)}"
            if not _claim(token):
                st.info("Still answering your last question…")
                st.stop()
            try:
                with st.spinner(_t("lesson.thinking")):
                    reply = orch.ask(session, question)
            except Exception as exc:
                _release(token, completed=False)
                st.error(_friendly(exc))
                st.stop()
            _release(token, completed=True)
            st.session_state.last_followup = (question, reply)
            st.rerun()

        asked_before = st.session_state.get("last_followup")
        if asked_before:
            q, a = asked_before
            st.caption(f"{_t('lesson.you_asked')}: {q}")
            st.info(a)


def _board(path: str) -> None:
    """The board video, plain.

    The teacher used to be an HTML layer over this element. She is drawn into
    the frames themselves now, so an overlay would be a SECOND copy of her —
    and being absolutely positioned bottom-right, it sat exactly on top of the
    video's fullscreen button. A plain video element keeps its own controls
    and still shows the teacher, because she is in the picture.
    """
    st.video(path)


def screen_lesson() -> None:
    session = st.session_state.session
    segment = st.session_state.segment

    if segment is not None and segment.question is not None:
        orch.remember_question(session, segment.question)

    plan = session.plan
    done = min(session.current_concept, len(plan.concepts))

    bar, lang_col = st.columns([4, 1])
    with bar:
        st.progress(done / len(plan.concepts),
                    text=f"{plan.topic} — {_t('lesson.concept')} "
                         f"{min(done + 1, len(plan.concepts))} "
                         f"{_t('lesson.of')} {len(plan.concepts)}")
    with lang_col:
        _language_switch(session)

    if segment is None:
        st.success(_t("lesson.complete"))
        if st.session_state.report is not None:
            st.info(_t("lesson.report_ready"))
            return
        if st.button(_t("lesson.finish"), type="primary", disabled=_busy()):
            token = f"finish:{session.session_id}"
            if not _claim(token):
                st.info("Already building your report…")
                st.stop()
            try:
                with st.spinner(_t("lesson.marking")):
                    st.session_state.report = orch.finish(session)
            except Exception as exc:
                _release(token, completed=False)
                st.error(_friendly(exc))
                st.stop()
            _release(token, completed=True)
            st.session_state.phase = "report"
            st.rerun()
        return

    media = orch.media_for(session, segment)
    video, visual = st.columns([3, 2])

    with video:
        if media.video_mp4 and os.path.exists(media.video_mp4):
            # The live teacher stands in the corner of the board video. This
            # was only wired into pages/2_Lesson.py, so app.py — the demo —
            # showed a bare st.video with no avatar over it at all.
            _board(media.video_mp4)
        else:
            st.info(_t("lesson.no_video"))
        st.write(segment.script)
        if media.audio_wav and os.path.exists(media.audio_wav):
            st.audio(media.audio_wav)

    with visual:
        if media.visual_png and os.path.exists(media.visual_png):
            st.image(media.visual_png, caption=segment.visual.caption)
        else:
            st.caption(f"visual: {segment.visual.kind}")

        # Render crisp Mermaid preview if diagram payload is mermaid
        if segment.visual.kind in ("diagram", "concept_map", "timeline") and segment.visual.payload:
            payload = segment.visual.payload.strip()
            if any(k in payload.lower() for k in ["graph", "flowchart", "timeline", "-->", "->"]):
                with st.expander("🔍 Interactive Diagram Preview", expanded=False):
                    st.markdown(f"```mermaid\n{payload}\n```")

        for note in media.notes:
            st.caption(f"⚠️ {note}")

    # Action row: Explain differently (Regeneration)
    act_col1, act_col2 = st.columns([1, 1])
    with act_col1:
        if st.button("🔄 Explain differently (Regenerate)",
                     key=f"diff_{session.session_id}_{segment.concept_id}_{session.attempts.get(segment.concept_id, 0)}",
                     disabled=_busy()):
            token = f"regen:{session.session_id}:{len(session.turns)}"
            if _claim(token):
                try:
                    with st.spinner("Preparing fresh explanation with new analogy..."):
                        new_seg = orch.regenerate_current(session, segment)
                        st.session_state.segment = new_seg
                except Exception as exc:
                    st.error(_friendly(exc))
                finally:
                    _release(token, completed=True)
                st.rerun()

    if segment.citations:
        with st.expander(f"{_t('lesson.from_material')} "
                         f"({len(segment.citations)})"):
            for c in segment.citations:
                where = f"page {c.page}" if c.page else "unknown page"
                st.markdown(f"**{where}** · relevance {c.score:.2f}")
                st.caption(c.text)
    elif session.doc_id:
        st.caption(_t("lesson.not_in_material"))

    if st.session_state.get("lang_note"):
        st.success(st.session_state.pop("lang_note"))

    _followup_box(session)

    if st.session_state.last_feedback:
        st.info(st.session_state.last_feedback)

    if segment.question is None:
        if st.button(_t("lesson.continue"), type="primary", disabled=_busy()):
            _advance(session)
        return

    # Check for MMCQ (multi-select) vs single MCQ
    is_mmcq = segment.question.kind in ("mmcq", "msq") or (
        segment.question.options and any(p in segment.question.prompt.lower() for p in ["select all", "which of the following are", "multiple options"])
    )
    badge = "[MMCQ · Multi-select]" if is_mmcq else (f"[{segment.question.kind.upper()}]" if segment.question.kind else "[QUESTION]")

    with st.form("answer_form", clear_on_submit=False):
        st.markdown(f"**{segment.question.prompt}** `{badge}`")
        if is_mmcq and segment.question.options:
            st.caption("☑️ Select all that apply:")
            selected_opts = []
            for opt_idx, opt in enumerate(segment.question.options):
                if st.checkbox(opt, key=f"ans_chk_{session.session_id}_{segment.question.id}_{opt_idx}"):
                    selected_opts.append(opt)
            reply = "; ".join(selected_opts) if selected_opts else ""
        elif segment.question.kind == "mcq" and segment.question.options:
            reply = st.radio(
                _t("lesson.your_answer"), segment.question.options,
                key=f"ans_rad_{session.session_id}_{segment.question.id}",
                index=None,
                label_visibility="collapsed"
            )
        else:
            reply = st.text_input(
                _t("lesson.your_answer"),
                key=f"ans_txt_{session.session_id}_{segment.question.id}",
                label_visibility="collapsed",
                placeholder="Type your answer here..."
            )

        col_a, col_s = st.columns([1, 1])
        with col_a:
            submitted = st.form_submit_button(_t("lesson.answer"), type="primary")
        with col_s:
            skipped = st.form_submit_button(_t("lesson.skip"))

    if skipped:
        st.session_state.busy = None  # A killed run leaves a stale lock; skip must not wedge on it.
        token = f"skip:{session.session_id}:{segment.question.id}"
        if _claim(token):
            orch.skip(session, segment.question.id)
            _release(token, completed=True)
            st.session_state.last_feedback = None
            _advance(session)

    if submitted:
        # A run killed mid-marking (Stop, file-change rerun) leaves busy set
        # forever; done_tokens still guards against double-marking, so clearing
        # the stale lock here is safe — same defence _advance() already uses.
        st.session_state.busy = None
        if not reply or not str(reply).strip():
            st.warning("⚠️ Please select or type an answer before submitting.")
            return

        token = f"answer:{session.session_id}:{segment.question.id}"
        if not _claim(token):
            st.info("That answer is already being marked…")
            st.stop()
        try:
            with st.spinner(_t("lesson.marking")):
                evaluation = orch.answer(
                    session,
                    StudentResponse(question_id=segment.question.id, answer=str(reply)),
                    question=segment.question,
                )
        except Exception as exc:
            _release(token, completed=False)
            st.error(_friendly(exc))
            st.stop()
        _release(token, completed=True)
        st.session_state.last_feedback = evaluation.feedback
        _advance(session)


def _advance(session) -> None:
    """Fetch the next segment — which may be a re-explanation of this one."""
    rt = orch.runtime(session)
    st.session_state.busy = None  # Ensure advance is never blocked by an earlier lock
    token = f"step:{session.session_id}:{len(session.turns)}:{session.current_concept}"
    if not _claim(token):
        st.rerun()
        return
    try:
        with st.spinner(_t("lesson.preparing")):
            if rt.pending is not None or not orch.is_finished(session):
                new_seg = orch.step(session)
                st.session_state.segment = new_seg
                if new_seg and new_seg.question:
                    orch.remember_question(session, new_seg.question)
            else:
                st.session_state.segment = None
    except Exception as exc:
        _release(token, completed=False)
        st.error(_friendly(exc))
        st.stop()
    _release(token, completed=True)
    st.rerun()


# ---------------------------------------------------------------------------
# Screen 3 — History
# ---------------------------------------------------------------------------

def screen_history() -> None:
    session = st.session_state.session
    if session is None:
        st.caption(_t("history.empty"))
        return

    # Read back from SQLite rather than from memory — if this renders, the
    # lesson genuinely survives a restart.
    turns = session.turns
    source = "in memory"
    if orch.history is not None:
        try:
            stored = orch.history.load_turns(session.session_id)
            if stored:
                turns, source = stored, "mentora.db"
        except Exception:
            pass

    if not turns:
        st.caption(_t("history.empty"))
        return
    st.caption(f"{len(turns)} {_t('history.turns')} · {source}")

    icons = {"teacher": "🎓", "student": "🙋", "system": "⚙️"}
    for turn in turns:
        stamp = turn.timestamp.strftime("%H:%M:%S")
        tag = f" · {turn.concept_id}" if turn.concept_id else ""
        st.markdown(f"{icons.get(turn.role, '•')} **{turn.role}** "
                    f"`{stamp}{tag}`")
        st.write(turn.content)
        st.divider()


# ---------------------------------------------------------------------------
# Screen 4 — Report
# ---------------------------------------------------------------------------

def screen_report() -> None:
    report = st.session_state.report
    if report is None:
        st.caption(_t("report.locked"))
        return

    st.metric(_t("report.score"), f"{report.score:.0f}%")

    video = orch.lesson_video(st.session_state.session)
    if video and os.path.exists(video):
        st.subheader(_t("report.your_lesson"))
        st.video(video)

    left, right = st.columns(2)
    with left:
        st.subheader(_t("report.strong"))
        for item in report.strong or ["—"]:
            st.write(f"✅ {item}")
    with right:
        st.subheader(_t("report.weak"))
        for item in report.weak or ["—"]:
            st.write(f"🔁 {item}")

    if report.misconceptions:
        st.subheader(_t("report.misconceptions"))
        for item in dict.fromkeys(report.misconceptions):
            st.warning(item)

    st.subheader(_t("report.revise"))
    for item in report.revise or ["—"]:
        st.write(f"• {item}")

    st.subheader(_t("report.next"))
    st.success(report.next_topic)

    if st.button(_t("report.again")):
        for key in ("phase", "session", "segment", "report", "last_feedback",
                    "busy", "done_tokens", "last_followup", "lang_note",
                    "quiz_report"):
            st.session_state.pop(key, None)
        init_state()
        st.rerun()


# ---------------------------------------------------------------------------

adaptation_panel()
api_panel()

if st.session_state.phase == "setup":
    screen_setup()
else:
    # Screens live in screens/ so several people can build them at once
    # without editing this file. Each takes the session and renders; none of
    # them touch st.session_state.
    #
    # The teacher gets one extra tab. It is added rather than substituted: a
    # teacher previewing a lesson needs to see exactly the lesson the class
    # will see, so every student tab stays exactly where it was.
    names = ["nav.lesson", "nav.history", "nav.quiz", "nav.flashcards",
             "nav.path", "nav.report"]
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
    if "nav.classroom" in tabs:
        with tabs["nav.classroom"]:
            classroom_screen.render_classroom(_lang())
