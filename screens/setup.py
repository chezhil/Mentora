"""Screen 1 — Setup (Hero Landing).

Extracted from app.py. All shared state helpers live in screens._state.
"""

import os

import streamlit as st

import orchestrator as orch
from screens._state import _lang, _t, _busy, _claim, _release, _friendly, save_upload
from shared import languages
from shared.models import LearnerProfile
from screens import classroom as classroom_screen


# ---------------------------------------------------------------------------
# Helpers
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


def _hero_banner() -> None:
    """Render the hero landing section with role cards."""
    st.markdown(
        """
        <div class="hero-banner" data-reveal>
          <div class="hero-icon float">🎓</div>
          <h1 class="hero-title gradient-text">Mentora</h1>
          <p class="hero-tagline">""" + _t("setup.hero_tag") + """</p>
          <p class="hero-sub">""" + _t("setup.hero_sub") + """</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _role_cards() -> None:
    """Visual role selector as clickable cards instead of radio buttons."""
    current = st.session_state.get("role", "student")
    st.markdown(f'<div class="section-label" data-reveal>{_t("setup.pick_role")}</div>',
                unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        student_active = current == "student"
        if st.button(
            f"🙋  {_t('role.student')}" , key="role_student",
            type="primary" if student_active else "secondary",
            use_container_width=True,
        ):
            if current != "student":
                st.session_state.role = "student"
                st.rerun()
    with c2:
        teacher_active = current == "teacher"
        if st.button(
            f"👩‍🏫  {_t('role.teacher')}", key="role_teacher",
            type="primary" if teacher_active else "secondary",
            use_container_width=True,
        ):
            if current != "teacher":
                st.session_state.role = "teacher"
                st.rerun()


def _past_lessons_preview(student_id: str) -> None:
    """Show past lessons as quick-start cards if any exist."""
    seen = orch.past_reports(student_id)
    if not seen:
        st.caption(_t("setup.no_past"))
        return
    st.markdown(f'<div class="section-label" data-reveal>{_t("setup.past_lessons")}</div>',
                unsafe_allow_html=True)
    for r in seen[-3:][::-1]:
        score = r.score
        mark = "🟥" if score < 50 else "🟨" if score < 75 else "🟩"
        weak_str = " · ".join(r.weak[:2]) if r.weak else "No weak spots"
        st.markdown(
            f'<div class="past-card shine-hover" data-reveal data-tilt>'
            f'<span class="past-score">{mark} {score:.0f}%</span> '
            f'<span class="past-weak">{weak_str}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _interface_language() -> None:
    """Language picker — compact, inline."""
    codes = languages.codes()
    current = _lang()
    chosen = st.selectbox(
        _t("setup.language"), codes,
        index=codes.index(current) if current in codes else 0,
        format_func=languages.label,
        label_visibility="collapsed",
    )
    if chosen != current:
        from screens._state import _set_language
        _set_language(chosen)
        st.rerun()


# ---------------------------------------------------------------------------
# Main screen
# ---------------------------------------------------------------------------

def screen_setup() -> None:
    _hero_banner()
    _role_cards()

    st.markdown("---")
    lang_col, name_col = st.columns([1, 1])
    with lang_col:
        _interface_language()
    with name_col:
        student_id = st.text_input(
            _t("setup.name"),
            value=st.session_state.get("student_id", "student"),
            label_visibility="collapsed",
            placeholder=_t("setup.name"),
        )
        st.session_state.student_id = student_id

    _past_lessons_preview(st.session_state.get("student_id", "student"))

    if st.session_state.role == "teacher":
        _teacher_setup()
        return

    _student_setup_form()


def _student_setup_form() -> None:
    """The lesson configuration form — compact, one column."""
    st.markdown(f'<div class="section-label" data-reveal>{_t("setup.start")}</div>',
                unsafe_allow_html=True)

    topic = st.text_input(_t("setup.topic"), placeholder=_t("setup.topic_ph"))
    uploaded = st.file_uploader(
        _t("setup.material"), type=["pdf", "docx", "pptx", "txt"],
    )

    col_level, col_time = st.columns(2)
    with col_level:
        levels = ["beginner", "intermediate", "advanced"]
        level = st.selectbox(_t("setup.level"), levels,
                             format_func=lambda v: _t(f"level.{v}"))
    with col_time:
        minutes = st.slider(_t("setup.time"), min_value=5, max_value=60,
                            value=20, step=1)

    goal = st.text_input(_t("setup.goal"), placeholder=_t("setup.goal_ph"))

    if st.button(_t("setup.start"), type="primary",
                 disabled=not topic or _busy(),
                 use_container_width=True):
        _begin_lesson(topic, level, minutes, goal, uploaded)


def _begin_lesson(topic, level, minutes, goal, uploaded) -> None:
    """Plan the lesson and open it. Shared by the student and teacher setups."""
    final_topic = (topic or "").strip()
    if not final_topic and uploaded:
        final_topic = os.path.splitext(uploaded.name)[0] \
            .replace("_", " ").replace("-", " ").title()
    if not final_topic:
        st.warning(_t("setup.enter_topic"))
        return

    language = _lang()
    token = f"start:{final_topic}:{level}:{language}:{minutes}"
    if not _claim(token):
        st.info(_t("lesson.already_starting"))
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
        _release(token, completed=False)
        st.error(_friendly(exc))
        st.stop()
    _release(token, completed=True)
    st.session_state.session = session
    st.session_state.segment = segment
    st.session_state.phase = "lesson"
    st.rerun()


def _teacher_setup() -> None:
    """Teacher view — classroom overview first, then lesson preview."""
    st.markdown("---")
    classroom_screen.render_classroom(_lang())
    st.divider()
    st.markdown(f"### {_t('teacher.preview')}")

    topic = st.text_input(_t("setup.topic"), key="teacher_topic",
                          placeholder=_t("setup.topic_ph"))
    uploaded = st.file_uploader(
        _t("setup.material"), type=["pdf", "docx", "pptx", "txt"],
        key="teacher_upload")
    col_l, col_t = st.columns(2)
    with col_l:
        levels = ["beginner", "intermediate", "advanced"]
        level = st.selectbox(_t("setup.level"), levels, key="teacher_level",
                             format_func=lambda v: _t(f"level.{v}"))
    with col_t:
        minutes = st.slider(_t("setup.time"), min_value=5, max_value=60,
                            value=20, step=1, key="teacher_minutes")
    st.session_state.student_id = "teacher preview"
    if st.button(_t("setup.start"), type="primary",
                 disabled=not topic or _busy(), key="teacher_start",
                 use_container_width=True):
        _begin_lesson(topic, level, minutes, None, uploaded)
