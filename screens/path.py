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


def _empty_card(title: str, hint: str) -> None:
    st.markdown(
        f"""
        <div class="pd-card">
          <div class="pd-card-title">{title}</div>
          <div class="pd-card-hint">{hint}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_path(session, lang: str = "en") -> None:
    student_id = st.session_state.get("student_id", "student")
    stats = orch.stats_dashboard(student_id)
    topic = session.plan.topic if session is not None else None

    if session is None and not stats["reports"]:
        st.info(t("path.locked", lang))
        return

    st.subheader("📈 Progress Dashboard")
    st.caption(f"Profile: **{student_id}** · every lesson, every answer, "
               f"every review.")

    # ------------------------------------------------------------------
    # Headline metrics
    # ------------------------------------------------------------------
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Lessons completed", stats["lessons"])
    col2.metric("🔥 Day streak", stats["streak"])
    col3.metric("⚡ XP", f"{stats['xp']}")
    col4.metric("Avg score", f"{stats['avg_score']:.0f}%")

    # Level ladder + progress to the next level.
    level, into, need = stats["level"], stats["xp_into_level"], stats["xp_for_next"]
    st.markdown(
        f"""
        <div class="pd-card">
          <div class="pd-card-row">
            <span class="pd-level">LEVEL {level}</span>
            <span class="pd-card-hint">{into} / {need} XP to level {level + 1}</span>
          </div>
          <div class="pd-xpbar"><div class="pd-xpfill" style="width:{max(2, 100 * into // need)}%"></div></div>
        </div>
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
        st.markdown("#### 📉 Score trend")
        scores = stats.get("score_history") or []
        if len(scores) >= 2:
            chart = {"Lesson": [f"{i + 1}" for i in range(len(scores))],
                     "Score": [s["score"] for s in scores]}
            st.line_chart(chart, x="Lesson", y="Score", color="#FFE600")
        elif len(scores) == 1:
            st.write(f"Score: **{scores[0]['score']:.0f}%** "
                     f"({scores[0]['topic'] or 'lesson'})")
            st.caption("Finish a second lesson to see your trend line.")
        else:
            _empty_card("No lessons yet",
                        "Start a lesson — your score trend appears here.")

    with right:
        st.markdown("#### 🎯 Concept mastery")
        mastery = stats.get("mastery") or []
        if mastery:
            chart = {
                "Concept": [m["concept"][:18] for m in mastery],
                "Accuracy (%)": [m["accuracy"] for m in mastery],
            }
            st.bar_chart(chart, x="Concept", y="Accuracy (%)", color="#00E5FF")
        else:
            _empty_card("No answers yet",
                        "Answer the lesson's questions and each concept's "
                        "accuracy lands here.")

    st.divider()

    # ------------------------------------------------------------------
    # Activity grid — the last 28 days, one tile per day.
    # ------------------------------------------------------------------
    activity = stats.get("activity") or []
    if activity:
        st.markdown("#### 🔥 Last 28 days")
        tiles = "".join(
            f'<span class="pd-day {"pd-day-on" if d["active"] else ""}" '
            f'title="{d["date"]}"></span>'
            for d in activity
        )
        st.markdown(f'<div class="pd-grid">{tiles}</div>',
                    unsafe_allow_html=True)
        st.caption(f"Current streak: **{stats['streak']} day(s)**. "
                   f"Every yellow tile is a day you studied.")

    # ------------------------------------------------------------------
    # Weak spots, gathered from every report.
    # ------------------------------------------------------------------
    weak = list(dict.fromkeys(w for r in stats["reports"] for w in r.weak))
    miscon = list(dict.fromkeys(m for r in stats["reports"] for m in r.misconceptions))
    if miscon or weak:
        st.markdown("#### 🧠 Concepts to revisit")
        for item in (weak or miscon)[:5]:
            st.warning(item)

    # ------------------------------------------------------------------
    # Learning path (Section 15 of the brief) — kept, dark-styled.
    # ------------------------------------------------------------------
    if topic:
        st.divider()
        st.markdown(f"### 🗺️ Learning path: {topic}")
        st.caption("Foundations first, then what each step makes possible.")

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
                here = ("<span class='pd-here'>YOU ARE HERE</span><br>"
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