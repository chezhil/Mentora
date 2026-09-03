"""New UI entry point. OWNED BY THE FRONTEND TEAM.

Run it with:

    .venv/bin/streamlit run app_v2.py

app.py is the current working demo and stays untouched until this is better,
so the team always has something to show. Nothing here imports from app.py.

Pages live in pages/. Anything you put there joins the nav automatically.

The ONLY backend you call is `orchestrator`. Its full API is in
WORKSPLIT_FRONTEND.txt. Do not import teacher/, planner/, ingest/,
prompt_101/ or wiring directly — orchestrator wraps all of them and handles
the failure cases.
"""

import streamlit as st

import ui

st.set_page_config(page_title="Mentora", page_icon="🎓", layout="wide")
ui.apply_theme()

# --- state shared across pages ---------------------------------------------
# st.session_state is the ONLY thing that survives a rerun or a page switch.
# Set these once here so every page can rely on them existing.
st.session_state.setdefault("session", None)     # SessionState | None
st.session_state.setdefault("segment", None)     # TeachingSegment | None
st.session_state.setdefault("report", None)      # LessonReport | None
st.session_state.setdefault("student_id", "student")

st.title("Mentora")
st.caption("AI Teacher — pick a page from the sidebar to begin.")

st.info(
    "This is the new UI, still being built. The working demo is app.py.\n\n"
    "Add pages in pages/ — see WORKSPLIT_FRONTEND.txt for the backend API."
)
