"""The house style for every visual Mentora draws.

WHY THIS EXISTS

Each renderer used to pick its own colours, its own title size and its own
margins, so a lesson that moved from a diagram to a graph to a code listing
looked like three different products spliced together. On a recorded demo that
reads as unfinished more than anything else does.

So: one palette, one grid, one title bar, drawn from here. A renderer says
what it wants to show; this file decides what it looks like.

THE STYLE IS DELIBERATE. Flat colour, a heavy black keyline on everything, a
hard offset shadow with no blur, and type set large and bold. It matches the
app's interface, and it is chosen for the medium: these frames are watched at
video bitrates, often small, often on a phone. Soft gradients and hairlines
turn to mud there. Thick black edges survive.

Everything here is millimetre-honest about size: the canvas is a fixed
1280x720 in axis units of 0-160 by 0-90, so 1 unit is 8 pixels and a box of
height 10 is 80px tall. Guessing in fractions of a figure is how the old
renderers ended up with labels hanging off the edge.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

# ── Canvas ──────────────────────────────────────────────────────────────────
# 160 x 90 axis units at 8 px per unit = 1280 x 720.
W, H = 160.0, 90.0
UNIT = 8

# ── Palette ─────────────────────────────────────────────────────────────────
INK = "#12100E"          # near-black; every keyline and every body word
PAPER = "#F5F1E8"        # warm off-white, easier on video than pure white
MUTED = "#6B6560"

# Five accents, in the order boxes take them. Chosen to stay distinguishable
# in greyscale as well as colour, because a projector will not be kind.
ACCENTS = [
    "#FFD400",   # yellow
    "#4A7DFF",   # blue
    "#FF5A36",   # orange-red
    "#00B37E",   # green
    "#B47AFF",   # violet
]

# Text on each accent. Yellow needs black; the rest carry white.
ON_ACCENT = ["#12100E", "#FFFFFF", "#FFFFFF", "#FFFFFF", "#12100E"]

BORDER = 2.6             # keyline width in points
SHADOW = 0.9             # hard shadow offset, in axis units


def accent(i: int) -> tuple[str, str]:
    """(fill, text colour) for slot i, wrapping round the palette."""
    return ACCENTS[i % len(ACCENTS)], ON_ACCENT[i % len(ON_ACCENT)]


# ── Canvas construction ─────────────────────────────────────────────────────

TITLE_H = 14.0           # height of the title bar, in axis units
FOOT_H = 6.0             # footer strip


def canvas(title: str = "", subject: str = "", accent_index: int = 0):
    """A figure with the title bar drawn, and the content box to draw inside.

    Returns (fig, ax, area) where area is (left, bottom, right, top) in axis
    units — the rectangle a renderer may use without colliding with the title
    or the footer.
    """
    fig, ax = plt.subplots(1, 1, figsize=(W * UNIT / 100, H * UNIT / 100), dpi=100)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    top = H
    if title:
        fill, _ = accent(accent_index)
        # A solid colour band across the top. It anchors the frame and gives
        # the eye somewhere to start, which matters when the visual changes
        # every thirty seconds.
        ax.add_patch(Rectangle((0, H - TITLE_H), W, TITLE_H,
                               facecolor=fill, edgecolor="none", zorder=1))
        ax.plot([0, W], [H - TITLE_H, H - TITLE_H], color=INK,
                linewidth=BORDER + 1, zorder=3, clip_on=False)
        ax.text(4.5, H - TITLE_H / 2, _shorten(title, 46),
                fontsize=30, fontweight="bold", color=INK,
                ha="left", va="center", zorder=4)
        top = H - TITLE_H

    bottom = 0.0
    if subject:
        ax.text(W - 4.5, 3.2, subject.upper(), fontsize=15, fontweight="bold",
                color=MUTED, ha="right", va="center", zorder=4)
        bottom = FOOT_H

    return fig, ax, (5.0, bottom + 2.0, W - 5.0, top - 3.0)


def _shorten(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ── Primitives ──────────────────────────────────────────────────────────────

def hard_box(ax, cx: float, cy: float, w: float, h: float, label: str,
             index: int = 0, fontsize: float = 16.0, zorder: float = 5.0):
    """A filled box with a black keyline and a hard offset shadow."""
    fill, text_colour = accent(index)
    x, y = cx - w / 2, cy - h / 2

    # The shadow is a second rectangle, offset, with no blur. That is the whole
    # trick — it reads as depth at any bitrate, where a soft drop shadow just
    # becomes a grey smear.
    ax.add_patch(Rectangle((x + SHADOW, y - SHADOW), w, h,
                           facecolor=INK, edgecolor="none", zorder=zorder))
    ax.add_patch(Rectangle((x, y), w, h, facecolor=fill, edgecolor=INK,
                           linewidth=BORDER, zorder=zorder + 1))
    ax.text(cx, cy, label, fontsize=fontsize, fontweight="bold",
            color=text_colour, ha="center", va="center",
            zorder=zorder + 2, linespacing=1.15)


def connect(ax, start: tuple[float, float], end: tuple[float, float],
            label: str = "", curve: float = 0.0, zorder: float = 4.0):
    """A thick arrow between two points, optionally labelled at its midpoint."""
    ax.add_patch(FancyArrowPatch(
        start, end,
        connectionstyle=f"arc3,rad={curve}",
        arrowstyle="-|>", mutation_scale=26,
        linewidth=2.6, color=INK, shrinkA=2, shrinkB=2, zorder=zorder,
    ))
    if label:
        mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        # Nudge off the line, in the direction the curve bows.
        my += 2.2 + curve * 12
        ax.text(mx, my, _shorten(label, 22), fontsize=12, fontweight="bold",
                color=INK, ha="center", va="center", zorder=zorder + 1,
                bbox=dict(boxstyle="square,pad=0.25", facecolor=PAPER,
                          edgecolor=INK, linewidth=1.4))


def wrap(label: str, width_units: float, fontsize: float) -> str:
    """Break a label so it fits a box `width_units` wide.

    Bold sans at fontsize f is roughly f * 0.62 points per character, and one
    axis unit is 8px = 6pt. So characters-per-line follows from the geometry
    rather than from a guess, which is what kept overflowing before.
    """
    import textwrap

    chars_per_line = max(6, int(width_units * 6.0 / (fontsize * 0.62)))
    words = str(label).split()
    if not words:
        return ""
    return "\n".join(textwrap.wrap(" ".join(words), chars_per_line)[:3])


def note(ax, text: str, x: float, y: float, fontsize: float = 14.0):
    """A small boxed caption, for anything that needs saying in words."""
    ax.text(x, y, _shorten(text, 80), fontsize=fontsize, color=INK,
            ha="center", va="center", zorder=8,
            bbox=dict(boxstyle="square,pad=0.5", facecolor=PAPER,
                      edgecolor=INK, linewidth=BORDER))


def empty(ax, area, headline: str, reason: str) -> None:
    """Say plainly that there was nothing to draw.

    Never invent a picture to fill the frame. A diagram of made-up boxes under
    a real concept name is the system lying to a student, and it is the single
    worst thing a teaching visual can do.
    """
    left, bottom, right, top = area
    cx, cy = (left + right) / 2, (bottom + top) / 2
    ax.text(cx, cy + 4, _shorten(headline, 40), fontsize=30, fontweight="bold",
            color=INK, ha="center", va="center")
    ax.text(cx, cy - 6, reason, fontsize=16, color=MUTED,
            ha="center", va="center")
