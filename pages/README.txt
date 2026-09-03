Streamlit multipage directory. OWNED BY THE FRONTEND TEAM.

Any .py file dropped in here becomes a page, and Streamlit builds the nav
itself. One file per page means one owner per file and no merge conflicts.

Files are ordered by name, so prefix with a number: 1_Setup.py, 2_Lesson.py.

The entry point for the new UI is app_v2.py in the repo root, NOT app.py.
app.py is the working demo and must keep running untouched until yours is
better. Run yours with:

    .venv/bin/streamlit run app_v2.py
