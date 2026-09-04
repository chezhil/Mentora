"""My Learning — past lessons as courses with progress.

Shows every past lesson as a card with score, weak spots, and a resume
button. Inspired by HEXAGON's 'Continue Learning' section.
"""

import streamlit as st

import orchestrator as orch
from ui.i18n import t


def render_learning(session, lang: str = "en") -> None:
    student_id = st.session_state.get("student_id", "student")
    reports = orch.past_reports(student_id)

    st.markdown(f'<div class="section-label" data-reveal>{t("learning.title", lang)}</div>',
                unsafe_allow_html=True)
    st.caption(t("learning.desc", lang))

    if not reports:
        st.info(t("learning.no_lessons", lang))
        return

    # Show lessons as cards (newest first)
    for r in reversed(reports):
        score = r.score
        mark = "🟥" if score < 50 else "🟨" if score < 75 else "🟩"
        weak_str = " · ".join(r.weak[:3]) if r.weak else "—"

        st.markdown(
            f'<div class="past-card shine-hover" data-reveal data-tilt>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<div>'
            f'<span class="past-score">{mark} {score:.0f}%</span> '
            f'<span class="past-weak"> — {r.next_topic}</span>'
            f'</div>'
            f'</div>'
            f'<div style="margin-top:0.4rem;font-size:0.8rem;color:var(--nb-text-dim);">'
            f'{t("learning.weak", lang)}: {weak_str}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
