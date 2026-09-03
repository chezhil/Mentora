"""One screen per file.

app.py imports these and calls them. It does NOT contain their bodies, so two
people can build two screens at the same time without touching the same file.

Every screen is display-only: it renders data the orchestrator already has and
never mutates st.session_state. That keeps it clear of Streamlit's rerun
model, which is the one trap that eats a day.
"""
