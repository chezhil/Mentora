"""Screen 3 — History.

Extracted from app.py.
"""

import streamlit as st

import orchestrator as orch
from screens._state import _t


def screen_history() -> None:
    student_id = st.session_state.get("student_id", "student")

    past = []
    if orch.history is not None:
        try:
            past = orch.history.load_session_summaries(student_id)
        except Exception:
            pass

    if past:
        st.markdown(f'<div class="section-label" data-reveal>{_t("history.past_sessions")}</div>',
                    unsafe_allow_html=True)
        for s in past:
            try:
                date_str = s["date"][:10] if s["date"] else ""
            except Exception:
                date_str = ""
            score = s["score"]
            mark = "🟥" if score < 50 else "🟨" if score < 75 else "🟩"
            st.markdown(
                f'<div class="session-timeline-item shine-hover" data-reveal data-tilt>'
                f'<span class="session-timeline-date">{date_str}</span>'
                f'<span class="session-timeline-score">{mark} {score:.0f}%</span>'
                f'<span class="session-timeline-topic">{s["topic"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown("---")

    session = st.session_state.session
    if session is None:
        if not past:
            st.caption(_t("history.empty"))
        return

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

    st.markdown(f'<div class="section-label">Current Session · {len(turns)} turns</div>',
                unsafe_allow_html=True)

    icons = {"teacher": "🎓", "student": "🙋", "system": "⚙️"}
    for turn in turns:
        stamp = turn.timestamp.strftime("%H:%M:%S")
        tag = f" · {turn.concept_id}" if turn.concept_id else ""
        st.markdown(
            icons.get(turn.role, "•") + " **" + turn.role.title() + "** `" + stamp + tag + "`"
        )
        st.write(turn.content)
        st.divider()
