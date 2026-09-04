"""Screen 4 — Report.

Extracted from app.py.
"""

import os

import streamlit as st

import orchestrator as orch
from screens._state import _t


def screen_report() -> None:
    report = st.session_state.report
    if report is None:
        st.caption(_t("report.locked"))
        return

    st.metric(_t("report.score"), f"{report.score:.0f}%")

    video = orch.lesson_video(st.session_state.session)
    if video and os.path.exists(video):
        st.subheader(_t("report.your_lesson"))
        st.video(video)

    left, right = st.columns(2)
    with left:
        st.subheader(_t("report.strong"))
        for item in report.strong or ["—"]:
            st.write(f"✅ {item}")
    with right:
        st.subheader(_t("report.weak"))
        for item in report.weak or ["—"]:
            st.write(f"🔁 {item}")

    if report.misconceptions:
        st.subheader(_t("report.misconceptions"))
        for item in dict.fromkeys(report.misconceptions):
            st.warning(item)

    st.subheader(_t("report.revise"))
    for item in report.revise or ["—"]:
        st.write(f"• {item}")

    st.subheader(_t("report.next"))
    st.success(report.next_topic)

    if st.button(_t("report.again")):
        for key in ("phase", "session", "segment", "report", "last_feedback",
                    "busy", "done_tokens", "last_followup", "lang_note",
                    "quiz_report"):
            st.session_state.pop(key, None)
        from app import init_state
        init_state()
        st.rerun()
