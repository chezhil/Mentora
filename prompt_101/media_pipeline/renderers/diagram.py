"""Diagram renderer — labelled boxes and the arrows between them.

WHAT WAS WRONG BEFORE

The old renderer could draw exactly one shape: a left-to-right row of up to
six pills, with an arrow from each to the next. Anything the teacher actually
described — a branch, a loop, a thing with two inputs — was flattened into
that row, so the arrows said something the lesson did not.

And when it could not parse the payload at all it drew a hardcoded default:
"Voltage → Current → Resistance" for any physics concept, "Input → Process →
Output" for everything else. Content-free art, drawn under a real concept
name, indistinguishable at a glance from a real diagram. That is deleted. If
there is nothing to draw, the frame says so.

WHAT IT DOES NOW

Ranks the nodes by how far they sit from a source, lays each rank out as a
column, and routes the arrows between columns — the standard layered graph
drawing, which handles branches, merges and diamonds as naturally as it
handles a straight chain. Above six ranks it switches to rows, because a
seven-column diagram is unreadable at 1280 wide whatever you do to it.
"""

from __future__ import annotations

from collections import defaultdict

import matplotlib
matplotlib.use("Agg")

from . import register, save_figure
from . import design
from .payload import enrich, parse_edges, parse_nodes

MAX_NODES = 12


@register("diagram")
def render_diagram(content: str, subject: str, data: dict) -> str:
    """Render a diagram of the concept's structure.

    Reads, in order of preference:
      data["edges"]  explicit [(from, to)] or [{"from","to","label"}]
      data["nodes"]  explicit node labels
      content        Mermaid-ish text, parsed by payload.py
    """
    data = enrich("diagram", content, data)
    title = str(data.get("title") or content)

    nodes, edges = _graph_from(content, data)

    fig, ax, area = design.canvas(title, subject, accent_index=1)

    if not nodes:
        design.empty(ax, area, "No diagram for this",
                     "the teacher's payload described no parts to draw")
        return save_figure(fig, "diagram")

    ranks = _rank(nodes, edges)
    _draw(ax, area, nodes, edges, ranks)
    return save_figure(fig, "diagram")


# ---------------------------------------------------------------------------
# Reading the payload
# ---------------------------------------------------------------------------

def _graph_from(content: str, data: dict) -> tuple[list[str], list[tuple]]:
    """(nodes, edges) as label strings. Edges are (from, to, label)."""
    edges: list[tuple[str, str, str]] = []

    for raw in data.get("edges") or []:
        if isinstance(raw, dict):
            a, b = str(raw.get("from", "")), str(raw.get("to", ""))
            edges.append((a, b, str(raw.get("label", ""))))
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            edges.append((str(raw[0]), str(raw[1]),
                          str(raw[2]) if len(raw) > 2 else ""))

    if not edges:
        edges = [(a, b, "") for a, b in parse_edges(content)]

    nodes: list[str] = []
    for raw in data.get("nodes") or []:
        label = str(raw.get("label", raw.get("id", ""))) if isinstance(raw, dict) else str(raw)
        if label:
            nodes.append(label)
    for box in data.get("boxes") or []:
        label = str(box.get("label", ""))
        if label:
            nodes.append(label)
    if not nodes:
        nodes = parse_nodes(content)

    # Every endpoint of an edge has to exist as a node.
    for a, b, _ in edges:
        nodes.extend([a, b])

    nodes = [n for n in dict.fromkeys(n.strip() for n in nodes) if n][:MAX_NODES]
    keep = set(nodes)
    edges = [e for e in dict.fromkeys(edges) if e[0] in keep and e[1] in keep
             and e[0] != e[1]]
    return nodes, edges


def _rank(nodes: list[str], edges: list[tuple]) -> dict[str, int]:
    """Longest path from a source, which is the node's column.

    Cycles are tolerated: an edge that would push a node past the number of
    nodes is simply not followed, so a loop settles rather than spinning.
    """
    incoming = defaultdict(list)
    for a, b, _ in edges:
        incoming[b].append(a)

    rank = {n: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for node in nodes:
            for parent in incoming[node]:
                if rank[parent] + 1 > rank[node]:
                    rank[node] = rank[parent] + 1
                    changed = True
        if not changed:
            break
    return rank


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw(ax, area, nodes, edges, ranks) -> None:
    left, bottom, right, top = area
    by_rank: dict[int, list[str]] = defaultdict(list)
    for node in nodes:
        by_rank[ranks[node]].append(node)
    columns = [by_rank[r] for r in sorted(by_rank)]

    if _is_chain(columns) and len(columns) > 5:
        centres, box_w, box_h, fontsize = _serpentine(area, columns)
    else:
        centres, box_w, box_h, fontsize = _columns(area, columns)

    # Arrows first, so the boxes sit on top of the arrowheads rather than the
    # other way round.
    for a, b, label in edges:
        start, end, curve = _route(centres[a], centres[b], box_w, box_h,
                                   skipped=abs(ranks[b] - ranks[a]) > 1)
        design.connect(ax, start, end, label, curve=curve)

    for i, node in enumerate(nodes):
        cx, cy = centres[node]
        design.hard_box(ax, cx, cy, box_w, box_h,
                        design.wrap(node, box_w, fontsize),
                        index=i, fontsize=fontsize)


def _is_chain(columns: list[list[str]]) -> bool:
    return all(len(c) == 1 for c in columns)


def _route(a: tuple[float, float], b: tuple[float, float],
           box_w: float, box_h: float, skipped: bool):
    """Leave one box and enter the next from whichever side faces it."""
    (ax1, ay1), (ax2, ay2) = a, b
    dx, dy = ax2 - ax1, ay2 - ay1

    if abs(dx) * box_h > abs(dy) * box_w:            # mostly horizontal
        sign = 1 if dx > 0 else -1
        start = (ax1 + sign * box_w / 2, ay1)
        end = (ax2 - sign * box_w / 2, ay2)
    else:                                            # mostly vertical
        sign = 1 if dy > 0 else -1
        start = (ax1, ay1 + sign * box_h / 2)
        end = (ax2, ay2 - sign * box_h / 2)
    # Bow anything that skips a rank, so it clears the boxes it flies over.
    return start, end, 0.22 if skipped else 0.0


def _columns(area, columns):
    """Ranks as columns, each column centred on the vertical midline.

    Centring matters: spreading a two-node column across the full height put
    the two boxes at the very top and the very bottom of the frame with a
    third of the canvas empty between them, which read as a layout bug.
    """
    left, bottom, right, top = area
    span_x, span_y = right - left, top - bottom
    mid_y = (top + bottom) / 2
    n_cols = len(columns)
    tallest = max(len(c) for c in columns)

    gap_x, gap_y = 9.0, 4.5
    box_w = min(36.0, (span_x - gap_x * (n_cols - 1)) / n_cols)
    box_h = min(19.0, (span_y - gap_y * (tallest - 1)) / tallest)
    fontsize = 17 if box_w >= 26 else (15 if box_w >= 21 else 13)

    pitch_x = box_w + gap_x
    pitch_y = box_h + gap_y
    first_x = (left + right) / 2 - pitch_x * (n_cols - 1) / 2

    centres = {}
    for ci, column in enumerate(columns):
        cx = first_x + ci * pitch_x
        first_y = mid_y + pitch_y * (len(column) - 1) / 2
        for ri, node in enumerate(column):
            centres[node] = (cx, first_y - ri * pitch_y)
    return centres, box_w, box_h, fontsize


def _serpentine(area, columns):
    """A long straight chain, wrapped over several rows and read boustrophedon.

    Six or more steps laid out in one row gives each box 20px of usable width;
    "TCP handshake" came out clipped to "TCP handshak". Wrapping keeps the
    boxes readable, and alternating the direction of each row means the arrow
    from the end of one row to the start of the next is a short hop down
    rather than a long sweep back across the frame.
    """
    left, bottom, right, top = area
    steps = [c[0] for c in columns]
    n = len(steps)

    per_row = 4 if n <= 8 else 5
    rows = (n + per_row - 1) // per_row

    span_x, span_y = right - left, top - bottom
    gap_x, gap_y = 8.0, 7.0
    box_w = min(30.0, (span_x - gap_x * (per_row - 1)) / per_row)
    box_h = min(16.0, (span_y - gap_y * (rows - 1)) / rows)
    fontsize = 15 if box_w >= 26 else 13

    pitch_x, pitch_y = box_w + gap_x, box_h + gap_y
    first_x = (left + right) / 2 - pitch_x * (per_row - 1) / 2
    first_y = (top + bottom) / 2 + pitch_y * (rows - 1) / 2

    centres = {}
    for i, node in enumerate(steps):
        row, col = divmod(i, per_row)
        if row % 2:                       # right to left on every other row
            col = per_row - 1 - col
        centres[node] = (first_x + col * pitch_x, first_y - row * pitch_y)
    return centres, box_w, box_h, fontsize
