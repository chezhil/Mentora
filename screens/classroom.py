"""The teacher's view of the class.

Mentora had exactly one kind of user: a student sitting alone. But the
adaptation data it already collects — who got what wrong, and what
misconception the teacher named for it — is far more useful to the person
running the class than to the student who lived it. A student learns their own
weak spot by being taught it again. A teacher learns that eleven of thirty
students hold the same misconception, and reteaches Monday's lesson.

So this reads across every student in mentora.db, which is a query the student
side never needed, and puts three things on one page:

    the class average, and how many have actually done the lesson
    the misconceptions more than one student holds — the reteach list
    a row per student, so nobody is invisible inside the average

Nothing here is generated. Every number is counted from reports the teaching
engine already wrote.
"""

from __future__ import annotations

from collections import Counter

import streamlit as st

from ui.i18n import t


def render_classroom(lang: str = "en") -> None:
    st.subheader(t("teacher.title", lang))
    st.caption(t("teacher.blurb", lang))

    try:
        import history
        rows = history.class_summary()
    except Exception as exc:
        st.warning(f"Could not read the class from mentora.db: {exc}")
        return

    # A student who has not named themselves is the default row, and counting
    # it as a person makes the class look bigger than it is.
    rows = [r for r in rows if r["lessons"]]
    if not rows:
        st.info(t("teacher.no_students", lang))
        return

    _headline(rows, lang)
    st.divider()
    _reteach_list(rows, lang)
    st.divider()
    _student_table(rows, lang)


def _headline(rows: list[dict], lang: str) -> None:
    scored = [r for r in rows if r["average"] > 0]
    average = sum(r["average"] for r in scored) / len(scored) if scored else 0.0
    lessons = sum(r["lessons"] for r in rows)

    left, middle, right = st.columns(3)
    left.metric(t("teacher.students", lang), len(rows))
    middle.metric(t("teacher.avg", lang), f"{average:.0f}%")
    right.metric(t("nav.lesson", lang), lessons)


def _reteach_list(rows: list[dict], lang: str) -> None:
    """Misconceptions held by more than one student, commonest first.

    Counting distinct STUDENTS, not occurrences: one student who kept making
    the same mistake five times is a conversation with that student, whereas
    five students making it once each is a lesson that needs reteaching, and
    those two must not look the same in this list.
    """
    st.markdown(f"#### {t('teacher.common_gaps', lang)}")

    weak = Counter()
    misconceptions = Counter()
    for row in rows:
        weak.update(set(row["weak"]))
        misconceptions.update(set(row["misconceptions"]))

    shared = [(name, n) for name, n in misconceptions.most_common() if n > 1]
    if shared:
        for name, count in shared[:6]:
            share = count / len(rows)
            st.warning(f"**{count} of {len(rows)} students** — {name}")
            st.progress(min(share, 1.0))
    elif weak:
        st.caption("No misconception is shared yet. Weakest concepts so far:")
        for name, count in weak.most_common(6):
            st.write(f"• {name} — {count} student{'s' if count > 1 else ''}")
    else:
        st.caption("Nothing to reteach — nobody has got anything wrong yet.")


def _student_table(rows: list[dict], lang: str) -> None:
    st.markdown(f"#### {t('teacher.students', lang)}")
    for row in rows:
        score = row["average"]
        # Bands, not a colour ramp: a teacher scanning thirty rows needs to
        # see who to sit with, not a precise shade.
        mark = "🟥" if score < 50 else "🟨" if score < 75 else "🟩"
        header = f"{mark}  **{row['student_id']}** — {score:.0f}%  ·  {row['lessons']} lesson(s)"
        with st.expander(header):
            if row["weak"]:
                st.write("**" + t("report.weak", lang) + "**")
                for item in row["weak"][:5]:
                    st.write(f"• {item}")
            if row["misconceptions"]:
                st.write("**" + t("panel.misconception", lang) + "**")
                for item in row["misconceptions"][:4]:
                    st.caption(item)
            if row["next_topic"]:
                st.write(f"**{t('report.next', lang)}:** {row['next_topic']}")
