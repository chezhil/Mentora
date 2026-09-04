"""Loads ui/style.css into the page, and sets the script direction.

You should not need to change this file. Write CSS in ui/style.css instead —
it is re-read on every rerun, so save the file and the browser updates.
"""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

CSS_PATH = Path(__file__).resolve().parent / "style.css"


def apply_theme(lang: str = "en", hide_nav: bool = False) -> None:
    """Inject ui/style.css. Silently does nothing if the file is absent.

    `hide_nav` hides Streamlit's automatic multipage navigation. There are two
    entry points in this repo — app.py, the single-page demo, and app_v2.py,
    the multipage UI in pages/ — and Streamlit discovers a pages/ directory
    from the location of whichever script is running. Both live in the repo
    root, so running app.py raised a nav to app_v2's five pages above the
    adaptation panel: a second, half-built copy of the app, one click away,
    during the demo. app.py passes hide_nav=True; app_v2.py must not, or it
    loses the navigation it is built around.
    """
    try:
        css = CSS_PATH.read_text(encoding="utf-8")
    except Exception:
        return
    if css.strip():
        st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)
    if hide_nav:
        st.markdown(
            '<style>[data-testid="stSidebarNav"]{display:none;}</style>',
            unsafe_allow_html=True,
        )
    _set_direction(lang)


def _set_direction(lang: str) -> None:
    """Mark the page right-to-left for Urdu and Arabic.

    Streamlit has no RTL mode. Its own DOM is built left-to-right and there is
    no supported hook to change that, so this reaches into the parent document
    and sets dir on the app root; ui/style.css picks it up from there.

    It has to go through st.components.v1.html, NOT st.markdown. Streamlit
    strips <script> out of markdown even with unsafe_allow_html=True, so the
    markdown version of this ran nothing at all and Urdu and Arabic have been
    rendering left-to-right the whole time. components.html is the supported
    way to get a script onto the page: it renders a real (zero-height) iframe,
    and window.parent from inside it is the app document.

    If Streamlit's internals move, the selector misses and the app renders
    left-to-right — exactly where it was before, so the failure stays cosmetic
    and cannot break a lesson.
    """
    try:
        from shared.languages import get
        rtl = get(lang).rtl
    except Exception:
        rtl = False

    direction = "rtl" if rtl else "ltr"
    components.html(
        f"""<script>
        const doc = window.parent.document;
        const root = doc.querySelector('.stApp');
        if (root) {{ root.setAttribute('dir', {direction!r}); }}
        </script>""",
        height=0,
        width=0,
    )
