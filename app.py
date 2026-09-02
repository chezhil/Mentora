"""Mentora — the student-facing app. Chezhil owns this file.

    streamlit run app.py

Four screens (Setup, Lesson, History, Report) and the adaptation panel.

STREAMLIT, IN ONE PARAGRAPH: this whole file re-runs top to bottom on every
single interaction. Nothing survives a rerun except st.session_state. So all
real state lives in st.session_state, and every branch below has to work when
the script starts again from line 1.
"""

import os

import streamlit as st

import orchestrator as orch
import wiring
from shared.models import LearnerProfile, StudentResponse

UPLOAD_DIR = "out/uploads"

LANGUAGES = {
    "en": "English",
    "hi": "हिन्दी / Hindi",
    "ta": "தமிழ் / Tamil",
    "kn": "ಕನ್ನಡ / Kannada",
    "hinglish": "Hinglish",
}

st.set_page_config(page_title="Mentora — AI Teacher", page_icon="🎓",
                   layout="wide")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def init_state() -> None:
    st.session_state.setdefault("phase", "setup")
    st.session_state.setdefault("session", None)
    st.session_state.setdefault("segment", None)
    st.session_state.setdefault("report", None)
    st.session_state.setdefault("last_feedback", None)


init_state()


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

    with right:
        level = st.selectbox("Your level",
                             ["beginner", "intermediate", "advanced"])
        language = st.selectbox(
            "Teach me in", list(LANGUAGES),
            format_func=lambda code: LANGUAGES[code],
        )
        minutes = st.select_slider("Time I have (minutes)",
                                   options=[5, 20, 60], value=20)

    if st.button("Start lesson", type="primary", disabled=not topic):
        profile = LearnerProfile(
            level=level,
            language=language,
            time_minutes=minutes,
            goal=goal or None,
        )
        with st.spinner("Reading your material and planning the lesson…"):
            session = orch.start_session(topic, profile, save_upload(uploaded))
            segment = orch.step(session)
        st.session_state.session = session
        st.session_state.segment = segment
        st.session_state.phase = "lesson"
        st.rerun()


# ---------------------------------------------------------------------------
# Screen 2 — Lesson
# ---------------------------------------------------------------------------

def screen_lesson() -> None:
    session = st.session_state.session
    segment = st.session_state.segment

    plan = session.plan
    done = min(session.current_concept, len(plan.concepts))
    st.progress(done / len(plan.concepts),
                text=f"{plan.topic} — concept {min(done + 1, len(plan.concepts))} "
                     f"of {len(plan.concepts)}")

    if segment is None:
        st.success("That's the whole lesson.")
        if st.session_state.report is not None:
            # Already finished. Streamlit cannot switch tabs for the student,
            # so say where the report went rather than offering the button
            # again and looking like nothing happened.
            st.info("Your report is ready — open the **Report** tab above.")
            return
        if st.button("Finish and see my report", type="primary"):
            st.session_state.report = orch.finish(session)
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

    if st.session_state.last_feedback:
        st.info(st.session_state.last_feedback)

    if segment.question is None:
        if st.button("Continue"):
            _advance(session)
        return

    with st.form("answer_form", clear_on_submit=True):
        st.write(f"**{segment.question.prompt}**")
        if segment.question.kind == "mcq" and segment.question.options:
            reply = st.radio("Your answer", segment.question.options,
                             label_visibility="collapsed")
        else:
            reply = st.text_input("Your answer", label_visibility="collapsed")
        submitted = st.form_submit_button("Answer", type="primary")

    if submitted and reply:
        evaluation = orch.answer(
            session,
            StudentResponse(question_id=segment.question.id, answer=reply),
        )
        st.session_state.last_feedback = evaluation.feedback
        _advance(session)


def _advance(session) -> None:
    """Fetch the next segment — which may be a re-explanation of this one."""
    rt = orch.runtime(session)
    if rt.pending is not None or not orch.is_finished(session):
        st.session_state.segment = orch.step(session)
    else:
        st.session_state.segment = None
    st.rerun()


# ---------------------------------------------------------------------------
# Screen 3 — History
# ---------------------------------------------------------------------------

def screen_history() -> None:
    session = st.session_state.session
    if session is None or not session.turns:
        st.caption("Nothing yet.")
        return

    icons = {"teacher": "🎓", "student": "🙋", "system": "⚙️"}
    for turn in session.turns:
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
        for key in ("phase", "session", "segment", "report", "last_feedback"):
            st.session_state.pop(key, None)
        init_state()
        st.rerun()


# ---------------------------------------------------------------------------

adaptation_panel()

if st.session_state.phase == "setup":
    screen_setup()
else:
    lesson_tab, history_tab, report_tab = st.tabs(
        ["Lesson", "History", "Report"]
    )
    with lesson_tab:
        screen_lesson()
    with history_tab:
        screen_history()
    with report_tab:
        screen_report()
