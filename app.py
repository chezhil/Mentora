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
from screens import path as path_screen
from screens import quiz as quiz_screen
from shared.models import LearnerProfile, StudentResponse

UPLOAD_DIR = "out/uploads"

# Every language here is verified end to end: real speech, and a font that can
# draw its script on the visuals. Do not add one without checking both — a
# language that renders as empty boxes is worse than one we do not offer.
LANGUAGES = {
    "en": "English",
    "hi": "हिन्दी / Hindi",
    "ta": "தமிழ் / Tamil",
    "te": "తెలుగు / Telugu",
    "kn": "ಕನ್ನಡ / Kannada",
    "bn": "বাংলা / Bengali",
    "mr": "मराठी / Marathi",
    "hinglish": "Hinglish",
}

st.set_page_config(
    page_title="Mentora — AI Teacher", page_icon="🎓", layout="wide",
    menu_items={
        "About": "**Mentora** — AI Teacher.\n\nTo change the Gemini API key "
                 "or switch to offline mode, use the **⚙️ APIs** panel at the "
                 "bottom of the sidebar. (Streamlit does not allow custom "
                 "controls in this menu.)",
    },
)

# Frontend team styles the app through ui/style.css and .streamlit/config.toml.
# This is the only line joining presentation to the rest of app.py.
ui.apply_theme()


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
    st.session_state.setdefault("busy", None)
    st.session_state.setdefault("last_followup", None)
    st.session_state.setdefault("done_tokens", set())


init_state()


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
        retry = re.search(r"retry in ([\d.]+)s", msg)
        when = f" Google suggests retrying in {float(retry.group(1)):.0f}s." if retry else ""
        per_day = "PerDay" in msg or "free_tier_requests" in msg
        return (
            "**Gemini quota exhausted.**"
            + (" This is the *daily* free-tier cap (20 requests/day), which "
               "resets at midnight US Pacific — not in a few seconds."
               if per_day else when)
            + "\n\nOne lesson costs 10-15 requests. Fix it in **⚙️ APIs** in the "
              "sidebar: paste another team member's key, or switch on "
              "*Offline mode* to keep working for free."
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
PROVIDERS = ["gemini", "groq", "ollama"]

PROVIDER_MODELS = {
    # Groq's free tier is thousands of requests a day against Gemini's 20,
    # and one lesson costs 22 — so Groq is the practical default for building
    # and rehearsing. Keep Gemini for the final recording if you prefer it.
    "groq": ['openai/gpt-oss-120b', 'qwen/qwen3.8-27b', 'groq/compound', 'groq/compound-mini', 'openai/gpt-oss-20b'],

    "ollama": ["llama3.1:8b", "qwen2.5:7b", "gemma2:9b"],
}

PROVIDER_KEY_ENV = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}

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

        st.caption(
            f"Gemini key: `{_mask(llm.API_KEY)}`  \n"
            f"Model: `{llm.MODEL}`  \n"
            f"Mode: {'🟡 offline (mock)' if offline else '🟢 live'}  \n"
            f"Avatar: {avatar_line}"
        )

        provider = st.selectbox(
            "Provider", PROVIDERS,
            index=PROVIDERS.index(llm.PROVIDER) if llm.PROVIDER in PROVIDERS else 0,
            help="Gemini free tier is 20 requests/day and one lesson costs 22. "
                 "Groq's free tier is thousands/day. Ollama runs locally with "
                 "no limit at all.")

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
            if key and key_env:
                os.environ[key_env] = key
                if provider == "gemini":
                    llm.API_KEY = key
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
    st.sidebar.header("Teacher reasoning")

    session = st.session_state.session
    if session is None:
        st.sidebar.caption("Starts once the lesson does.")
        return

    panel = orch.runtime(session).panel

    if panel.concept_name:
        st.sidebar.caption("Now teaching")
        st.sidebar.write(f"**{panel.concept_name}**")

    if panel.retrieved:
        pages = ", ".join(str(p) for p in panel.grounded_pages) or "—"
        st.sidebar.caption("Grounding")
        st.sidebar.write(f"{panel.retrieved} chunks · pages {pages}")
    elif session.doc_id:
        st.sidebar.caption("Grounding")
        st.sidebar.write("nothing relevant in the document")

    st.sidebar.divider()

    if not panel.answered:
        st.sidebar.caption("Waiting for the first answer.")
    else:
        st.sidebar.write(
            f"**Answer:** {'correct' if panel.correct else 'incorrect'}"
        )
        if panel.misconception:
            st.sidebar.write("**Misconception**")
            st.sidebar.warning(panel.misconception)
        if panel.action_taken:
            line = f"**Action:** {panel.action_taken}"
            if panel.escalated:
                line += f"  \n_(Pair B said {panel.action_from_pair_b}; "
                line += f"escalated on attempt {panel.attempt})_"
            st.sidebar.write(line)
        if panel.analogy:
            st.sidebar.write(f"**Analogy:** {panel.analogy}")
        if panel.difficulty:
            st.sidebar.write(f"**Difficulty:** {panel.difficulty}")
        if panel.attempt:
            st.sidebar.write(f"**Attempt:** {panel.attempt}")

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
    st.title("🎓 Mentora")
    st.write("Upload your material, or just name a topic. Then say how you "
             "want to be taught.")

    left, right = st.columns([3, 2])

    with left:
        uploaded = st.file_uploader(
            "Your material (optional)",
            type=["pdf", "docx", "pptx", "txt"],
        )
        topic = st.text_input(
            "What do you want to learn?",
            placeholder="Ohm's Law, or Chapter 4, or React hooks",
        )
        goal = st.text_input("Your goal (optional)",
                             placeholder="pass the unit test on Friday")
        student_id = st.text_input(
            "Your name", value=st.session_state.get("student_id", "student"),
            help="Used to remember what you struggled with last time.",
        )
        st.session_state.student_id = student_id

        seen = orch.past_reports(student_id)
        if seen:
            weak = list(dict.fromkeys(w for r in seen for w in r.weak))[:3]
            st.info(
                f"Welcome back — {len(seen)} previous lesson"
                f"{'s' if len(seen) > 1 else ''}. "
                + (f"Last time you struggled with {', '.join(weak)}."
                   if weak else "")
            )

    with right:
        level = st.selectbox("Your level",
                             ["beginner", "intermediate", "advanced"])
        language = st.selectbox(
            "Teach me in", list(LANGUAGES),
            format_func=lambda code: LANGUAGES[code],
        )
        minutes = st.slider("Time I have (minutes)",
                            min_value=5, max_value=60, value=20, step=1)

    if st.button("Start lesson", type="primary",
                 disabled=not topic or _busy()):
        token = f"start:{topic}:{level}:{language}:{minutes}"
        if not _claim(token):
            st.info("Already starting that lesson…")
            st.stop()
        profile = LearnerProfile(
            level=level,
            language=language,
            time_minutes=minutes,
            goal=goal or None,
        )
        try:
            with st.spinner("Reading your material and planning the lesson…"):
                session = orch.start_session(topic, profile, save_upload(uploaded),
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


# ---------------------------------------------------------------------------
# Screen 2 — Lesson
# ---------------------------------------------------------------------------

def _language_switch(session) -> None:
    """Change the teaching language without restarting the lesson.

    The brief asks for this explicitly — "now explain it in English" mid
    conversation — and the lesson has to survive it: same plan, same progress,
    same history. Pair B reads state.profile.language on every call, and
    speak() is passed it per segment, so changing it here is enough. It takes
    effect on the next segment rather than re-rendering the current one, which
    would cost a Gemini call and a re-render for something the student can
    just read.
    """
    codes = list(LANGUAGES)
    current = session.profile.language
    index = codes.index(current) if current in codes else 0

    chosen = st.selectbox(
        "Language", codes, index=index,
        format_func=lambda c: LANGUAGES[c],
        key=f"lang_switch_{session.session_id}",
        label_visibility="collapsed",
        help="Switch mid-lesson. Applies from the next part onwards.",
    )
    if chosen != current:
        session.profile.language = chosen
        orch.note(session,
                  f"Student switched the teaching language to {LANGUAGES[chosen]}.")
        st.session_state.lang_note = (
            f"Switched to {LANGUAGES[chosen]} — from the next part onwards."
        )
        st.rerun()


def _followup_box(session) -> None:
    """Let the student ask their own question mid-lesson.

    Task 2 of the brief: answer follow-ups while holding lesson context.
    orchestrator.ask() does the retrieval, the logging and the failure
    handling; this is only the input and the reply.
    """
    with st.expander("Ask me something about this"):
        with st.form(f"followup_{session.session_id}", clear_on_submit=True):
            question = st.text_input(
                "Your question", label_visibility="collapsed",
                placeholder="e.g. why does the water pipe analogy work?")
            asked = st.form_submit_button("Ask", disabled=_busy())

        if asked and question.strip():
            token = f"ask:{session.session_id}:{len(session.turns)}"
            if not _claim(token):
                st.info("Still answering your last question…")
                st.stop()
            try:
                with st.spinner("Thinking…"):
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
            st.caption(f"You asked: {q}")
            st.info(a)


def screen_lesson() -> None:
    session = st.session_state.session
    segment = st.session_state.segment

    plan = session.plan
    done = min(session.current_concept, len(plan.concepts))

    bar, lang_col = st.columns([4, 1])
    with bar:
        st.progress(done / len(plan.concepts),
                    text=f"{plan.topic} — concept "
                         f"{min(done + 1, len(plan.concepts))} "
                         f"of {len(plan.concepts)}")
    with lang_col:
        _language_switch(session)

    if segment is None:
        st.success("That's the whole lesson.")
        if st.session_state.report is not None:
            # Already finished. Streamlit cannot switch tabs for the student,
            # so say where the report went rather than offering the button
            # again and looking like nothing happened.
            st.info("Your report is ready — open the **Report** tab above.")
            return
        if st.button("Finish and see my report", type="primary",
                     disabled=_busy()):
            token = f"finish:{session.session_id}"
            if not _claim(token):
                st.info("Already building your report…")
                st.stop()
            try:
                with st.spinner("Marking the lesson…"):
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
            st.video(media.video_mp4)
        else:
            st.info("Avatar video pending (Pair C) — teaching as text for now.")
        st.write(segment.script)
        if media.audio_wav and os.path.exists(media.audio_wav):
            st.audio(media.audio_wav)

    with visual:
        if media.visual_png and os.path.exists(media.visual_png):
            st.image(media.visual_png, caption=segment.visual.caption)
        else:
            st.caption(f"visual: {segment.visual.kind}")
        for note in media.notes:
            st.caption(f"⚠️ {note}")

    if segment.citations:
        with st.expander(f"From your material ({len(segment.citations)} passages)"):
            for c in segment.citations:
                where = f"page {c.page}" if c.page else "unknown page"
                st.markdown(f"**{where}** · relevance {c.score:.2f}")
                st.caption(c.text)
    elif session.doc_id:
        st.caption("Nothing in your material covers this — taught from "
                   "general knowledge.")

    if st.session_state.get("lang_note"):
        st.success(st.session_state.pop("lang_note"))

    _followup_box(session)

    if st.session_state.last_feedback:
        st.info(st.session_state.last_feedback)

    if segment.question is None:
        if st.button("Continue", disabled=_busy()):
            _advance(session)
        return

    with st.form("answer_form", clear_on_submit=True):
        st.write(f"**{segment.question.prompt}**")
        if segment.question.kind == "mcq" and segment.question.options:
            reply = st.radio("Your answer", segment.question.options,
                             label_visibility="collapsed")
        else:
            reply = st.text_input("Your answer", label_visibility="collapsed")
        col_a, col_s = st.columns([1, 1])
        with col_a:
            submitted = st.form_submit_button("Answer", type="primary",
                                              disabled=_busy())
        with col_s:
            skipped = st.form_submit_button("Skip question", disabled=_busy())

    if skipped:
        token = f"skip:{session.session_id}:{segment.question.id}"
        if _claim(token):
            orch.skip(session, segment.question.id)
            _release(token, completed=True)
            st.session_state.last_feedback = None
            _advance(session)

    if submitted and reply:
        # Keyed on the question, so one question can only ever be answered once
        # however many times the button is pressed.
        token = f"answer:{session.session_id}:{segment.question.id}"
        if not _claim(token):
            st.info("That answer is already being marked…")
            st.stop()
        try:
            with st.spinner("Marking your answer…"):
                evaluation = orch.answer(
                    session,
                    StudentResponse(question_id=segment.question.id, answer=reply),
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
    token = f"step:{session.session_id}:{len(session.turns)}"
    if not _claim(token):
        st.stop()
    try:
        with st.spinner("Preparing the next part…"):
            if rt.pending is not None or not orch.is_finished(session):
                st.session_state.segment = orch.step(session)
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
        st.caption("Nothing yet.")
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
        st.caption("Nothing yet.")
        return
    st.caption(f"{len(turns)} turns · read from {source}")

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
        st.caption("Finish the lesson to see your report.")
        return

    st.metric("Score", f"{report.score:.0f}%")

    video = orch.lesson_video(st.session_state.session)
    if video and os.path.exists(video):
        st.subheader("Your lesson")
        st.video(video)

    left, right = st.columns(2)
    with left:
        st.subheader("Strong")
        for item in report.strong or ["—"]:
            st.write(f"✅ {item}")
    with right:
        st.subheader("Needs work")
        for item in report.weak or ["—"]:
            st.write(f"🔁 {item}")

    if report.misconceptions:
        st.subheader("What tripped you up")
        for item in dict.fromkeys(report.misconceptions):
            st.warning(item)

    st.subheader("Revise")
    for item in report.revise or ["—"]:
        st.write(f"• {item}")

    st.subheader("Next")
    st.success(report.next_topic)

    if st.button("Teach me something else"):
        for key in ("phase", "session", "segment", "report", "last_feedback",
                    "busy", "done_tokens", "last_followup", "lang_note"):
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
    lesson_tab, history_tab, quiz_tab, path_tab, report_tab = st.tabs(
        ["Lesson", "History", "Quiz", "Path", "Report"]
    )
    with lesson_tab:
        screen_lesson()
    with history_tab:
        screen_history()
    with quiz_tab:
        quiz_screen.render_quiz(st.session_state.session)
    with path_tab:
        path_screen.render_path(st.session_state.session)
    with report_tab:
        screen_report()
