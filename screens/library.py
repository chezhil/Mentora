"""Library — uploaded materials and document history.

Shows every uploaded document as a card with upload date and associated
lesson count. Inspired by HEXAGON's Library page.
"""

import streamlit as st

import orchestrator as orch
from ui.i18n import t


def render_library(session, lang: str = "en") -> None:
    student_id = st.session_state.get("student_id", "student")

    st.markdown(f'<div class="section-label" data-reveal>{t("library.title", lang)}</div>',
                unsafe_allow_html=True)
    st.caption(t("library.desc", lang))

    # Get past reports to find uploaded materials
    reports = orch.past_reports(student_id)
    if not reports:
        st.info(t("library.empty", lang))
        return

    # List uploaded materials from session history
    seen_materials = set()
    for r in reports:
        topic = r.next_topic or "Untitled"
        if topic not in seen_materials:
            seen_materials.add(topic)
            score = r.score
            mark = "🟥" if score < 50 else "🟨" if score < 75 else "🟩"
            st.markdown(
                f'<div class="past-card shine-hover" data-reveal data-tilt>'
                f'<span class="past-score">{mark}</span> '
                f'<span style="font-weight:700;">{topic}</span> '
                f'<span class="past-weak"> · {score:.0f}% avg</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
