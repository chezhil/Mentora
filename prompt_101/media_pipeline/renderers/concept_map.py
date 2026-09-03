"""Concept map renderer using matplotlib or networkx.

Renders concept relationship diagrams filling the full canvas.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

from . import register, save_figure, IMAGE_WIDTH, IMAGE_HEIGHT, DPI, BG_COLOR, TITLE_COLOR, ACCENT_COLORS, get_font_family


@register("concept_map")
def render_concept_map(content: str, subject: str, data: dict) -> str:
    """Render a concept map filling the full 1280x720 canvas.
    
    Data options:
    - data["central"]: central concept name
    - data["related"]: list of related concept names
    - data["nodes"], data["edges"]: for networkx graphs
    """
    if HAS_NETWORKX and "nodes" in data:
        return _render_networkx_concept_map(content, data)
    return _render_matplotlib_concept_map(content, subject, data)


def _render_matplotlib_concept_map(content: str, subject: str, data: dict) -> str:
    """Render concept map with central node and satellites filling the canvas."""
    lang = data.get("lang", "en")
    font = get_font_family(lang)

    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)

    # Title at top
    ax.text(5, 9.3, content[:50], fontsize=32, fontweight="bold",
            ha="center", va="center", color=TITLE_COLOR, fontfamily=font)

    # Central concept - large circle
    central = data.get("central", content[:25])
    center_x, center_y = 5, 5

    # Outer glow
    glow = plt.Circle((center_x, center_y), 2.0, color=ACCENT_COLORS[0],
                       alpha=0.15, transform=ax.transData)
    ax.add_patch(glow)

    # Main circle
    circle = plt.Circle((center_x, center_y), 1.5, facecolor=ACCENT_COLORS[0],
                         alpha=0.95, edgecolor="white", linewidth=4)
    ax.add_patch(circle)
    ax.text(center_x, center_y, central, fontsize=24, ha="center", va="center",
            color="white", fontweight="bold", fontfamily=font,
            wrap=True)

    # Related concepts in a circle around center
    related = data.get("related", ["Concept A", "Concept B", "Concept C", "Concept D"])
    n = len(related)
    radius = 3.8

    for i, rel in enumerate(related):
        angle = 2 * np.pi * i / n - np.pi / 2  # Start from top
        x = center_x + radius * np.cos(angle)
        y = center_y + radius * np.sin(angle)

        color = ACCENT_COLORS[(i + 1) % len(ACCENT_COLORS)]

        # Satellite circle
        sat_circle = plt.Circle((x, y), 1.0, facecolor=color, alpha=0.95,
                                edgecolor="white", linewidth=3)
        ax.add_patch(sat_circle)
        ax.text(x, y, rel, fontsize=16, ha="center", va="center",
                color="white", fontweight="bold", fontfamily=font)

        # Arrow from satellite to center
        arrow_len = 0.8
        ax.annotate("",
                    xy=(center_x + 1.5 * np.cos(angle + np.pi),
                        center_y + 1.5 * np.sin(angle + np.pi)),
                    xytext=(x - arrow_len * np.cos(angle),
                            y - arrow_len * np.sin(angle)),
                    arrowprops=dict(arrowstyle="-|>", color="#555555",
                                    lw=2.5, mutation_scale=18))

    # Subject tag
    if subject:
        ax.text(5, 0.4, subject.title(), fontsize=18,
                ha="center", va="center", color="#888888",
                fontfamily=font, fontstyle="italic")

    return save_figure(fig, "concept_map")


def _render_networkx_concept_map(content: str, data: dict) -> str:
    """Render concept map using shared networkx renderer."""
    from . import render_networkx_graph
    return render_networkx_graph(content, data, kind="concept_map")
