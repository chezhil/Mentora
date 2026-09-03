"""Loads ui/style.css into the page.

You should not need to change this file. Write CSS in ui/style.css instead —
it is re-read on every rerun, so save the file and the browser updates.
"""

from pathlib import Path

import streamlit as st

CSS_PATH = Path(__file__).resolve().parent / "style.css"


def apply_theme() -> None:
    """Inject ui/style.css. Silently does nothing if the file is absent."""
    try:
        css = CSS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    except Exception:
        return
    if css.strip():
        st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)
