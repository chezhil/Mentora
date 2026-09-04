"""Study Planner — daily goals, streak tracking, weekly overview.

Shows the student's study habits: daily goal progress, current streak,
and a simple weekly calendar. Inspired by HEXAGON's Planner page.
"""

import streamlit as st

import orchestrator as orch
from ui.i18n import t


def render_planner(session, lang: str = "en") -> None:
    student_id = st.session_state.get("student_id", "student")

    st.markdown(f'<div class="section-label" data-reveal>{t("planner.title", lang)}</div>',
                unsafe_allow_html=True)
    st.caption(t("planner.desc", lang))

    # ── Stats row ───────────────────────────────────────────────────────
    today = orch.goals_today(student_id)
    mem = orch.goal_memory(student_id)
    goal = int(today.get("goal", 0))
    done = int(today.get("done", 0))
    met = mem.get("met", 0) if mem else 0
    streak = 0
    try:
        stats = orch.stats_dashboard(student_id)
        streak = stats.get("streak", 0)
    except Exception:
        pass

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f'<div class="stat-card" data-reveal data-tilt>'
            f'<div class="stat-card-value">🔥 {streak}</div>'
            f'<div class="stat-card-label">{t("planner.streak", lang)}</div>'
            f'</div>', unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="stat-card" data-reveal data-tilt>'
            f'<div class="stat-card-value">{goal}</div>'
            f'<div class="stat-card-label">{t("planner.goal", lang)}</div>'
            f'</div>', unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="stat-card" data-reveal data-tilt>'
            f'<div class="stat-card-value">{done}</div>'
            f'<div class="stat-card-label">{t("planner.reviews", lang)}</div>'
            f'</div>', unsafe_allow_html=True,
        )

    # ── Today's goal progress ───────────────────────────────────────────
    st.markdown(f"#### {t('planner.today', lang)}")
    if goal <= 0:
        st.info(t("planner.no_goal", lang))
    else:
        if done >= goal:
            st.success(t("path.goal_met", lang))
        st.progress(min(done / max(goal, 1), 1.0))
        st.caption(f"{done}/{goal} {t('flashcards.reviewed', lang)}")

    # ── This week ───────────────────────────────────────────────────────
    st.markdown(f"#### {t('planner.this_week', lang)}")
    daily = mem.get("daily", [0]*7) if mem else [0]*7
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    cols = st.columns(7)
    for i, col in enumerate(cols):
        with col:
            count = daily[i] if i < len(daily) else 0
            active = count > 0
            color = "var(--nb-yellow)" if active else "var(--nb-card)"
            st.markdown(
                f'<div style="text-align:center;padding:0.5rem;'
                f'background:{color};border-radius:4px;border:2px solid #000;">'
                f'<div style="font-size:0.7rem;font-weight:700;color:{"#000" if active else "var(--nb-text-dim)"};">'
                f'{days[i]}</div>'
                f'<div style="font-size:1.1rem;font-weight:900;color:{"#000" if active else "var(--nb-text-dim)"};">'
                f'{count}</div>'
                f'</div>', unsafe_allow_html=True,
            )
