"""Learning path screen. OWNER: Utkarsh. Nobody else edits this file.

Section 15 of the brief: AI-Generated Learning Path.
Renders an ordered curriculum path for the student.
"""

import streamlit as st
import orchestrator as orch


def render_path(session) -> None:
    topic = session.plan.topic if session is not None else None
    if not topic:
        st.info("💡 Start a lesson to view the personalized learning path.")
        return

    st.subheader(f"🗺️ Learning Path: Where '{topic}' Leads")
    st.caption("A structured step-by-step roadmap tailored to build deep subject mastery.")

    steps = orch.learning_path_for(topic)
    if not steps:
        st.info("No learning path steps available for this topic yet.")
        return

    for idx, step_item in enumerate(steps, start=1):
        # Parse step title and explanation if formatted as "Title - Description"
        if " - " in step_item:
            title, desc = step_item.split(" - ", 1)
        elif ": " in step_item:
            title, desc = step_item.split(": ", 1)
        else:
            title, desc = step_item, ""

        # Highlight if it matches or is part of current topic
        is_current = (topic.lower() in title.lower() or title.lower() in topic.lower())
        
        with st.container():
            if is_current:
                st.markdown(
                    f"""
                    <div style="background-color: #0c4a6e; border-left: 5px solid #38bdf8; padding: 12px 16px; border-radius: 6px; margin-bottom: 12px;">
                        <span style="background-color: #38bdf8; color: #082f49; font-weight: bold; padding: 2px 8px; border-radius: 12px; font-size: 0.85rem;">ACTIVE LESSON</span>
                        <h4 style="margin: 6px 0 2px 0; color: #f0f9ff;">Step {idx}: {title}</h4>
                        <p style="margin: 0; color: #bae6fd; font-size: 0.95rem;">{desc}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"""
                    <div style="background-color: #1e293b; border-left: 4px solid #64748b; padding: 10px 14px; border-radius: 6px; margin-bottom: 10px;">
                        <h4 style="margin: 0 0 2px 0; color: #f8fafc;">Step {idx}: {title}</h4>
                        <p style="margin: 0; color: #94a3b8; font-size: 0.92rem;">{desc}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
