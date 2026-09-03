"""Presentation layer. OWNED BY THE FRONTEND TEAM.

Nothing in here changes behaviour. app.py calls ui.apply_theme() once, at the
top, and that is the only line connecting this package to the rest of the app.
Restyle freely without touching a single line of application logic.
"""

from .theme import apply_theme

__all__ = ["apply_theme"]
