"""Screen 2 — Lesson.

Extracted from app.py. All shared state helpers live in screens._state.
"""

import os
from datetime import datetime, timezone

import streamlit as st

import orchestrator as orch
import ui.voice as voice
from screens._state import _lang, _t, _set_language, _busy, _claim, _release, _friendly
from shared import languages
from shared.models import StudentResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _language_switch(session) -> None:
    """Change the teaching language immediately mid-lesson."""
    codes = languages.codes()
    current = session.profile.language
    index = codes.index(current) if current in codes else 0

    chosen = st.selectbox(
        _t("setup.language"), codes, index=index,
        format_func=languages.label,
        key=f"lang_switch_{session.session_id}",
        label_visibility="collapsed",
        help=_t('lesson.switch_help'),
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
            _set_language(chosen)
            st.rerun()


def _followup_box(session) -> None:
    """Let the student ask their own question mid-lesson."""
    with st.expander(_t("lesson.ask")):
        with st.form(f"followup_{session.session_id}", clear_on_submit=True):
            question = st.text_input(
                _t("lesson.ask"), label_visibility="collapsed",
                placeholder=_t("lesson.ask_ph"))
            asked = st.form_submit_button(_t("lesson.ask_button"),
                                          disabled=_busy())

        if asked and question.strip():
            st.session_state.busy = None
            token = f"ask:{session.session_id}:{len(session.turns)}"
            if not _claim(token):
                st.info(_t('lesson.still_answering'))
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


def _socratic_chips(session, segment) -> None:
    """Quick-action Socratic prompts."""
    if segment is None or _busy():
        return

    chips = [
        ("💡 " + _t("socratic.simpler"), "Explain this concept more simply, with a real-world analogy."),
        ("📝 " + _t("socratic.example"), "Give me a concrete example of this concept."),
        ("✅ " + _t("socratic.check"), "Quiz me on what you just explained — ask a quick question."),
        ("🔗 " + _t("socratic.connect"), "How does this connect to what I learned before?"),
    ]
    cols = st.columns(len(chips))
    for col, (label, prompt) in zip(cols, chips):
        with col:
            if st.button(label, key=f"chip_{session.session_id}_{segment.concept_id}_{label}",
                         use_container_width=True):
                st.session_state.busy = None
                token = f"chip:{session.session_id}:{segment.concept_id}:{label}"
                if not _claim(token):
                    st.stop()
                try:
                    with st.spinner(_t("lesson.thinking")):
                        reply = orch.ask(session, prompt)
                except Exception as exc:
                    _release(token, completed=False)
                    st.error(_friendly(exc))
                    st.stop()
                _release(token, completed=True)
                st.session_state.last_followup = (label, reply)
                st.rerun()


def _advance(session) -> None:
    """Fetch the next segment — which may be a re-explanation of this one."""
    rt = orch.runtime(session)
    st.session_state.busy = None
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
# Main screen
# ---------------------------------------------------------------------------

def screen_lesson() -> None:
    session = st.session_state.session
    segment = st.session_state.segment

    if _busy():
        st.session_state.busy = None

    if segment is not None and segment.question is not None:
        orch.remember_question(session, segment.question)

    plan = session.plan
    done = min(session.current_concept, len(plan.concepts))

    bar, timer_col, lang_col = st.columns([4, 1, 1])
    with bar:
        st.progress(done / len(plan.concepts),
                    text=f"{plan.topic} — {_t('lesson.concept')} "
                         f"{min(done + 1, len(plan.concepts))} "
                         f"{_t('lesson.of')} {len(plan.concepts)}")
    with timer_col:
        if session.started_at:
            elapsed = (datetime.now(timezone.utc) - session.started_at).total_seconds()
            mins, secs = divmod(int(elapsed), 60)
            st.metric("⏱️", f"{mins}:{secs:02d}", label_visibility="collapsed")
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
                st.info(_t("lesson.already_building"))
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
            st.video(media.video_mp4)
        else:
            st.info(_t("lesson.no_video"))
        st.write(segment.script)
        if st.button(_t('lesson.read_aloud'), key=f"tts_{session.session_id}_{segment.concept_id}"):
            voice.speak_text(segment.script)
        if media.audio_wav and os.path.exists(media.audio_wav):
            st.audio(media.audio_wav)

    with visual:
        if media.visual_png and os.path.exists(media.visual_png):
            st.image(media.visual_png, caption=segment.visual.caption)
        else:
            st.caption(f"visual: {segment.visual.kind}")

        if segment.visual.kind in ("diagram", "concept_map", "timeline") and segment.visual.payload:
            payload = segment.visual.payload.strip()
            if any(k in payload.lower() for k in ["graph", "flowchart", "timeline", "-->", "->"]):
                with st.expander("🔍 Interactive Diagram Preview", expanded=False):
                    st.markdown(f"```mermaid\n{payload}\n```")

        for note in media.notes:
            st.caption(f"⚠️ {note}")

    act_col1, act_col2 = st.columns([1, 1])
    with act_col1:
        if st.button(_t('lesson.explain_differently'),
                     key=f"diff_{session.session_id}_{segment.concept_id}_{session.attempts.get(segment.concept_id, 0)}",
                     disabled=_busy()):
            token = f"regen:{session.session_id}:{len(session.turns)}"
            if _claim(token):
                try:
                    with st.spinner(_t('lesson.preparing_fresh')):
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
    _socratic_chips(session, segment)

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
        st.session_state.busy = None
        token = f"skip:{session.session_id}:{segment.question.id}"
        if _claim(token):
            orch.skip(session, segment.question.id)
            _release(token, completed=True)
            st.session_state.last_feedback = None
            _advance(session)

    if submitted:
        st.session_state.busy = None
        if not reply or not str(reply).strip():
            st.warning(_t("lesson.pick_first"))
            return

        token = f"answer:{session.session_id}:{segment.question.id}"
        if not _claim(token):
            st.info(_t('lesson.answer_marked'))
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
