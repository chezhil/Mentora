"""Page 2 — The Lesson.  OWNER: Jyothi (frontend).

Runs under app_v2.py multipage. This page teaches the current segment,
shows the teacher's live reasoning (the adaptation panel), lets the student
answer, and lets them ask their own follow-up questions.

Only the orchestrator is called here. Never import teacher/, planner/,
ingest/, prompt_101/ or wiring directly — orchestrator wraps them all and
owns the failure handling.
"""

import os

import streamlit as st

import orchestrator as orch
from shared import languages
from shared.models import StudentResponse
import ui
ui.apply_theme()

# One source of truth for the language list — see shared/languages.py. The
# literal dict that used to live here offered five languages while app.py
# offered eight and the voice service supported more still, so which languages
# existed depended on which screen you asked.
LANGUAGES = {code: languages.label(code) for code in languages.codes()}

# ---------------------------------------------------------------------------
# Concurrency guards. Two layers, because alone neither is enough:
#   busy flag   - greys every button out while one call is in flight, so a
#                 double click cannot spend double Gemini quota
#   done tokens - an action already completed can never run twice, even if the
#                 flag were lost to a cancelled script run
# ---------------------------------------------------------------------------

def _busy() -> bool:
    return st.session_state.get("busy") is not None


def _claim(token: str) -> bool:
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
    msg = str(exc)
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        return ("**Gemini quota exhausted.** One lesson costs 10-15 requests "
                "and the free tier is 20/day. Switch on offline mode or paste "
                "another team key, then continue.")
    if "API key not valid" in msg or "PERMISSION_DENIED" in msg:
        return ("**Gemini rejected that API key.** Paste a valid one (from "
                "Google AI Studio, starts with AIza).")
    return f"Something went wrong: `{msg[:200]}`"


# ---------------------------------------------------------------------------
# The adaptation panel — the single highest-value thing on this screen.
# The rubric rewards a system that visibly understands WHY a student got a
# question wrong and changes its approach. Every field is shown so a judge
# can see the adaptation happen, live.
# ---------------------------------------------------------------------------

def _adaptation_panel(session) -> None:
    st.sidebar.markdown("## Teacher reasoning")

    panel = orch.runtime(session).panel

    if panel.concept_name:
        st.sidebar.caption("Now teaching")
        st.sidebar.markdown(f"**{panel.concept_name}**")

    if panel.retrieved:
        pages = ", ".join(str(p) for p in panel.grounded_pages) or "—"
        st.sidebar.caption("Grounding")
        st.sidebar.markdown(f"{panel.retrieved} chunks · pages {pages}")

    st.sidebar.divider()

    if not panel.answered:
        st.sidebar.caption("Waiting for the first answer.")
        return

    if panel.correct:
        st.sidebar.success("Answer: correct")
    else:
        st.sidebar.error("Answer: incorrect")

    if panel.misconception:
        st.sidebar.markdown("**Misconception**")
        # A warning alert: the CSS turns this into a red callout — the most
        # visible evidence that the teacher adapted.
        st.sidebar.warning(panel.misconception)

    if panel.action_taken:
        line = f"**Action:** {panel.action_taken}"
        if panel.escalated:
            line += (f"  \n_(Pair B said {panel.action_from_pair_b}; "
                     f"escalated on attempt {panel.attempt})_")
        st.sidebar.markdown(line)

    if panel.analogy:
        st.sidebar.markdown(f"**Analogy:** {panel.analogy}")

    if panel.difficulty:
        st.sidebar.markdown(f"**Difficulty:** {panel.difficulty}")

    if panel.attempt:
        st.sidebar.markdown(f"**Attempt:** {panel.attempt}")


# ---------------------------------------------------------------------------
# Language switch — the brief asks us to re-teach in another language
# mid-conversation. It takes effect on the next part, which is fine and costs
# no extra Gemini call.
# ---------------------------------------------------------------------------

def _language_switch(session) -> None:
    codes = list(LANGUAGES)
    current = session.profile.language
    index = codes.index(current) if current in codes else 0

    chosen = st.selectbox(
        "Language", codes, index=index,
        format_func=lambda c: LANGUAGES[c],
        key=f"lang_{session.session_id}",
        label_visibility="collapsed",
        help="Switch mid-lesson. Applies from the next part onwards.",
    )
    if chosen != current:
        session.profile.language = chosen
        orch.note(session,
                  f"Student switched teaching language to {LANGUAGES[chosen]}.")
        st.session_state.lang_note = (
            f"Switched to {LANGUAGES[chosen]} — from the next part onwards."
        )
        st.rerun()


def _advance(session) -> None:
    """Fetch the next segment, which may be a re-explanation of this one."""
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
# Render. The body lives in one function so `return` is legal at each branch
# (a page script cannot use top-level return). `st.stop()` is reserved for the
# hard halt when there is no session.
# ---------------------------------------------------------------------------

def _render() -> None:
    # .get() rather than ["session"] so a fresh session (before app_v2 has had
    # a chance to set defaults) falls through to the guard instead of raising.
    session = st.session_state.get("session")
    if session is None:
        st.info("Start a lesson on the **Setup** page first.")
        st.stop()

    plan = session.plan
    segment = st.session_state.segment

    done = min(session.current_concept, len(plan.concepts))
    bar, lang = st.columns([4, 1])
    with bar:
        st.progress(
            done / len(plan.concepts),
            text=f"{plan.topic} · concept {min(done + 1, len(plan.concepts))} "
                 f"of {len(plan.concepts)}",
        )
    with lang:
        _language_switch(session)

    _adaptation_panel(session)

    if st.session_state.get("lang_note"):
        st.success(st.session_state.pop("lang_note"))
    if st.session_state.get("last_feedback"):
        st.info(st.session_state.pop("last_feedback"))

    if segment is None:
        # Whole lesson done.
        st.success("That's the whole lesson.")
        if st.session_state.report is not None:
            st.info("The lesson is finished! Open the **Quiz** page to take your final assessment.")
            return
        if st.button("Finish and take the Final Quiz", type="primary",
                     disabled=_busy()):
            token = f"finish:{session.session_id}"
            if not _claim(token):
                st.info("Preparing your quiz...")
                st.stop()
            try:
                with st.spinner("Preparing your final quiz..."):
                    st.session_state.report = orch.finish(session)
            except Exception as exc:
                _release(token, completed=False)
                st.error(_friendly(exc))
                st.stop()
            _release(token, completed=True)
            if hasattr(st, "switch_page"):
                st.switch_page("pages/3_Quiz.py")
            else:
                st.rerun()
        return

    media = orch.media_for(session, segment)

    video, visual = st.columns([3, 2])
    with video:
        if media.video_mp4 and os.path.exists(media.video_mp4):
            # The teacher is drawn into the video frames, so no overlay: a
            # second copy of her would sit on the fullscreen button.
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
            st.caption(note)

    # Citations — the proof the lesson is grounded in the student's material.
    if segment.citations:
        with st.expander(
                f"From your material ({len(segment.citations)} passages)"):
            for c in segment.citations:
                where = f"page {c.page}" if c.page else "unknown page"
                st.markdown(f"**{where}** · relevance {c.score:.2f}")
                st.caption(c.text)
    elif session.doc_id:
        st.caption("Nothing in your material covers this — taught from general "
                   "knowledge.")

    # The student's own mid-lesson question (orchestrator.ask).
    with st.expander("Ask me something about this"):
        with st.form(f"followup_{session.session_id}", clear_on_submit=True):
            question = st.text_input(
                "Your question", label_visibility="collapsed",
                placeholder="e.g. why does the water-pipe analogy work?")
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

    if st.session_state.get("last_followup"):
        q, a = st.session_state.pop("last_followup")
        st.markdown(f"**You:** {q}")
        st.write(a)

    if segment.question is None:
        if st.button("Continue", disabled=_busy()):
            _advance(session)
        return

    # Answer the current question.
    with st.form("answer_form", clear_on_submit=True):
        st.markdown(f"**{segment.question.prompt}**")
        if segment.question.kind == "mcq" and segment.question.options:
            reply = st.radio("Your answer", segment.question.options,
                             label_visibility="collapsed")
        else:
            reply = st.text_input("Your answer", label_visibility="collapsed")
        submitted = st.form_submit_button("Answer", type="primary",
                                          disabled=_busy())

    if submitted and reply:
        token = f"answer:{session.session_id}:{segment.question.id}"
        if not _claim(token):
            st.info("That answer is already being marked…")
            st.stop()
        try:
            with st.spinner("Marking your answer…"):
                evaluation = orch.answer(
                    session,
                    StudentResponse(question_id=segment.question.id,
                                    answer=reply),
                )
        except Exception as exc:
            _release(token, completed=False)
            st.error(_friendly(exc))
            st.stop()
        _release(token, completed=True)
        st.session_state.last_feedback = evaluation.feedback
        _advance(session)


_render()
