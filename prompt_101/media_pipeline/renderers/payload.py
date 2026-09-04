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

_ARROW = re.compile(r"\s*(?:-->|->|→|=>|-\.->|==>)\s*")
_HEADER = re.compile(r"^\s*(?:graph|flowchart|digraph)\s+(?:TD|TB|BT|RL|LR|\w+)\s*;?\s*", re.I)
_LABELLED = re.compile(r"^([\w\-]+)\s*([\[\(\{]+)\s*(.+?)\s*([\]\)\}]+)$")

_EDGE_LABEL = re.compile(r"\|([^|]+)\|")

_SAFE_EXPR = re.compile(r"^[\w\s\.\+\-\*/\(\)\^,]+$")
_FUNCS = ("sin", "cos", "tan", "exp", "log", "sqrt", "abs", "pi", "x")


def _clean_label(text: str) -> str:
    """Clean quotes, markdown formatting, and brackets from label."""
    s = text.strip().rstrip(";").strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return s


def parse_graph(content: str) -> tuple[list[dict], list[dict]]:
    """Parse Mermaid text into (nodes, edges).
    
    Returns:
        nodes: list of {"id": str, "label": str}
        edges: list of {"from": str, "to": str, "label": str}
    """
    if not content:
        return [], []

    # Strip header like 'graph TD' or 'flowchart LR'
    text = _HEADER.sub("", content.strip())
    
    id_to_label: dict[str, str] = {}
    edges_raw: list[tuple[str, str, str]] = []

    for line in re.split(r"[;\n]+", text):
        line = line.strip()
        if not line or line.startswith("%%"):
            continue

        # Check for edge label like A -->|label| B or A -- label --> B
        edge_label = ""
        m_edge = _EDGE_LABEL.search(line)
        if m_edge:
            edge_label = m_edge.group(1).strip()
            line = line[:m_edge.start()] + "-->" + line[m_edge.end():]
        elif "--" in line and "-->" in line:
            m_mid = re.search(r"--\s*([^-]+?)\s*-->", line)
            if m_mid:
                edge_label = m_mid.group(1).strip()
                line = re.sub(r"--\s*[^-]+?\s*-->", "-->", line)

        parts = [p.strip() for p in _ARROW.split(line) if p.strip()]
        if not parts:
            continue

        parsed_part_ids = []
        for p in parts:
            m = _LABELLED.match(p)
            if m:
                node_id = m.group(1).strip()
                node_label = _clean_label(m.group(3))
                id_to_label[node_id] = node_label
                parsed_part_ids.append(node_id)
            else:
                clean_p = _clean_label(p)
                # If bare word, use as id and label unless id already seen
                if clean_p not in id_to_label:
                    id_to_label[clean_p] = clean_p
                parsed_part_ids.append(clean_p)

        for a, b in zip(parsed_part_ids, parsed_part_ids[1:]):
            if a and b:
                edges_raw.append((a, b, edge_label))

    # Build node list
    nodes = [{"id": nid, "label": id_to_label.get(nid, nid)} for nid in id_to_label]
    
    # If no edges were parsed but we have lines with labelled items
    if not edges_raw and len(nodes) > 1:
        # Fallback to chain
        for i in range(len(nodes) - 1):
            edges_raw.append((nodes[i]["id"], nodes[i+1]["id"], ""))

    edges = [
        {"from": a, "to": b, "label": lbl}
        for a, b, lbl in edges_raw
    ]
    return nodes, edges


def parse_edges(content: str) -> list[tuple[str, str]]:
    """Pull (source, target) label pairs out of mermaid-ish text."""
    nodes, edges = parse_graph(content)
    id_map = {n["id"]: n["label"] for n in nodes}
    return [(id_map.get(e["from"], e["from"]), id_map.get(e["to"], e["to"])) for e in edges]


def parse_nodes(content: str) -> list[str]:
    """Every distinct node label, in the order it first appears."""
    nodes, _ = parse_graph(content)
    return [n["label"] for n in nodes]


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
        for x, w, label in zip(xs, widths, labels)
    ]


def enrich(kind: str, content: str, data: dict | None) -> dict:
    """Fill in whatever the renderer for `kind` needs, without overriding data."""
    out = dict(data or {})

    if kind == "diagram":
        if "nodes" not in out and "boxes" not in out:
            nodes, edges = parse_graph(content)
            if nodes:
                out["nodes"] = nodes
                out["edges"] = edges
                out["boxes"] = layout_boxes([n["label"] for n in nodes])

    elif kind == "concept_map":
        if "nodes" not in out and "related" not in out:
            nodes, edges = parse_graph(content)
            if nodes:
                out["nodes"] = nodes
                out["edges"] = edges
                out["central"] = nodes[0]["label"]
                out["related"] = [n["label"] for n in nodes[1:]] or [nodes[0]["label"]]

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
