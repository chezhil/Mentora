"""Learning path screen.  OWNER: Utkarsh.  Nobody else edits this file.

Section 15 of the brief. The function that produces the path already exists
and is already wired — it is simply never called, so we score nothing for it.

WHAT EXISTS ALREADY:
    orchestrator.learning_path_for(topic) -> list[str]
        An ordered path. Each entry is "Step name - one line on why it comes
        here", e.g. "Python fundamentals - you need loops before you can read
        a training script". Naman owns the content and its ordering.

WHAT YOU BUILD: the body of render_path below.

    - numbered list, in order, one row per step
    - mark the current topic if it appears in the path
    - keep it to a simple ordered list; this is a display screen, not a
      planner

DO NOT call planner/ directly. Go through orchestrator.
"""

import streamlit as st

import orchestrator as orch


def render_path(session) -> None:
    topic = session.plan.topic if session is not None else None
    if not topic:
        st.caption("Start a lesson to see where it leads.")
        return

    st.subheader(f"Where {topic} leads")
    st.info("Not built yet — Utkarsh. See the docstring at the top of this file.")
