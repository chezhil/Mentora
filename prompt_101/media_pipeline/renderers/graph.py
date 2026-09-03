"""Graph/plot renderer using matplotlib.

Renders function plots and data graphs filling the full canvas.
Designed for phone viewing: large axis labels, thick lines.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import re

import numpy as np

from .payload import enrich
from . import register, save_figure, IMAGE_WIDTH, IMAGE_HEIGHT, DPI, BG_COLOR, TITLE_COLOR, ACCENT_COLORS


@register("graph")
def render_graph(content: str, subject: str, data: dict) -> str:
    """Render a plot/graph filling the full 1280x720 canvas.
    
    Data options:
    - data["function"]: string like "np.sin(x)" to plot
    - data["x_values"], data["y_values"]: lists of data points
    - data["x_min"], data["x_max"]: range for function plots
    - data["title"]: custom title
    - data["x_label"], data["y_label"]: axis labels
    """
    data = enrich("graph", content, data)
    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    ax.set_facecolor(BG_COLOR)
    fig.patch.set_facecolor(BG_COLOR)

    # Large fonts for phone viewing
    title_size = 28
    label_size = 22
    tick_size = 16

    plotted = False

    # Plot data points if provided
    if "x_values" in data and "y_values" in data:
        x = np.array(data["x_values"])
        y = np.array(data["y_values"])
        ax.plot(x, y, "o-", color=ACCENT_COLORS[0], linewidth=3, markersize=10,
                markerfacecolor="white", markeredgecolor=ACCENT_COLORS[0], markeredgewidth=2)
        plotted = True

    # Plot function if provided
    elif "function" in data:
        func_str = data["function"]
        # Physical quantities a student meets here — resistance, current,
        # time, concentration — are positive. Plotting -10..10 wasted half the
        # canvas and put a singularity dead centre, which flattened the part
        # of the curve the lesson is actually about.
        x_min = data.get("x_min", 0.1)
        x_max = data.get("x_max", 10)
        x = np.linspace(x_min, x_max, 600)
        try:
            safe_ns = {
                "x": x, "np": np,
                "sin": np.sin, "cos": np.cos, "tan": np.tan,
                "exp": np.exp, "log": np.log, "sqrt": np.sqrt,
                "pi": np.pi, "abs": np.abs,
            }
            with np.errstate(divide="ignore", invalid="ignore"):
                y = np.asarray(eval(func_str, {"__builtins__": {}}, safe_ns),
                               dtype=float)

            finite = np.isfinite(y)
            x, y = x[finite], y[finite]

            ax.plot(x, y, color=ACCENT_COLORS[0], linewidth=3.5,
                    solid_capstyle="round", zorder=3)
            # A soft fill makes the trend legible at a glance on a video frame.
            ax.fill_between(x, y, y.min(), color=ACCENT_COLORS[0], alpha=0.10,
                            zorder=2)

            # An asymptote can span orders of magnitude. Clip to the bulk of
            # the data so the teaching region is visible instead of a spike.
            lo, hi = np.percentile(y, [1, 97])
            pad = (hi - lo) * 0.12 or 1.0
            ax.set_ylim(max(lo - pad, y.min() - pad), hi + pad)
            ax.set_xlim(x.min(), x.max())
            plotted = True
        except Exception as e:
            ax.text(0.5, 0.5, f"Cannot plot: {func_str}\n{e}",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=24, color="#e74c3c")

    # Nothing plottable. Say so — do NOT draw an unrelated curve under a title
    # naming a different function. A sine wave labelled "y = 1/x" reads as the
    # system inventing content, which is worse than showing no graph at all.
    if not plotted:
        ax.axis("off")
        ax.text(0.5, 0.62, content[:70], transform=ax.transAxes, ha="center",
                va="center", fontsize=title_size, fontweight="bold",
                color=TITLE_COLOR, wrap=True)
        ax.text(0.5, 0.38, "no plottable expression in this payload",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=tick_size, color="#999999")

    # Style: large grid, thick spines
    ax.grid(True, alpha=0.25, linewidth=1.0, linestyle="--", color="#9aa0aa")
    ax.set_axisbelow(True)
    # A full box round a teaching plot is noise. Keep the two axes that carry
    # meaning and drop the rest.
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_linewidth(1.6)
        ax.spines[side].set_color("#8b909a")
    ax.tick_params(axis="both", which="major", labelsize=tick_size, width=2, length=6)

    # Large axis labels
    # "X" and "Y" tell a student nothing. The caption is usually "<y> vs <x>",
    # so use it when nothing better was supplied.
    x_label, y_label = data.get("x_label"), data.get("y_label")
    if not (x_label and y_label):
        caption = str(data.get("title") or content)
        parts = re.split(r"\s+vs\.?\s+|\s+against\s+", caption, maxsplit=1,
                         flags=re.I)
        if len(parts) == 2:
            y_label = y_label or parts[0].strip().capitalize()
            x_label = x_label or parts[1].strip().capitalize()
    ax.set_xlabel(x_label or "", fontsize=label_size, fontweight="bold", labelpad=10)
    ax.set_ylabel(y_label or "", fontsize=label_size, fontweight="bold", labelpad=10)

    # Title
    title = data.get("title", content[:50])
    ax.set_title(title, fontsize=title_size, fontweight="bold", color=TITLE_COLOR, pad=20)

    # Add padding so content doesn't touch edges
    plt.subplots_adjust(left=0.08, right=0.95, top=0.90, bottom=0.10)

    return save_figure(fig, "graph")
