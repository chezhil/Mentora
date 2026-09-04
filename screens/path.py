"""Learning path screen. OWNER: Utkarsh. Nobody else edits this file.

Section 15 of the brief: AI-Generated Learning Path.
Renders an ordered curriculum path for the student.
"""

from html import escape

import streamlit as st

import orchestrator as orch
from ui.i18n import t


def render_path(session, lang: str = "en") -> None:
    topic = session.plan.topic if session is not None else None
    if not topic:
        st.info(t("path.locked", lang))
        return

    st.subheader(f"{t('path.title', lang)}: {topic}")
    st.caption("Foundations first, then what each step makes possible.")

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

        # These strings come straight from the model and go into a markdown
        # block with unsafe_allow_html=True. A step named "C++ <template>
        # basics" silently swallowed everything after the "<", and anything
        # angle-bracketed could restyle or break the page. Escape after the
        # comparison above, so matching still sees the real text.
        title, desc = escape(title), escape(desc)

        with st.container():
            # Colours match ui/style.css: yellow marks where the student is,
            # white for everything else, black keyline and hard shadow on both.
            fill = "#FFD400" if is_current else "#FFFFFF"
            here = ("<span style=\"background:#12100E;color:#F5F1E8;"
                    "font-weight:800;padding:2px 8px;font-size:.7rem;"
                    "letter-spacing:.08em;\">YOU ARE HERE</span><br>"
                    if is_current else "")
            st.markdown(
                f"""
                <div style="background:{fill};border:3px solid #12100E;
                            box-shadow:5px 5px 0 #12100E;padding:12px 16px;
                            margin-bottom:16px;">
                    {here}
                    <h4 style="margin:4px 0 2px 0;color:#12100E;
                               text-transform:uppercase;letter-spacing:-0.02em;">
                        {idx}. {title}</h4>
                    <p style="margin:0;color:#12100E;font-size:0.95rem;">{desc}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
