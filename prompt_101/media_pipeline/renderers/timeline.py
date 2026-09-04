"""Timeline renderer — dated events along a spine, in the house style.

Events alternate above and below the spine. That is not decoration: at four
or more events on a 1280-wide frame, labels all on one side collide, and the
old renderer's answer was to split a long label across two lines at the
halfway word, which put "Faraday discovers" above "induction" with a gap
between them and no way to tell which event either belonged to.

Like every other renderer, this one draws nothing rather than inventing
content: the placeholder "Start / Middle / End" timeline is gone.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

from . import register, save_figure
from . import design
from .payload import enrich

MAX_EVENTS = 7


@register("timeline")
def render_timeline(content: str, subject: str, data: dict) -> str:
    """Render a horizontal timeline.

    Data options:
      data["events"]: list of {"year": str, "label": str}
    """
    data = enrich("timeline", content, data)
    title = str(data.get("title") or content)

    events = [e for e in (data.get("events") or []) if isinstance(e, dict)]
    events = events[:MAX_EVENTS]

    fig, ax, area = design.canvas(title, subject, accent_index=2)
    left, bottom, right, top = area

    if not events:
        design.empty(ax, area, "No timeline for this",
                     "the teacher's payload listed no dated events")
        return save_figure(fig, "timeline")

    spine_y = (top + bottom) / 2
    x0, x1 = left + 6, right - 6

    # The spine, with a black keyline so it holds up at video bitrates.
    ax.plot([x0, x1], [spine_y, spine_y], color=design.INK, linewidth=5,
            solid_capstyle="butt", zorder=2)

    n = len(events)
    card_w = min(30.0, (x1 - x0) / max(n - 0.4, 1))
    card_h = 12.0

    for i, event in enumerate(events):
        x = x0 if n == 1 else x0 + (x1 - x0) * i / (n - 1)
        above = i % 2 == 0
        fill, _ = design.accent(i)

        # Marker on the spine.
        ax.plot(x, spine_y, "o", markersize=17, color=fill,
                markeredgecolor=design.INK, markeredgewidth=2.6, zorder=6)

        # Year, hard against the spine on the side the card is not.
        ax.text(x, spine_y + (-4.5 if above else 4.5),
                str(event.get("year", i + 1)),
                fontsize=19, fontweight="bold", color=design.INK,
                ha="center", va="center", zorder=6)

        # Label card, on a leader line so it is unambiguous which mark it
        # belongs to.
        card_y = spine_y + (14.0 if above else -14.0)
        # Keep the card inside the frame even when its mark sits at the very
        # first or very last position — otherwise the opening and closing
        # events, the two a viewer looks at first, are the two that clip.
        card_x = min(max(x, left + card_w / 2), right - card_w / 2)
        ax.plot([x, card_x], [spine_y, card_y + (-card_h / 2 if above else card_h / 2)],
                color=design.INK, linewidth=2.0, zorder=3)
        design.hard_box(ax, card_x, card_y, card_w, card_h,
                        design.wrap(str(event.get("label", "")), card_w, 14),
                        index=i, fontsize=14)

    return save_figure(fig, "timeline")
