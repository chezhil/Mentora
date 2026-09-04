"""Progress dashboard + learning path screen.

The Path tab now doubles as the student's dashboard: streaks, XP and level,
score trend, per-concept mastery, a 28-day activity grid, and the weak spots
diagnosed across lessons. The AI-generated learning path (Section 15 of the
brief) sits underneath, restyled to the dark neo-brutalist theme.
"""

import streamlit as st

import orchestrator as orch
from screens import flashcards as fc
from ui.i18n import t


def _badge_title(badge: dict, lang: str) -> str:
    return t(f"badge.{badge['id']}.title", lang)


def _ring_html(value: float, max_val: float, label: str, color: str = "#eab308", size: int = 80) -> str:
    """SVG donut ring for metrics."""
    pct = min(value / max(max_val, 1), 1.0)
    circumference = 2 * 3.14159 * (size // 2 - 6)
    offset = circumference * (1 - pct)
    return (
        f'<div style="text-align:center;">'
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<circle cx="{size//2}" cy="{size//2}" r="{size//2-6}" fill="none"'
        f' stroke="#27272a" stroke-width="5"/>'
        f'<circle cx="{size//2}" cy="{size//2}" r="{size//2-6}" fill="none"'
        f' stroke="{color}" stroke-width="5" stroke-linecap="round"'
        f' stroke-dasharray="{circumference}" stroke-dashoffset="{offset}"'
        f' transform="rotate(-90 {size//2} {size//2})"'
        f' style="transition: stroke-dashoffset 1s ease;"/>'
        f'<text x="{size//2}" y="{size//2+1}" text-anchor="middle" dominant-baseline="middle"'
        f' font-family="JetBrains Mono" font-weight="800" font-size="{size//4}px"'
        f' fill="{color}">{value:.0f}</text>'
        f'</svg>'
        f'<div style="font-size:0.65rem;font-weight:600;color:var(--text-tertiary);'
        f' text-transform:uppercase;letter-spacing:0.08em;margin-top:0.2rem;">{label}</div>'
        f'</div>'
    )


def render_path(session, lang: str = "en") -> None:
    student_id = st.session_state.get("student_id", "student")
    stats = orch.stats_dashboard(student_id)
    topic = session.plan.topic if session is not None else None

    if session is None and not stats["reports"]:
        st.info(t("path.locked", lang))
        return

    st.markdown(
        f"""
        <div class="hero-banner" style="padding:1rem 1rem 0.5rem 1rem;">
          <h1 style="font-size:1.8rem; margin:0;">{t("path.dashboard_title", lang)}</h1>
          <p class="hero-sub" style="font-size:0.9rem;">{student_id}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Headline stats — modern stat card grid
    # ------------------------------------------------------------------
    # Ring stat cards
    lessons_val = stats["lessons"]
    streak_val = stats["streak"]
    xp_val = stats["xp"]
    score_val = int(stats["avg_score"])
    level, into, need = stats["level"], stats["xp_into_level"], stats["xp_for_next"]

    ring1 = _ring_html(lessons_val, max(lessons_val + 5, 10), t('path.ring_lessons', lang), '#eab308', 90)
    ring2 = _ring_html(streak_val, max(streak_val + 5, 14), t('path.ring_streak', lang), '#ef4444', 90)
    ring3 = _ring_html(xp_val, need, f"Lvl {level}", '#06b6d4', 90)
    ring4 = _ring_html(score_val, 100, t('path.ring_score', lang), '#22c55e', 90)

    st.markdown(
        f"""
        <div class="skel-row">
        <div class="skel-ring-card" data-reveal>{ring1}</div>
        <div class="skel-ring-card" data-reveal>{ring2}</div>
        <div class="skel-ring-card" data-reveal>{ring3}</div>
        <div class="skel-ring-card" data-reveal>{ring4}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Level progress bar (elevated card)
    pct = max(2, 100 * into // need) if need > 0 else 0
    st.markdown(
        f"""
        <div class="skel-card" style="border-left:3px solid var(--accent);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem;">
        <span class="skel-card-title" style="color:var(--accent);">{t('path.level', lang).format(level=level)}</span>
        <span style="font-family:JetBrains Mono;font-size:0.8rem;color:var(--text-tertiary);">
        {t('path.xp_progress', lang).format(xp_into=into, xp_need=need, next_level=level + 1)}</span>
        </div>
        <div style="background:var(--bg-tertiary);border-radius:6px;height:10px;overflow:hidden;">
        <div style="background:linear-gradient(90deg, #eab308, #facc15);height:100%;
        width:{pct}%;border-radius:6px;transition:width 0.8s ease;"></div>
        </div></div>
        """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Due-for-review queue — the dashboard's call to action: whatever spaced
    # repetition (including every missed question) flags for right now can be
    # flipped and rated here, with the same widget as the Flashcards tab.
    # ------------------------------------------------------------------
    due_cards = orch.due_reviews(student_id)
    if due_cards:
        st.markdown(f"#### {t('path.due_heading', lang)}")
        st.caption(t("path.due_hint", lang))
        if st.session_state.get("pd_last"):
            ease, interval = st.session_state.pop("pd_last")
            st.caption(fc.interval_note(ease, interval, lang))
        for card in due_cards:
            result = fc.review_card(student_id, card, lang, ns="pd_queue",
                                    position=t("flashcards.pos_due", lang))
            if result is not None:
                st.session_state.pd_last = result
                st.rerun()
    else:
        learned = (stats.get("reviews") or {}).get("learned", 0)
        if learned:
            st.caption(t("path.due_none", lang).format(n=str(learned)))

    # ------------------------------------------------------------------
    # Daily goal — cards reviewed today vs the student's own target.
    # ------------------------------------------------------------------
    st.markdown(f"#### {t('path.goal_title', lang)}")
    today = orch.goals_today(student_id)
    goal = int(today.get("goal", 0))
    done = int(today.get("done", 0))
    edit = int(st.number_input(
        t("path.goal_label", lang), min_value=0, max_value=200, step=1,
        value=goal, key=f"dg_{student_id}"))
    # Only persist when the student actually changes the target. Reading the
    # widget back (value=goal) never fires this, so merely viewing the
    # dashboard cannot set or resurrect a goal the student cleared to 0.
    if edit != goal:
        orch.set_daily_goal(student_id, edit)
        st.rerun()
    if edit <= 0:
        st.caption(t("path.goal_none", lang))
    else:
        if done >= edit:
            st.success(t("path.goal_met", lang))
        st.caption(t("path.goal_today", lang).format(done=str(done),
                                                     goal=str(edit)))
        st.progress(min(done / max(edit, 1), 1.0))
    # Activity memory strip — visible even without a goal to nudge the
    # student toward setting one ("you studied 3 of 7 days, set a goal").
    mem = orch.goal_memory(student_id)
    if mem and mem.get("daily") is not None:
        if edit > 0 and mem.get("met") is not None:
            st.caption(t("path.goal_memory", lang).format(
                met=str(mem["met"]), days=str(mem["days"])))
        elif edit <= 0:
            active = sum(1 for d in mem["daily"] if d > 0)
            if active:
                st.caption(t("path.activity_memory", lang).format(
                    active=str(active), days=str(mem["days"])))

    # ------------------------------------------------------------------
    # Achievements — badges decided by the aggregates above (history/badges).
    # ------------------------------------------------------------------
    st.markdown(f"#### {t('path.badges_title', lang)}")
    ach = orch.badges_for(student_id)
    earned = ach.get("earned") or []
    locked = ach.get("locked") or []
    nxt = ach.get("next")
    if not earned and not locked:
        st.caption(t("path.badges_empty", lang))
    else:
        if earned:
            row = " · ".join(f'{b["icon"]} {_badge_title(b, lang)}'
                             for b in earned)
            st.markdown(
                f'<div class="pd-card"><div class="pd-card-title">'
                f'{t("path.badges_earned", lang)}</div>'
                f'<div class="pd-card-hint">{row}</div></div>',
                unsafe_allow_html=True,
            )
        if locked:
            st.markdown(
                f'<div class="pd-card"><div class="pd-card-title">'
                f'{t("path.badges_locked", lang)}</div></div>',
                unsafe_allow_html=True,
            )
            # Every locked badge explains how to earn it and how close the
            # student is — opaque rows were the gap, not the catalog.
            for badge in locked:
                how = t(f"badge.{badge['id']}.how", lang)
                line = f"🔒 {badge['icon']} {_badge_title(badge, lang)} — {how}"
                if badge.get("target") is not None:
                    frac = t("path.badges_progress", lang).format(
                        value=str(badge["value"]),
                        target=str(badge["target"]))
                    line += f" · {frac}"
                st.caption(line)
        if nxt:
            hint = f"{nxt['icon']} {_badge_title(nxt, lang)}"
            if nxt.get("remaining"):
                hint += f" · {t('path.badges_to_go', lang).format(n=str(nxt['remaining']))}"
            st.caption(f"{t('path.badges_next_label', lang)} {hint}")

    st.divider()

    # ------------------------------------------------------------------
    # Charts row
    # ------------------------------------------------------------------
    left, right = st.columns(2)

    with left:
        st.markdown(f'#### {t("path.score_trend", lang)}')
        scores = stats.get("score_history") or []
        if len(scores) >= 2:
            chart = {"Lesson": [f"{i + 1}" for i in range(len(scores))],
                     "Score": [s["score"] for s in scores]}
            st.line_chart(chart, x="Lesson", y="Score", color="#FFE600")
        elif len(scores) == 1:
            st.write(t('path.score_single', lang).format(
                score=f"{scores[0]['score']:.0f}",
                topic=scores[0]['topic'] or 'lesson'))
            st.caption(t('path.trend_hint', lang))
        else:
            st.info(t('path.no_lessons', lang) + ' — ' + t('path.no_lessons_hint', lang))

    with right:
        st.markdown(f'#### {t("path.concept_mastery", lang)}')
        mastery = stats.get("mastery") or []
        if mastery:
            chart = {
                "Concept": [m["concept"][:18] for m in mastery],
                "Accuracy (%)": [m["accuracy"] for m in mastery],
            }
            st.bar_chart(chart, x="Concept", y="Accuracy (%)", color="#00E5FF")
        else:
            st.info(t('path.no_answers', lang) + ' — ' + t('path.no_answers_hint', lang))

    st.divider()

    # ------------------------------------------------------------------
    # Activity grid — the last 28 days, one tile per day.
    # ------------------------------------------------------------------
    activity = stats.get("activity") or []
    if activity:
        st.markdown(f'#### {t("path.last_28_days", lang)}')
        tiles = "".join(
            f'<span class="pd-day {"pd-day-on" if d["active"] else ""}" '
            f'title="{d["date"]}"></span>'
            for d in activity
        )
        st.markdown(f'<div class="pd-grid">{tiles}</div>',
                    unsafe_allow_html=True)
        st.caption(t('path.streak_caption', lang).format(streak=stats['streak']))

    # ------------------------------------------------------------------
    # Weak + Strong concepts
    weak = list(dict.fromkeys(w for r in stats["reports"] for w in r.weak))
    miscon = list(dict.fromkeys(m for r in stats["reports"] for m in r.misconceptions))
    strong = list(dict.fromkeys(s for r in stats["reports"] for s in r.strong))
    if weak or miscon or strong:
        st.markdown(f'#### {t("path.concept_analysis", lang)}')
        cw1, cw2 = st.columns(2)
        with cw1:
            items = (weak or miscon)[:5]
            if items:
                items_html = "".join(
                    f'<div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0;'
                    f'border-bottom:1px solid var(--border-subtle);">'
                    f'<span style="color:var(--red);">⚠</span>'
                    f'<span style="font-size:0.8rem;color:var(--text-secondary);">{item}</span>'
                    f'</div>'
                    for item in items
                )
                st.markdown(
                    f'<div class="skel-card" style="border-left:3px solid var(--red);">'
                    f'<div class="skel-card-title" style="color:var(--red);">{t("path.needs_work", lang)}</div>'
                    f'{items_html}</div>',
                    unsafe_allow_html=True,
                )
        with cw2:
            if strong:
                items_html = "".join(
                    f'<div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0;'
                    f'border-bottom:1px solid var(--border-subtle);">'
                    f'<span style="color:var(--green);">✓</span>'
                    f'<span style="font-size:0.8rem;color:var(--text-secondary);">{item}</span>'
                    f'</div>'
                    for item in strong[:5]
                )
                st.markdown(
                    f'<div class="skel-card" style="border-left:3px solid var(--green);">'
                    f'<div class="skel-card-title" style="color:var(--green);">{t("path.mastered", lang)}</div>'
                    f'{items_html}</div>',
                    unsafe_allow_html=True,
                )

    # ------------------------------------------------------------------
    # Learning path (Section 15 of the brief) — kept, dark-styled.
    # ------------------------------------------------------------------
    if topic:
        st.divider()
        st.markdown(f'### {t("path.learning_path", lang).format(topic=topic)}')
        st.caption(t('path.learning_path_desc', lang))

        steps = orch.learning_path_for(topic)
        if steps:
            for idx, step_item in enumerate(steps, start=1):
                if " - " in step_item:
                    title, desc = step_item.split(" - ", 1)
                elif ": " in step_item:
                    title, desc = step_item.split(": ", 1)
                else:
                    title, desc = step_item, ""

                is_current = (topic.lower() in title.lower()
                              or title.lower() in topic.lower())
                here = (f"<span class='pd-here'>{t('path.you_are_here', lang)}</span><br>"
                        if is_current else "")
                st.markdown(
                    f"""
                    <div class="pd-step {"pd-step-current" if is_current else ""}">
                      {here}
                      <div class="pd-step-title">{idx}. {title}</div>
                      <div class="pd-step-desc">{desc}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )