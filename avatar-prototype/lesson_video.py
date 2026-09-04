"""Render one teaching segment to an animated MP4, timed to its narration.

    python lesson_video.py --segment sample_segment.json --out seg.mp4
    python lesson_video.py --text "..." --kind equation --payload "V = I R"

Takes the same shape `teacher.next_segment()` already returns — a spoken
script, a visual kind and a payload — and produces a video in which the
diagram BUILDS while the teacher talks, instead of one still image held
motionless for the whole narration.

HOW THE TIMING WORKS

edge-tts emits a SentenceBoundary event per sentence, carrying a real offset
and duration. Each element of the visual is matched to the first sentence that
mentions it, and appears at that moment. So the box labelled "resistance"
arrives exactly as the teacher says the word.

(An earlier note in this repo said edge-tts gives nothing to align against.
That was wrong, and it was my own measurement error: a single-sentence probe
returns a single event, which looked like a whole-utterance boundary. Multi-
sentence text returns one event per sentence.)

Elements that match nothing are spread across whatever time is left, so a
payload whose labels do not appear in the script still builds rather than
appearing all at once.

Self-contained: reads font FILES from ../assets/fonts, but imports no repo code.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FFMpegWriter
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

PAPER, INK, MUTED = "#F5F1E8", "#12100E", "#6B6459"
YELLOW, BLUE, CORAL, TEAL, VIOLET = "#FFD400", "#4A7DFF", "#FF6B4A", "#12A594", "#7C5CFF"
ACCENTS = [BLUE, CORAL, TEAL, VIOLET, YELLOW]

W, H, DPI, FPS = 1280, 720, 100, 25

# The teacher stands bottom-right, so nothing meaningful may be drawn there.
# Same reserve make_visual.py uses, in the same 16x9 units.
SAFE_X, SAFE_Y = 13.1, 3.3


def setup_fonts() -> None:
    """Register the Noto scripts, or every Hindi label renders as tofu boxes.

    The repo already ships these under assets/fonts for exactly this reason;
    matplotlib only does per-glyph fallback across a concrete family list, so
    the list has to be explicit.
    """
    from matplotlib import font_manager
    stack = ["DejaVu Sans"]
    d = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    if d.is_dir():
        for ttf in sorted(d.glob("*.ttf")):
            try:
                font_manager.fontManager.addfont(str(ttf))
                name = font_manager.FontProperties(fname=str(ttf)).get_name()
                if name not in stack:
                    stack.append(name)
            except Exception:
                pass
    plt.rcParams["font.family"] = stack
    plt.rcParams["axes.unicode_minus"] = False
    import logging
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Payload parsing. These are the shapes the model actually emits, taken from
# 76 cached segments: 45 diagram, 29 equation, 2 concept_map.
# ---------------------------------------------------------------------------

@dataclass
class Element:
    label: str
    at: float = 0.0                      # seconds, filled in by schedule()
    edge_from: int | None = None         # index of the node this arrives from


# One pattern per bracket style. A single combined class does NOT work: on the
# real payload `A[बैटरी (वोल्टेज V)]` a class of "anything but a closing
# bracket" stops at the nested ")", so every label came out truncated —
# "बैटरी (वोल्टेज V" with the bracket missing.
NODE_PATTERNS = [
    re.compile(r"([A-Za-z]\w*)\s*\[([^\]]*)\]"),
    re.compile(r"([A-Za-z]\w*)\s*\(\(?([^)]*)\)\)?"),
    re.compile(r"([A-Za-z]\w*)\s*\{([^}]*)\}"),
]
LABEL_BLOCK = re.compile(r"\[[^\]]*\]|\{[^}]*\}|\([^)]*\)")
# The optional `|edge label|` has to be an all-or-nothing group. Written as
# `\|?[^|]*\|?` the middle is greedy and matches across the whole payload, so
# `A --> B  B --> C  C --> D` parsed as the single edge A -> D.
MERMAID_EDGE = re.compile(
    r"([A-Za-z]\w*)\s*[-=.]{1,2}[->.]*>\s*(?:\|[^|]*\|\s*)?([A-Za-z]\w*)")


def parse_diagram(payload: str) -> list[Element]:
    """Mermaid flowchart -> ordered nodes with the edge that reaches each.

    Real payload: `flowchart LR A[battery] --> B[tank] B --> C[pipe]`
    Some payloads are not diagrams at all — one cached segment's payload is
    the literal string "crowd_doorway_diagram.png". Those yield nothing here
    and the caller falls back to the script itself.
    """
    payload = payload or ""
    names: dict[str, str] = {}
    for pattern in NODE_PATTERNS:
        for key, label in pattern.findall(payload):
            names.setdefault(key, label.strip())
    # Edges are invisible until the labels are removed: `A[...] --> B[...]`
    # has a "]" where the edge pattern needs the node id, so nothing matched
    # and the nodes came out in dictionary order instead of flow order.
    stripped = LABEL_BLOCK.sub(" ", payload)
    order: list[str] = []
    edges = MERMAID_EDGE.findall(stripped)
    for a, b in edges:
        for k in (a, b):
            if k not in order:
                order.append(k)
    for k in names:
        if k not in order:
            order.append(k)
    if not order:
        return []
    index = {k: i for i, k in enumerate(order)}
    incoming = {b: a for a, b in edges}
    return [
        Element(label=names.get(k, k),
                edge_from=index.get(incoming.get(k)) if k in incoming else None)
        for k in order
    ]


def split_latex(payload: str) -> list[str]:
    """Break an equation into terms that can be revealed one at a time.

    Splits on =, +, -, \\times and \\cdot at brace depth zero, so
    `I = \\frac{Q}{t}` becomes ['I', '=', '\\frac{Q}{t}'] and the fraction
    survives intact.
    """
    s = (payload or "").strip().strip("$")
    out, buf, depth, i = [], "", 0, 0
    ops = ["\\times", "\\cdot", "=", "+", "-"]
    while i < len(s):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
        matched = None
        if depth == 0:
            for op in ops:
                if s.startswith(op, i):
                    matched = op
                    break
        if matched:
            if buf.strip():
                out.append(buf.strip())
            out.append(matched)
            i += len(matched)
            buf = ""
            continue
        buf += s[i]
        i += 1
    if buf.strip():
        out.append(buf.strip())
    return [t for t in out if t]


def parse_equation(payload: str) -> list[Element]:
    return [Element(label=t) for t in split_latex(payload)]


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

@dataclass
class Sentence:
    text: str
    start: float
    end: float


@dataclass
class Narration:
    audio: Path
    sentences: list[Sentence] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.sentences[-1].end if self.sentences else 0.0


async def _synthesise(text: str, voice: str, mp3: Path) -> list[Sentence]:
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate="-8%")
    sentences: list[Sentence] = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                start = chunk["offset"] / 1e7
                sentences.append(Sentence(str(chunk.get("text", "")), start,
                                          start + chunk["duration"] / 1e7))
    return sentences


def narrate(text: str, voice: str, workdir: Path) -> Narration:
    """Speak the script and return the audio plus real per-sentence timings."""
    mp3 = workdir / "narration.mp3"
    sentences = asyncio.run(_synthesise(text, voice, mp3))
    if not sentences:
        raise RuntimeError("edge-tts returned no sentence boundaries")
    return Narration(audio=mp3, sentences=sentences)


# Split on separators rather than matching a letter class. `[^\W\d_]` excludes
# Devanagari combining vowel signs, so "बैटरी" was being chopped at every
# matra and nothing ever matched a Hindi sentence — every element fell back to
# even spacing, which is what the first run did.
_SEPARATORS = re.compile(r"[\s\u0964\u0965,.;:!?()\[\]{}\"'\u2014\u2013-]+")


def _words(text: str) -> list[str]:
    return [w for w in _SEPARATORS.split(text) if len(w) >= 3]


MIN_GAP = 0.7          # seconds; two reveals closer than this read as one


def schedule(elements: list[Element], sentences: list[Sentence]) -> None:
    """Give each element the time of the first sentence that mentions it.

    Matching is on words of three characters or more, split on separators so
    it behaves the same in Devanagari as in Latin.

    Several elements often match the SAME sentence — one Hindi script named
    four of them in a single breath — so a matched group is spread across that
    sentence's own span rather than stacked on its start. Without that they
    all appeared on one frame, which is the thing this file exists to avoid.
    """
    if not elements or not sentences:
        return

    lowered = [s.text.lower() for s in sentences]
    matched: list[int | None] = []
    for el in elements:
        words = [w.lower() for w in _words(el.label)]
        matched.append(next(
            (i for i, text in enumerate(lowered)
             if any(w in text for w in words)), None))

    groups: dict[int, list[int]] = {}
    for i, sidx in enumerate(matched):
        if sidx is not None:
            groups.setdefault(sidx, []).append(i)

    for sidx, idxs in groups.items():
        sent = sentences[sidx]
        span = max(sent.end - sent.start, 0.6)
        for j, i in enumerate(idxs):
            # Land inside the sentence, never on its final word.
            elements[i].at = sent.start + span * (j / len(idxs)) * 0.8

    first, last = sentences[0].start, sentences[-1].end
    for i, el in enumerate(elements):
        if matched[i] is None:
            frac = (i + 1) / (len(elements) + 1)
            el.at = first + (last - first) * frac * 0.75

    # A reveal must never precede one that comes before it in the flow, and two
    # must never land close enough to read as a single pop.
    running = 0.0
    for el in elements:
        el.at = running = max(el.at, running)
        running += MIN_GAP


# ---------------------------------------------------------------------------
# Drawing
#
# The visual language: a calm lesson board. Ink type on paper, Mentora's
# accents used sparingly -- cards are pale tints of their accent rather than
# full-saturation slabs, boxes are rounded and softly shadowed instead of
# outlined in black, and the title is type with a yellow tick rather than a
# sticker over the whole top of the frame. Colour carries meaning (one accent
# per element, a step badge on a chain), never noise.
# ---------------------------------------------------------------------------


def ease(t: float, start: float, dur: float = 0.5) -> float:
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    x = (t - start) / dur
    return 0.0 if x <= 0 else 1.0 if x >= 1 else 1 - (1 - x) ** 3


def wrap(text: str, per_line: int) -> str:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if len(trial) > per_line and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return "\n".join(lines[:3])


def anchors(src, dst):
    """Where an arrow should leave one box and meet the next.

    Centre-to-centre with a large shrink was hiding the arrowhead inside the
    target box, so every edge rendered as a bare line. Leaving from the edge
    facing the target means the head is always in open space.
    """
    sx, sy, sw, sh = src
    dx, dy, dw, dh = dst
    scx, scy, dcx, dcy = sx + sw / 2, sy + sh / 2, dx + dw / 2, dy + dh / 2
    if abs(dcx - scx) >= abs(dcy - scy):
        return ((sx + sw, scy), (dx, dcy)) if dcx > scx \
            else ((sx, scy), (dx + dw, dcy))
    return ((scx, sy), (dcx, dy + dh)) if dcy < scy \
        else ((scx, sy + sh), (dcx, dy))


def grid(n: int) -> list[tuple[float, float, float, float]]:
    """Node boxes, laid out entirely clear of the avatar corner.

    A chain of four reads as a flow on one row. Wrapping it into 2x2 sent the
    second edge diagonally across the frame from top-right to bottom-left,
    which is the opposite of the direction the lesson is going. Boxes are
    narrower than the cell so the arrows between them have room to breathe.
    """
    if n <= 0:
        return []
    cols = min(n, 4) if n <= 4 else 3
    rows = (n + cols - 1) // cols
    x0, x1, y0, y1 = 0.9, 12.95, 2.05, 6.85
    cw, ch = (x1 - x0) / cols, (y1 - y0) / rows
    bw = cw * 0.80
    bh = min(ch * 0.92, 2.60)
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        bx = x0 + c * cw + (cw - bw) / 2
        by = y1 - (r + 1) * ch + (ch - bh) / 2
        out.append((bx, by, bw, bh))
    return out


def mathtext(term: str) -> str:
    return f"${term}$" if term not in ("=", "+", "-") else term


def _rgb(hexcolour: str) -> list[float]:
    h = hexcolour.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def mix(a: str, b: str, t: float) -> str:
    """Blend hex colour a toward b by t in [0, 1]."""
    ca, cb = _rgb(a), _rgb(b)
    return "#" + "".join(
        "%02X" % round((ca[i] + (cb[i] - ca[i]) * t) * 255) for i in range(3))


def rrect(ax, x, y, w, h, r, *, face="#FFFFFF", edge=None, lw=1.0,
          z=1, alpha=1.0):
    """A rounded rectangle patch; rounding is clamped to the half-dimensions."""
    r = max(0.0, min(r, w / 2, h / 2))
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r:.3f}",
        facecolor=face, edgecolor=edge if edge else "none",
        linewidth=lw, zorder=z, alpha=alpha))


def title_bar(ax, t, caption) -> None:
    """Type, not a sticker: ink headline beside a short yellow tick."""
    a = ease(t, 0.0, 0.45)
    if a <= 0.0:
        return
    line = wrap(caption or "", 46).split("\n")[0]
    fs = 28 if len(line) <= 40 else 23
    rrect(ax, 0.62, 7.66, 0.30, 0.98, 0.15, face=YELLOW, z=6, alpha=a)
    ax.text(1.18, 8.15, line, fontsize=fs, fontweight="bold", color=INK,
            va="center", ha="left", zorder=8, alpha=a)


def subtitle(ax, t, sentences) -> None:
    """The sentence being spoken, as a soft caption capsule bottom-centre.

    The capsule only spans its own text instead of the full width, so it
    reads as a subtitle rather than a bar of chrome.
    """
    live = next((s for s in sentences if s.start <= t < s.end), None)
    if live is None:
        return
    rise = ease(t, live.start, 0.25)
    settle = 1.0 - ease(t, live.end, 0.18)
    a = rise * settle
    if a <= 0.0:
        return
    lines = wrap(live.text.strip(), 66).split("\n")[:2]
    fs = 15.5
    glyph = fs * 0.60 / 80.0          # rough advance per char, in 16x9 units
    w = min(max(max(len(l) for l in lines) * glyph + 1.4, 3.2), 11.6)
    h = 0.92 if len(lines) == 1 else 1.30
    cx = 6.6
    x, y = cx - w / 2, 0.24
    rrect(ax, x + 0.08, y - 0.10, w, h, 0.26, face=INK, z=10, alpha=0.07 * a)
    rrect(ax, x, y, w, h, 0.26, face="#FFFFFF", z=11, alpha=a)
    rrect(ax, x, y, w, h, 0.26, edge=INK, lw=1.2, z=12, alpha=0.20 * a)
    ax.text(cx, y + h / 2, "\n".join(lines), fontsize=fs, color=INK,
            va="center", ha="center", linespacing=1.28, zorder=13, alpha=a)


def progress_bar(ax, t, total) -> None:
    if total <= 0.0:
        return
    frac = min(max(t / total, 0.0), 1.0)
    if frac <= 0.0:
        return
    rrect(ax, 0.0, 8.875, 16.0 * frac, 0.10, 0.05, face=CORAL, z=20,
          alpha=0.85)


_DEVA = re.compile("[\u0900-\u097F]")
# Steps are 1..n, so index 0 maps to १, not to the zero glyph.
_DEVA_DIGITS = ["०", "१", "२", "३", "४", "५", "६", "७", "८", "९"]


def _is_chain(elements) -> bool:
    """True when every element (after the first) arrives from its predecessor,
    so the badges can honestly number the steps of a flow. A branching
    diagram gets coloured dots' worth of meaning, not fake ordering."""
    if not elements or elements[0].edge_from is not None:
        return False
    out = [0] * len(elements)
    for i, el in enumerate(elements):
        if i and el.edge_from != i - 1:
            return False
        if el.edge_from is not None:
            out[el.edge_from] += 1
            if out[el.edge_from] > 1:
                return False
    return True


def draw_flow(ax, t, elements) -> None:
    boxes = grid(len(elements))
    chain = _is_chain(elements)
    deva = any(_DEVA.search(el.label or "") for el in elements)

    # Arrows first, beneath the cards, so each connection appears exactly as
    # the box it reaches does -- and stops cleanly at that box's edge.
    for i, (el, box) in enumerate(zip(elements, boxes)):
        e = ease(t, el.at, 0.5)
        if e <= 0.0 or el.edge_from is None or el.edge_from >= len(boxes):
            continue
        tail, head = anchors(boxes[el.edge_from], box)
        ax.add_patch(FancyArrowPatch(tail, head, arrowstyle="-|>",
                                     mutation_scale=15, color=INK, lw=2.2,
                                     alpha=e * 0.80, zorder=3))

    for i, (el, (bx, by, bw, bh)) in enumerate(zip(elements, boxes)):
        e = ease(t, el.at, 0.5)
        if e <= 0.0:
            continue
        accent = ACCENTS[i % len(ACCENTS)]
        # Grow from 88% to full around the centre, so a reveal is a settling
        # card rather than a sudden sticker.
        s = 0.88 + 0.12 * e
        w2, h2 = bw * s, bh * s
        x2, y2 = bx + (bw - w2) / 2, by + (bh - h2) / 2
        face = mix("#FFFFFF", accent, 0.10)
        rrect(ax, x2 + 0.09, y2 - 0.11, w2, h2, 0.20, face=INK, z=4,
              alpha=0.09 * e)
        rrect(ax, x2, y2, w2, h2, 0.20, face=face, z=5, alpha=e)
        rrect(ax, x2, y2, w2, h2, 0.20, edge=INK, lw=1.2, z=6, alpha=0.12 * e)

        # A step badge on a genuine chain; colour alone otherwise.
        if chain:
            r = 0.30
            bcx, bcy = bx + bw / 2, by + bh - 0.50
            ax.add_patch(Circle((bcx, bcy), r, facecolor=accent,
                                edgecolor="none", zorder=7))
            if deva:
                glyph = _DEVA_DIGITS[(i + 1) % 10] if i + 1 < 10 else "•"
            else:
                glyph = str(i + 1)
            ax.text(bcx, bcy, glyph, fontsize=12.5, fontweight="bold",
                    color="#FFFFFF", ha="center", va="center", zorder=8)

        fs = 15 if len(boxes) <= 4 else 13
        ax.text(bx + bw / 2, by + bh / 2 - 0.16,
                wrap(el.label, max(9, int(bw * 5.0))),
                fontsize=fs, fontweight="bold", color=INK, ha="center",
                va="center", linespacing=1.3, zorder=8, alpha=e)


def draw_equation(ax, t, elements) -> None:
    """Terms settle into place in ink; each arrival flashes its accent once,
    so colour marks what is new without the finished equation looking like a
    row of unrelated symbols."""
    ops = ("=", "+", "-", "\\times", "\\cdot")
    gap, cx, cy = 2.3, 6.6, 4.95
    first = cx - gap * (len(elements) - 1) / 2
    for i, el in enumerate(elements):
        e = ease(t, el.at, 0.5)
        x = first + gap * i
        if e <= 0.0:
            continue
        op = el.label in ops
        fs = 44 if op else 62
        colour = INK if op else mix(ACCENTS[i % len(ACCENTS)], INK, e)
        try:
            ax.text(x, cy - (1 - e) * 0.35, mathtext(el.label), fontsize=fs,
                    fontweight="bold", color=colour, ha="center", va="center",
                    alpha=e, zorder=6)
        except Exception:
            ax.text(x, cy - (1 - e) * 0.35, el.label, fontsize=fs, color=colour,
                    ha="center", va="center", alpha=e, zorder=6)

    # Once the equation is complete, a soft rule settles beneath it -- one
    # pop of emphasis, then it stays, instead of pulsing for the whole video.
    last = elements[-1].at
    if elements and t > last + 0.55:
        since = t - last - 0.55
        a = 0.60 * ease(since, 0.0, 0.6) + \
            0.30 * max(0.0, np.sin(since * 4.2)) * np.exp(-since * 2.0)
        if a > 0.01:
            span = gap * (len(elements) - 1) + 2.1
            rrect(ax, first - 1.05, 3.52, span, 0.17, 0.085, face=YELLOW,
                  z=6, alpha=min(a, 0.9))


def draw_fallback(ax, t, caption) -> None:
    """Junk payloads -- one cached segment's is literally a .png filename --
    get a plain quotation card of the script instead of an apology."""
    a = ease(t, 0.5, 0.5)
    if a <= 0.0:
        return
    lines = wrap(caption or "", 30).split("\n")[:3]
    fs = 27 if max(len(l) for l in lines) <= 26 else 22
    glyph = fs * 0.62 / 80.0
    w = min(max(len(l) for l in lines) * glyph + 2.4, 13.2)
    h = len(lines) * fs * 1.5 / 80.0 + 1.1
    cx, cy = 6.6, 4.55
    x, y = cx - w / 2, cy - h / 2
    rrect(ax, x + 0.10, y - 0.12, w, h, 0.28, face=INK, z=4, alpha=0.08 * a)
    rrect(ax, x, y, w, h, 0.28, face="#FFFFFF", z=5, alpha=a)
    rrect(ax, x, y, w, h, 0.28, edge=INK, lw=1.2, z=6, alpha=0.18 * a)
    ax.text(cx, cy, "\n".join(lines), fontsize=fs, fontweight="bold",
            color=INK, ha="center", va="center", linespacing=1.35, zorder=8,
            alpha=a)


def draw(ax, t, elements, kind, caption, sentences, total):
    ax.clear()
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis("off")

    if kind == "equation" and elements:
        title_bar(ax, t, caption)
        draw_equation(ax, t, elements)
    elif elements:
        title_bar(ax, t, caption)
        draw_flow(ax, t, elements)
    else:
        draw_fallback(ax, t, caption)

    subtitle(ax, t, sentences)
    progress_bar(ax, t, total)

# ---------------------------------------------------------------------------

def build(segment: dict, out: Path, voice: str) -> int:
    setup_fonts()
    script = (segment.get("script") or "").strip()
    if not script:
        print("segment has no script", file=sys.stderr)
        return 2
    visual = segment.get("visual") or {}
    kind = visual.get("kind") or "none"
    payload = visual.get("payload") or ""
    caption = (visual.get("caption") or script[:60]).strip()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        print(f"speaking {len(script)} chars as {voice} ...")
        narration = narrate(script, voice, work)

        elements = (parse_equation(payload) if kind == "equation"
                    else parse_diagram(payload))
        schedule(elements, narration.sentences)
        total = narration.duration + 1.2

        print(f"  {len(narration.sentences)} sentences, {total:.1f}s, "
              f"{len(elements)} element(s) from a {kind} payload")
        for el in elements:
            print(f"    {el.at:6.2f}s  {el.label[:52]}")

    return encode(out, elements, kind, caption, narration)


def encode(out: Path, elements: list[Element], kind: str, caption: str,
           narration: Narration) -> int:
    """Draw and mux a narrated board video into `out`.

    Factored out of build() so the rest of Mentora can render the same
    animated board from audio it has already synthesised (no second TTS):
    hand it a Narration whose .audio is the existing WAV and whose
    .sentences come from any source with real start/end times.
    """
    setup_fonts()
    total = narration.duration + 1.2
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        matplotlib.rcParams["animation.ffmpeg_path"] = ffmpeg
    except Exception:
        ffmpeg = "ffmpeg"

    silent = out.parent / f".{out.stem}_silent.mp4"
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(PAPER)
    writer = FFMpegWriter(fps=FPS, bitrate=2600,
                          extra_args=["-pix_fmt", "yuv420p"])
    try:
        with writer.saving(fig, str(silent), DPI):
            for f in range(int(total * FPS)):
                draw(ax, f / FPS, elements, kind, caption,
                     narration.sentences, total)
                writer.grab_frame(facecolor=PAPER)
    finally:
        plt.close(fig)

    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(silent),
         "-i", str(narration.audio), "-c:v", "copy", "-c:a", "aac",
         "-shortest", "-movflags", "+faststart", str(out)],
        check=True, timeout=300)
    try:
        silent.unlink()
    except OSError:
        pass

    print(f"{out}  {out.stat().st_size / 1024:.0f} KB  {total:.1f}s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--segment", help="JSON file with script/visual, as "
                                      "teacher.next_segment() returns")
    ap.add_argument("--text"), ap.add_argument("--kind", default="diagram")
    ap.add_argument("--payload", default=""), ap.add_argument("--caption")
    ap.add_argument("--voice", default="en-IN-NeerjaNeural")
    ap.add_argument("--out", default="segment.mp4")
    args = ap.parse_args()

    if args.segment:
        segment = json.loads(Path(args.segment).read_text(encoding="utf-8"))
    elif args.text:
        segment = {"script": args.text,
                   "visual": {"kind": args.kind, "payload": args.payload,
                              "caption": args.caption}}
    else:
        ap.error("give --segment or --text")
    return build(segment, Path(args.out), args.voice)


if __name__ == "__main__":
    raise SystemExit(main())
