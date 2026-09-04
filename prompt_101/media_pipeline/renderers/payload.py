"""Turn a VisualSpec.payload string into the structured `data` the renderers want.

WHY THIS EXISTS

Every renderer here does real work when handed data["nodes"], data["function"],
data["events"] and so on — and falls back to a hardcoded placeholder when it is
not. But shared/models.py VisualSpec carries only {kind, payload, caption}:
there is no data field, so nothing upstream could ever populate it.

The result was diagrams reading "Input -> Process -> Output", concept maps
labelled "Concept A/B/C/D", and a graph titled "y = 1/x" plotting a sine wave.
Content-free art that looks plausible at a glance — the worst kind of wrong.

So parse the payload here, where the renderer already knows what shape it needs.
Explicit data still wins; this only fills gaps.
"""

import re

_ARROW = re.compile(r"\s*(?:-->|->|→|=>|---|--)\s*")
_HEADER = re.compile(r"^\s*(?:graph|flowchart|digraph)\s+\w+\s*;?\s*", re.I)
_LABELLED = re.compile(r"^(\w+)\s*[\[\(\{]\s*(.+?)\s*[\]\)\}]$")

# `A[Voltage]` anywhere in the text declares that the id A means "Voltage".
_NODE_DEF = re.compile(r"(\w+)\s*[\[\(\{]\s*([^\[\]\(\)\{\}]+?)\s*[\]\)\}]")

# Mermaid writes an edge label as `A -->|carries charge| B`.
_EDGE_LABEL = re.compile(r"^\|\s*([^|]+?)\s*\|\s*")

_SAFE_EXPR = re.compile(r"^[\w\s\.\+\-\*/\(\)\^,]+$")
_FUNCS = ("sin", "cos", "tan", "exp", "log", "sqrt", "abs", "pi", "x")


def node_labels(content: str) -> dict[str, str]:
    """Every `id[Label]` declaration in the payload, as {id: label}.

    Mermaid names a node once and then refers to it by its bare id:

        A[Voltage] --> B[Current]; C[Resistance] --> B

    Without this map that last `B` is drawn as a box labelled "B" — which is
    what the diagrams were doing, sitting in the middle of a real circuit
    diagram as a single meaningless letter.
    """
    return {m.group(1): m.group(2).strip()
            for m in _NODE_DEF.finditer(content or "")}


def _label(token: str, known: dict[str, str] | None = None) -> str:
    """`A[Resistance]` -> `Resistance`; a bare `A` -> whatever A was declared as."""
    token = token.strip().rstrip(";").strip()
    m = _LABELLED.match(token)
    if m:
        return m.group(2).strip()
    if known and token in known:
        return known[token]
    return token


def parse_edges(content: str) -> list[tuple[str, str]]:
    """Pull (source, target) label pairs out of mermaid-ish text."""
    if not content:
        return []
    known = node_labels(content)
    text = _HEADER.sub("", content.strip())
    edges: list[tuple[str, str]] = []
    for statement in re.split(r"[;\n]+", text):
        parts = [p for p in _ARROW.split(statement) if p.strip()]
        if len(parts) < 2:
            continue
        # Strip any `|edge label|` the arrow left glued to the target.
        parts = [_EDGE_LABEL.sub("", p.strip()) for p in parts]
        labels = [_label(p, known) for p in parts]
        # Deliberately ragged: this pairs each label with the next one.
        for a, b in zip(labels, labels[1:], strict=False):
            if a and b and a != b:
                edges.append((a, b))
    return list(dict.fromkeys(edges))


def parse_nodes(content: str) -> list[str]:
    """Every distinct node label, in the order it first appears."""
    seen: dict[str, None] = {}
    for a, b in parse_edges(content):
        seen.setdefault(a, None)
        seen.setdefault(b, None)
    return list(seen)


def parse_function(content: str) -> str | None:
    """`y = 1/x` -> `1/x`. Returns None if nothing safely plottable."""
    if not content:
        return None
    expr = content.strip()
    if "=" in expr:
        expr = expr.split("=", 1)[1]
    expr = expr.strip().replace("^", "**")
    if not expr or not _SAFE_EXPR.match(expr):
        return None
    if "x" not in expr:
        return None                       # a constant is not worth a plot
    names = set(re.findall(r"[A-Za-z_]\w*", expr))
    if not names <= set(_FUNCS):
        return None                       # unknown symbol - do not guess
    return expr


def parse_events(content: str) -> list[dict]:
    """`1827: Ohm; 1831: Faraday` -> [{'year': '1827', 'label': 'Ohm'}, ...]"""
    events = []
    for part in re.split(r"[;\n]+", content or ""):
        m = re.match(r"\s*(\d{3,4}(?:\s*(?:BC|AD|BCE|CE))?)\s*[:\-–]\s*(.+)",
                     part.strip())
        if m:
            events.append({"year": m.group(1).strip(), "label": m.group(2).strip()})
    return events


def layout_boxes(labels: list[str]) -> list[dict]:
    """Lay node labels out as a left-to-right chain on the 0-10 canvas.

    The box-and-arrow renderer draws arrows between consecutive boxes, so chain
    order is what makes the arrows mean something.
    """
    labels = labels[:6]
    n = len(labels)
    if n == 0:
        return []

    # Width follows the label. The renderer measures the laid-out text and can
    # widen further; this is the starting estimate.
    widths = [max(2.3, len(label) * 0.19 + 0.7) for label in labels]

    # Keep every box inside the 0-10 axes. Centring the first box at a fixed
    # margin put wide boxes at a negative x, where matplotlib clipped them and
    # the label spilled past the visible edge.
    edge = max(widths) / 2 + 0.35
    left, right = edge, 10 - edge
    if right <= left:
        left = right = 5.0
    xs = [5.0] if n == 1 else [left + (right - left) * i / (n - 1)
                               for i in range(n)]

    return [
        {"x": x, "y": 5.0, "w": w, "h": 1.35, "label": label}
        for x, w, label in zip(xs, widths, labels, strict=True)
    ]


def enrich(kind: str, content: str, data: dict | None) -> dict:
    """Fill in whatever the renderer for `kind` needs, without overriding data."""
    out = dict(data or {})

    if kind == "diagram":
        if "boxes" not in out and "nodes" not in out:
            nodes = parse_nodes(content)
            if nodes:
                out["boxes"] = layout_boxes(nodes)

    elif kind == "concept_map":
        if "nodes" not in out and "related" not in out:
            nodes = parse_nodes(content)
            if nodes:
                out["central"] = nodes[0]
                out["related"] = nodes[1:] or nodes

    elif kind == "graph":
        if "function" not in out and "x_values" not in out:
            expr = parse_function(content)
            if expr:
                out["function"] = expr

    elif kind == "timeline":
        if "events" not in out:
            events = parse_events(content)
            if events:
                out["events"] = events

    return out
