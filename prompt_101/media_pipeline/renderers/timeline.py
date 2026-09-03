"""Timeline renderer using matplotlib.

Renders horizontal timelines filling the full canvas.
Designed for phone viewing: large text, clear markers.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .payload import enrich
from . import register, save_figure, IMAGE_WIDTH, IMAGE_HEIGHT, DPI, BG_COLOR, TITLE_COLOR, TEXT_COLOR, ACCENT_COLORS


@register("timeline")
def render_timeline(content: str, subject: str, data: dict) -> str:
    """Render a horizontal timeline filling the full 1280x720 canvas.
    
    Data options:
    - data["events"]: list of {"year": str, "label": str}
    """
    data = enrich("timeline", content, data)
    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Title at top - large
    ax.text(0.5, 0.92, (data.get("title") or content)[:50], fontsize=32, fontweight="bold",
            ha="center", va="center", color=TITLE_COLOR)

    # Divider
    ax.plot([0.05, 0.95], [0.87, 0.87], color=ACCENT_COLORS[0],
            linewidth=2, alpha=0.3, transform=ax.transAxes, clip_on=False)

    # Get events
    events = data.get("events", [
        {"year": "Start", "label": "Beginning"},
        {"year": "Middle", "label": "Key Event"},
        {"year": "End", "label": "Conclusion"},
    ])

    n = len(events)
    if n == 0:
        events = [{"year": "N/A", "label": "No events"}]
        n = 1

    # Timeline axis - thick line in the middle third
    y_line = 0.50
    ax.plot([0.06, 0.94], [y_line, y_line], color="#cccccc", linewidth=5,
            transform=ax.transAxes, zorder=1, solid_capstyle="round")

    # Place events along the timeline
    for i, event in enumerate(events):
        x = 0.06 + (0.88 * i / max(n - 1, 1))
        color = ACCENT_COLORS[i % len(ACCENT_COLORS)]

        # Large marker circle
        ax.plot(x, y_line, "o", color=color, markersize=24,
                transform=ax.transAxes, zorder=3,
                markeredgecolor="white", markeredgewidth=3)

        # Year label below - large font
        year_text = event.get("year", str(i + 1))
        ax.text(x, y_line - 0.10, year_text, fontsize=22,
                ha="center", va="top", color=color, fontweight="bold",
                transform=ax.transAxes)

        # Event label above - large font, alternating above/below for readability
        label_text = event.get("label", f"Event {i + 1}")
        y_label = y_line + 0.12

        # Wrap long labels
        if len(label_text) > 25:
            words = label_text.split()
            mid = len(words) // 2
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
            ax.text(x, y_label + 0.04, line1, fontsize=18,
                    ha="center", va="bottom", color=TEXT_COLOR,
                    transform=ax.transAxes)
            ax.text(x, y_label - 0.02, line2, fontsize=18,
                    ha="center", va="bottom", color=TEXT_COLOR,
                    transform=ax.transAxes)
        else:
            ax.text(x, y_label, label_text, fontsize=20,
                    ha="center", va="bottom", color=TEXT_COLOR,
                    transform=ax.transAxes,
                    fontweight="bold")

    # Subject tag at bottom
    if subject:
        ax.text(0.5, 0.04, subject.title(), fontsize=18,
                ha="center", va="center", color="#888888",
                transform=ax.transAxes, fontstyle="italic")

    return save_figure(fig, "timeline")
