"""Diagram renderer using matplotlib shapes and networkx.

Renders labeled diagrams filling the full canvas.
Supports both simple box-and-arrow diagrams and networkx graphs.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

from . import register, save_figure, IMAGE_WIDTH, IMAGE_HEIGHT, DPI, BG_COLOR, TITLE_COLOR, TEXT_COLOR, ACCENT_COLORS


@register("diagram")
def render_diagram(content: str, subject: str, data: dict) -> str:
    """Render a diagram filling the full 1280x720 canvas.
    
    Data options:
    - data["nodes"], data["edges"]: for networkx graphs
    - data["boxes"]: list of {"x", "y", "label", "color"} for matplotlib diagrams
    """
    if HAS_NETWORKX and "nodes" in data:
        return _render_networkx_diagram(content, data)
    return _render_matplotlib_diagram(content, subject, data)


def _render_matplotlib_diagram(content: str, subject: str, data: dict) -> str:
    """Render diagram with boxes and arrows filling the full canvas."""
    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)

    # Title at top - large font
    ax.text(5, 9.3, content[:50], fontsize=32, fontweight="bold",
            ha="center", va="center", color=TITLE_COLOR, fontfamily="sans-serif")

    # Divider
    ax.axhline(y=8.8, xmin=0.1, xmax=0.9, color=ACCENT_COLORS[0],
               linewidth=2, alpha=0.3)

    # Get boxes from data or generate defaults
    boxes = data.get("boxes", None)
    if not boxes:
        boxes = _generate_default_boxes(content, subject)

    # Draw boxes
    for box in boxes:
        x, y = box["x"], box["y"]
        w, h = box.get("w", 2.2), box.get("h", 1.2)
        color = box.get("color", ACCENT_COLORS[0])
        label = box.get("label", "")

        rect = FancyBboxPatch((x - w/2, y - h/2), w, h,
                              boxstyle="round,pad=0.15",
                              facecolor=color, edgecolor="white",
                              linewidth=3, alpha=0.92)
        ax.add_patch(rect)
        ax.text(x, y, label, fontsize=20, ha="center", va="center",
                color="white", fontweight="bold", fontfamily="sans-serif")

    # Draw arrows between consecutive boxes
    for i in range(len(boxes) - 1):
        x1, y1 = boxes[i]["x"], boxes[i]["y"]
        x2, y2 = boxes[i+1]["x"], boxes[i+1]["y"]
        w1 = boxes[i].get("w", 2.2) / 2
        w2 = boxes[i+1].get("w", 2.2) / 2

        ax.annotate("",
                    xy=(x2 - w2 - 0.1, y2),
                    xytext=(x1 + w1 + 0.1, y1),
                    arrowprops=dict(arrowstyle="-|>", color="#555555",
                                    lw=3, mutation_scale=20))

    # Subject tag at bottom
    if subject:
        ax.text(5, 0.4, subject.title(), fontsize=18,
                ha="center", va="center", color="#888888",
                fontfamily="sans-serif", fontstyle="italic")

    return save_figure(fig, "diagram")


def _generate_default_boxes(content: str, subject: str) -> list:
    """Generate default boxes based on content and subject."""
    colors = ACCENT_COLORS

    if "physics" in subject.lower():
        return [
            {"x": 2, "y": 5, "label": "Voltage", "color": colors[0]},
            {"x": 5, "y": 5, "label": "Current", "color": colors[1]},
            {"x": 8, "y": 5, "label": "Resistance", "color": colors[2]},
        ]
    elif "biology" in subject.lower():
        return [
            {"x": 2, "y": 6.5, "label": "Cell Membrane", "color": colors[0]},
            {"x": 5, "y": 6.5, "label": "Nucleus", "color": colors[1]},
            {"x": 8, "y": 6.5, "label": "Mitochondria", "color": colors[2]},
            {"x": 5, "y": 3.5, "label": "Cytoplasm", "color": colors[3]},
        ]
    else:
        return [
            {"x": 2, "y": 5, "label": "Input", "color": colors[0]},
            {"x": 5, "y": 5, "label": "Process", "color": colors[1]},
            {"x": 8, "y": 5, "label": "Output", "color": colors[2]},
        ]


def _render_networkx_diagram(content: str, data: dict) -> str:
    """Render a network diagram using shared networkx renderer."""
    from . import render_networkx_graph
    return render_networkx_graph(content, data, kind="diagram")
