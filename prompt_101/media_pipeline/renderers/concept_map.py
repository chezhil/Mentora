"""Concept map renderer — one idea in the middle, what hangs off it around.

The old version used networkx's spring layout, which is a physics simulation:
run it twice on the same graph and the nodes land somewhere else, boxes
overlap when the seed is unlucky, and labels are drawn wherever the springs
happened to settle. Fine for exploring a graph, wrong for a teaching frame
that has to be legible the first time and identical every time.

This places the nodes on a ring instead. Deterministic, never overlapping,
and it says the thing a concept map is for: this is the idea, and these are
the things attached to it.
"""

from __future__ import annotations

import math

import matplotlib
matplotlib.use("Agg")

from . import register, save_figure
from . import design
from .payload import enrich, parse_edges, parse_nodes

MAX_SPOKES = 8


@register("concept_map")
def render_concept_map(content: str, subject: str, data: dict) -> str:
    """Render a hub-and-spoke concept map.

    Data options:
      data["central"]   the hub label
      data["related"]   the spoke labels
      data["nodes"] / data["edges"]  or Mermaid text in `content`
    """
    data = enrich("concept_map", content, data)
    title = str(data.get("title") or content)

    central, spokes, labels = _shape(content, data)

    fig, ax, area = design.canvas(title, subject, accent_index=4)

    if not central:
        design.empty(ax, area, "No concept map for this",
                     "the teacher's payload named no related concepts")
        return save_figure(fig, "concept_map")

    _draw(ax, area, central, spokes, labels)
    return save_figure(fig, "concept_map")


def _shape(content: str, data: dict):
    """(hub, spokes, {spoke: edge label})."""
    central = str(data.get("central") or "").strip()
    spokes = [str(s).strip() for s in (data.get("related") or []) if str(s).strip()]
    labels: dict[str, str] = {}

    if not central or not spokes:
        edges = parse_edges(content)
        nodes = parse_nodes(content)
        if edges:
            # The hub is whichever node the most edges touch.
            counts: dict[str, int] = {}
            for a, b in edges:
                counts[a] = counts.get(a, 0) + 1
                counts[b] = counts.get(b, 0) + 1
            central = central or max(counts, key=lambda n: counts[n])
            spokes = spokes or [n for n in nodes if n != central]
        elif nodes:
            central = central or nodes[0]
            spokes = spokes or nodes[1:]

    if central and not spokes:
        spokes = []
    return central, list(dict.fromkeys(spokes))[:MAX_SPOKES], labels


def _draw(ax, area, central: str, spokes: list[str], labels: dict) -> None:
    left, bottom, right, top = area
    cx, cy = (left + right) / 2, (bottom + top) / 2

    hub_w, hub_h = 40.0, 17.0
    spoke_w, spoke_h = 30.0, 12.0

    # Radii chosen so a spoke box never crosses the frame edge, ellipse-shaped
    # because the canvas is 16:9 and a circle would waste the width.
    rx = min((right - left) / 2 - spoke_w / 2, 52.0)
    ry = min((top - bottom) / 2 - spoke_h / 2, 27.0)

    n = len(spokes)
    for i, spoke in enumerate(spokes):
        # Start at the right and go anticlockwise, skipping the exact top and
        # bottom when there are few spokes so nothing sits directly above the
        # hub label.
        angle = 2 * math.pi * i / max(n, 1) + (math.pi / n if n else 0)
        sx, sy = cx + rx * math.cos(angle), cy + ry * math.sin(angle)

        # Meet the hub on its edge, not its centre.
        ux, uy = math.cos(angle), math.sin(angle)
        design.connect(
            ax,
            (cx + ux * hub_w / 2 * 0.9, cy + uy * hub_h / 2 * 0.9),
            (sx - ux * spoke_w / 2 * 0.9, sy - uy * spoke_h / 2 * 0.9),
            labels.get(spoke, ""), zorder=3,
        )
        design.hard_box(ax, sx, sy, spoke_w, spoke_h,
                        design.wrap(spoke, spoke_w, 14), index=i + 1,
                        fontsize=14, zorder=6)

    # The hub last and highest, so every spoke line disappears under it.
    design.hard_box(ax, cx, cy, hub_w, hub_h,
                    design.wrap(central, hub_w, 20), index=0,
                    fontsize=20, zorder=9)
