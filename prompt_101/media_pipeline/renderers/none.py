"""Title card — what goes on screen when a segment needs no diagram.

Also the safety net: visual.render() falls back here when a renderer raises,
so this function must never fail.

The old version drew a coolwarm gradient and a translucent circle behind the
text. That is decoration standing in for content — it made a segment with no
visual look like a segment whose visual had failed. A title card should look
like a deliberate title card: the concept, set large, and the sentence that
matters, and nothing else.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

from . import register, save_figure
from . import design


@register("none")
def render_none(content: str, subject: str, data: dict) -> str:
    """Render a title card. Always succeeds."""
    title = str(data.get("title") or "").strip()
    body = " ".join(str(content or "").split())

    fig, ax, area = design.canvas("", subject, accent_index=0)
    left, bottom, right, top = area
    cx = (left + right) / 2

    # A colour band down the left edge, so the card belongs to the same family
    # as the diagrams without pretending to be one.
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((0, 0), 6.0, design.H, facecolor=design.ACCENTS[0],
                           edgecolor="none", zorder=1))
    ax.plot([6.0, 6.0], [0, design.H], color=design.INK,
            linewidth=design.BORDER + 1, zorder=2, clip_on=False)

    heading = title or (body[:48] if body else "This part is spoken")
    ax.text(cx + 3, (top + bottom) / 2 + (7 if title and body else 0),
            design.wrap(heading, 120, 40), fontsize=40, fontweight="bold",
            color=design.INK, ha="center", va="center", linespacing=1.2)

    if title and body:
        ax.text(cx + 3, (top + bottom) / 2 - 12,
                design.wrap(design._shorten(body, 150), 130, 19),
                fontsize=19, color=design.MUTED, ha="center", va="center",
                linespacing=1.35)

    return save_figure(fig, "placeholder")
