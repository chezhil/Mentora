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
import importlib.util
import json
import os
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
    matched: bool = False                # True when a spoken word placed it


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
# The target is matched with a LOOKAHEAD so it is not consumed: mermaid
# chains edges on one line -- `A --> B --> C` -- and a consuming match would
# swallow B, leaving " --> C" with nothing in front of it. Half the arrows in
# a chained payload went missing that way, which is how a five-step process
# came out as three loose boxes and two orphans.
MERMAID_EDGE = re.compile(
    r"([A-Za-z]\w*)\s*[-=.]{1,2}[->.]*>\s*(?:\|[^|]*\|\s*)?(?=([A-Za-z]\w*))")


def parse_diagram(payload: str) -> list[Element]:
    """Mermaid flowchart -> ordered nodes with the edge that reaches each.

    Real payload: `flowchart LR A[battery] --> B[tank] B --> C[pipe]`
    Some payloads are not diagrams at all — one cached segment's payload is
    the literal string "crowd_doorway_diagram.png". Those yield nothing here
    and the caller falls back to the script itself.
    """
    payload = payload or ""
    names: dict[str, str] = {}

    # Blank each match out as it is taken, so a later pattern cannot match
    # INSIDE an earlier one's label. Running them independently over the raw
    # payload meant `D[Ender Dragon (perches on top)]` matched the SQUARE
    # pattern as D, and then the ROUND pattern matched "Dragon (perches on
    # top)" inside that same label and invented a node called "Dragon" whose
    # text was "perches on top". Any label with a parenthetical -- and models
    # write those constantly -- produced a phantom node with no edges, which
    # is what the stray A/B/C/D boxes beside the real ones were.
    remaining = payload

    def _capture(m):
        names.setdefault(m.group(1), m.group(2).strip())
        return " " * len(m.group(0))

    for pattern in NODE_PATTERNS:
        remaining = pattern.sub(_capture, remaining)
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


_TOKEN = re.compile(r"[^\s,.;:!?()\[\]{}\"'\u0964\u0965\u2014\u2013-]+")
_LATEX_CMD = re.compile(r"\\[a-zA-Z]+")


def _words(label: str) -> list[str]:
    """The words worth looking for in the script.

    LaTeX is stripped first: `\\frac{Q}{t}` has to yield Q and t, not "frac".
    Tokens are split on separators rather than matched with a letter class,
    because `[^\\W\\d_]` excludes Devanagari combining vowel signs and chopped
    every Hindi word at its matras.
    """
    text = _LATEX_CMD.sub(" ", label)
    text = re.sub(r"[{}$^_\\]", " ", text)
    return [w for w in _TOKEN.findall(text) if w]


def _position(word: str, text: str) -> int | None:
    """Where `word` occurs in `text`, or None.

    Words of one or two characters must match a WHOLE token. An equation term
    is often a single letter, and a substring search for "I" hits the i in
    "divided" and lands the reveal on the wrong sentence entirely.
    """
    word = word.lower()
    if len(word) >= 3:
        i = text.find(word)
        return i if i >= 0 else None
    for m in _TOKEN.finditer(text):
        if m.group(0).lower() == word:
            return m.start()
    return None


MIN_GAP = 0.35         # seconds; two reveals closer than this read as one


def schedule(elements: list[Element], sentences: list[Sentence]) -> None:
    """Time each element to the moment its word is actually spoken.

    Matching to a sentence is not precise enough on its own. One Hindi script
    names four things in a single nine-second sentence, so anchoring all four
    to the sentence START put every box on screen before three of them were
    mentioned. The offset of the matched word WITHIN the sentence is used to
    interpolate across the sentence's own duration instead.

    Which sentence is scored, not taken first-come. Accepting the earliest
    sentence containing ANY word of a label meant the opening line -- which
    names the topic, so it is full of the very nouns the boxes are made of --
    swallowed most of them: "Alright, let's break down how a Nether portal
    works" claimed both "Portal field appears" and "Arrive in Nether at scaled
    coords", putting those two boxes on screen at 3.4s and 2.8s, ahead of the
    first box at 7.6s. A word is now worth 1/(sentences it appears in), so
    "obsidian" or "ignite" outweighs a "portal" that turns up in half the
    script, and the sentence with the best total wins. Ties go to the earlier
    sentence, and the reveal lands on the most distinctive word within it.
    """
    if not elements or not sentences:
        return

    lowered = [s.text.lower() for s in sentences]
    words = {id(el): [w.lower() for w in _words(el.label)] for el in elements}
    spread: dict[str, int] = {}
    for ws in words.values():
        for word in ws:
            if word not in spread:
                spread[word] = sum(1 for text in lowered
                                   if _position(word, text) is not None)

    for el in elements:
        best = None
        for si, text in enumerate(lowered):
            score, pos, top = 0.0, None, 0.0
            for word in words[id(el)]:
                at = _position(word, text)
                if at is None:
                    continue
                weight = 1.0 / max(spread.get(word, 1), 1)
                score += weight
                if weight > top:
                    top, pos = weight, at
            if score > 0.0 and (best is None or score > best[0]):
                best = (score, si, pos)
        el.matched = best is not None
        if best:
            _, si, pos = best
            sent = sentences[si]
            frac = pos / max(len(lowered[si]), 1)
            el.at = sent.start + (sent.end - sent.start) * frac * 0.92

    # An element nobody says — an "=" between two named terms — belongs BETWEEN
    # its matched neighbours, not spread across the whole narration. Sending it
    # to an even fraction of the total put the equals sign ten seconds before
    # the fraction it joins.
    first, last = sentences[0].start, sentences[-1].end
    for i, el in enumerate(elements):
        if el.matched:
            continue
        prev = next((e.at for e in reversed(elements[:i]) if e.matched), first)
        nxt = next((e.at for e in elements[i + 1:] if e.matched), last)
        gap_before = sum(1 for e in elements[:i] if not e.matched)
        run = sum(1 for e in elements[i:] if not e.matched) + 1
        el.at = prev + (nxt - prev) * (gap_before + 1) / (gap_before + run)

    # Spread collisions in the order things are SPOKEN, not the order they sit
    # in the flowchart. The script names these in its own order — one Hindi
    # segment mentions the battery last though it is node A — and clamping to
    # flow order dragged every later box back to within 0.35s of the first,
    # which is what "the images do not show up on time" was. Layout keeps the
    # flow order; only the timing follows the voice.
    for i in sorted(range(len(elements)), key=lambda i: elements[i].at):
        el = elements[i]
        earlier = [e.at for j, e in enumerate(elements)
                   if j != i and e.at <= el.at]
        if earlier:
            el.at = max(el.at, max(earlier) + MIN_GAP)


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

    Rows past the first run backwards (boustrophedon), the way a plough turns
    at the end of a furrow. Left-to-right on every row meant the wrap edge --
    last box of one row to first box of the next -- was a long diagonal from
    the right edge back to the left, and on a five-box flow it crossed behind
    every other box on the way. Reversing alternate rows turns that edge into
    a short vertical drop, and it right-aligns a partly-filled final row so
    the drop still lands directly under its parent.
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
        if r % 2:
            c = cols - 1 - c
        bx = x0 + c * cw + (cw - bw) / 2
        by = y1 - (r + 1) * ch + (ch - bh) / 2
        out.append((bx, by, bw, bh))
    return out


def _depth_of(elements) -> list[int]:
    """How far each node sits from a root, following edge_from."""
    out = []
    for i in range(len(elements)):
        d, seen, cur = 0, {i}, elements[i].edge_from
        while cur is not None and cur not in seen and d < len(elements):
            seen.add(cur)
            cur = elements[cur].edge_from
            d += 1
        out.append(d)
    return out


def layered(elements) -> list[tuple[float, float, float, float]]:
    """Rank a branching graph by depth: parents above, children below.

    A grid is right for a chain and wrong for a tree. Laying a tree out in
    reading order put a parent in the top-right and its child in the
    bottom-left, so the edges ran the full diagonal of the frame and crossed
    each other. Ranking by depth makes every edge short and downward.
    """
    if not elements:
        return []                     # grid(0) returns []; match it
    depths = _depth_of(elements)
    rows: dict[int, list[int]] = {}
    for i, d in enumerate(depths):
        rows.setdefault(d, []).append(i)

    x0, x1, y0, y1 = 0.9, 12.95, 1.9, 6.9
    n_rows = max(rows) + 1
    rh = (y1 - y0) / n_rows
    bh = min(rh * 0.78, 1.9)
    boxes = [(0.0, 0.0, 0.0, 0.0)] * len(elements)
    for d, idxs in rows.items():
        cw = (x1 - x0) / len(idxs)
        bw = min(cw * 0.86, 4.2)
        for j, i in enumerate(idxs):
            bx = x0 + cw * j + (cw - bw) / 2
            by = y1 - (d + 1) * rh + (rh - bh) / 2
            boxes[i] = (bx, by, bw, bh)
    return boxes


def fit_label(ax, text: str, bw: float, bh: float, max_fs: float):
    """Wrap and size a node label so it fits inside its card.

    The label used to be wrapped at `int(bw * 5.0)` characters at a fixed
    font size, both guesses. Long labels overflowed the card, and wrap()
    silently dropped anything past its third line. Measure instead, and shrink
    the type until the text is genuinely inside the box.
    """
    inner_w, inner_h = bw - 0.42, bh - 0.34
    fs = max_fs
    while fs >= 8.0:
        per_line = max(8, int(inner_w / (fs * 0.62 * UNITS_PER_PX)))
        lines = _wrap_lines(text, per_line)
        body = "\n".join(lines)
        w, h = _text_size(ax, body, fs)
        if w <= inner_w and h <= inner_h:
            return body, fs
        fs -= 1.0
    return "\n".join(_wrap_lines(text, 14)), 8.0


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
    # Measure, do not guess. Wrapping at 46 characters and keeping only the
    # first line silently ate the end of any longer caption -- "How eating at
    # a laptop impacts hardware and", with the "focus." missing. Scale the
    # type to fit one line instead, and ellipsise only if even the smallest
    # will not go.
    line = " ".join((caption or "").split())
    avail = 14.1                     # from x=1.18 to the right edge
    for fs in (28.0, 25.0, 23.0, 21.0, 19.0):
        if _text_size(ax, line, fs)[0] <= avail:
            break
    else:
        fs = 19.0
        while len(line) > 12 and _text_size(ax, line + "\u2026", fs)[0] > avail:
            line = line[:-1].rstrip()
        line += "\u2026"
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
    body, fs, w, h = subtitle_layout(ax, live.text.strip())
    cx = 6.6
    x, y = cx - w / 2, 0.24
    rrect(ax, x + 0.08, y - 0.10, w, h, 0.26, face=INK, z=10, alpha=0.07 * a)
    rrect(ax, x, y, w, h, 0.26, face="#FFFFFF", z=11, alpha=a)
    rrect(ax, x, y, w, h, 0.26, edge=INK, lw=1.2, z=12, alpha=0.20 * a)
    ax.text(cx, y + h / 2, body, fontsize=fs, color=INK,
            va="center", ha="center", linespacing=1.28, zorder=13, alpha=a)


# Measuring text beats estimating it. The box used to be sized from
# `len(line) * fontsize * 0.60`, a guess at the average glyph advance, and then
# clamped to two lines — so a long sentence had its tail silently dropped, and
# Devanagari (whose glyphs are wider than the guess) overflowed the capsule it
# was supposed to sit inside. Now the real extent is measured.
#
# A sentence is on screen for a few seconds, which is roughly a hundred frames
# at 25fps, so the measurement is cached and costs one layout per sentence.
_TEXT_CACHE: dict[tuple[str, float], tuple[float, float]] = {}
UNITS_PER_PX = 1.0 / 80.0          # the axes is 16x9 across 1280x720
SUB_MAX_W, SUB_MAX_LINES = 11.6, 3


def _wrap_lines(text: str, per_line: int) -> list[str]:
    """Like wrap(), but it never throws away the lines that do not fit."""
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
    return lines


def _text_size(ax, text: str, fs: float) -> tuple[float, float]:
    key = (text, fs)
    hit = _TEXT_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        artist = ax.text(0, 0, text, fontsize=fs, linespacing=1.28)
        box = artist.get_window_extent(ax.figure.canvas.get_renderer())
        artist.remove()
        size = (box.width * UNITS_PER_PX, box.height * UNITS_PER_PX)
    except Exception:
        # No renderer yet: fall back to the old estimate rather than fail.
        widest = max((len(l) for l in text.split("\n")), default=1)
        size = (widest * fs * 0.62 * UNITS_PER_PX,
                (text.count("\n") + 1) * fs * 1.5 * UNITS_PER_PX)
    _TEXT_CACHE[key] = size
    return size


def subtitle_layout(ax, text: str):
    """Body text, font size and capsule size that actually fits it.

    Tries progressively smaller type and wider wraps until the whole sentence
    fits the capsule in at most three lines. Shrinking the type is always
    preferable to dropping words: the subtitle exists to be read.
    """
    for fs in (15.5, 14.0, 12.5, 11.0):
        for per_line in (66, 78, 92):
            lines = _wrap_lines(text, per_line)
            if len(lines) > SUB_MAX_LINES:
                continue
            body = "\n".join(lines)
            w, h = _text_size(ax, body, fs)
            if w + 1.4 <= SUB_MAX_W:
                return body, fs, max(w + 1.4, 3.2), h + 0.58
    # A single unbreakable run longer than the frame. Clamp rather than spill.
    body = "\n".join(_wrap_lines(text, 92)[:SUB_MAX_LINES])
    w, h = _text_size(ax, body, 11.0)
    return body, 11.0, min(max(w + 1.4, 3.2), SUB_MAX_W), h + 0.58


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
    chain = _is_chain(elements)
    # A chain reads as a row; anything that branches needs ranking, or its
    # edges cross the frame.
    boxes = grid(len(elements)) if chain else layered(elements)
    deva = any(_DEVA.search(el.label or "") for el in elements)

    # Arrows first, beneath the cards, so each connection appears exactly as
    # the box it reaches does -- and stops cleanly at that box's edge.
    for i, (el, box) in enumerate(zip(elements, boxes)):
        if el.edge_from is None or el.edge_from >= len(boxes):
            continue
        # BOTH ends have to exist before the line between them does. Gating on
        # the target alone drew an arrow emerging from empty space, which
        # happens whenever the script names a child before its parent — and
        # the reveal follows the narration, not the flowchart.
        src = elements[el.edge_from]
        e = ease(t, max(el.at, src.at), 0.5)
        if e <= 0.0:
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

        # The badge occupies the top of the card, so only a badged card owes
        # the text any offset. A fixed -0.16 pushed every label off centre,
        # including on the branching diagrams that have no badge at all.
        head_room = 0.62 if chain else 0.0
        body, fs = fit_label(ax, el.label, bw, bh - head_room,
                             15.0 if len(boxes) <= 4 else 13.0)
        ax.text(bx + bw / 2, by + (bh - head_room) / 2,
                body, fontsize=fs, fontweight="bold", color=INK,
                ha="center", va="center", linespacing=1.3, zorder=8, alpha=e)


# Where terms sit; shared with gaze_track so the teacher looks at the term
# she is actually saying rather than at where it used to be drawn.
EQ_GAP, EQ_CX, EQ_CY = 2.3, 6.6, 4.95


def draw_equation(ax, t, elements) -> None:
    """Terms settle into place in ink; each arrival flashes its accent once,
    so colour marks what is new without the finished equation looking like a
    row of unrelated symbols."""
    ops = ("=", "+", "-", "\\times", "\\cdot")
    gap, cx, cy = EQ_GAP, EQ_CX, EQ_CY
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


def still(out: Path, kind: str, payload: str, caption: str,
          width: int = W, height: int = H) -> Path:
    """One finished board, as a PNG.

    Voice mode needs a picture while the sentence is still being spoken, so
    it cannot wait on a video. This is the same parse and the same layout the
    lesson videos use -- the label-blanking fix, the serpentine grid, the
    fitted text -- drawn once with every element already revealed. The
    separate still renderer in the media pipeline mis-reads chained mermaid
    arrows (`A --> B --> C`) and splits node labels down the middle, which is
    what "B[Split H2O" and "Glucose]" boxes are.
    """
    setup_fonts()
    elements = (parse_equation(payload) if kind == "equation"
                else parse_diagram(payload))
    for el in elements:
        el.at = 0.0                       # everything already on the board

    fig = plt.figure(figsize=(width / DPI, height / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(PAPER)
    try:
        ax.clear()
        ax.set_xlim(0, 16)
        ax.set_ylim(0, 9)
        ax.axis("off")
        t = 10.0                          # past every reveal
        if kind == "equation" and elements:
            title_bar(ax, t, caption)
            draw_equation(ax, t, elements)
        elif elements:
            title_bar(ax, t, caption)
            draw_flow(ax, t, elements)
        else:
            draw_fallback(ax, t, caption)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=DPI, facecolor=PAPER)
    finally:
        plt.close(fig)
    return out


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

        # Inside the temp directory, not after it. Splitting build() from
        # encode() left this dedented, so the narration was deleted before the
        # mux could read it and the CLI could not render anything at all.
        return encode(out, elements, kind, caption, narration)


# The teacher stands here, in the corner make_visual reserves for her.
AVATAR_X, AVATAR_Y, AVATAR_W = 12.9, 0.0, 2.95

# Her head within that box: the SVG puts the face at (200, 220) of a 400x460
# view, and draw_avatar scales by AVATAR_W/400 and flips y.
HEAD_X = AVATAR_X + AVATAR_W * 0.50
HEAD_Y = AVATAR_Y + AVATAR_W * 0.60


def _avatar_module():
    """Load the sibling avatar renderer, fresh whenever its file has changed.

    board_media.py deliberately re-execs THIS file on every render so a
    long-running server picks up edits without a restart. A plain
    `import avatar_render` in here got no such treatment: sys.modules hands
    back whatever the process imported first. So a server that had already
    rendered one segment ran NEW board code against a STALE avatar module,
    and the moment analyse() grew its gaze argument the call raised
    TypeError -- caught by encode(), which degrades to the board alone. The
    video came out correct in every respect except that the teacher was
    simply missing, with the reason on a stderr line nobody reads. Keying on
    the file's mtime keeps the two halves of the pair in step.
    """
    path = Path(__file__).resolve().parent / "avatar_render.py"
    stamp = path.stat().st_mtime_ns
    mod = sys.modules.get("avatar_render")
    if mod is not None and getattr(mod, "_loaded_at", None) == stamp:
        return mod
    spec = importlib.util.spec_from_file_location("avatar_render", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["avatar_render"] = mod        # before exec, for @dataclass
    spec.loader.exec_module(mod)
    mod._loaded_at = stamp
    return mod


def gaze_track(elements, kind) -> list[tuple[float, float, float]]:
    """(time, x, y) look-at targets, one per element, as the board reveals it.

    x and y are head-relative and roughly -1..1. Everything on the board is to
    her left, so x stays negative throughout -- that is honest, and the spread
    between a near column and a far one is still wide enough to read as a
    change of direction.
    """
    if not elements:
        return []
    if kind == "equation":
        first = EQ_CX - EQ_GAP * (len(elements) - 1) / 2
        centres = [(first + EQ_GAP * i, EQ_CY) for i in range(len(elements))]
    else:
        boxes = grid(len(elements)) if _is_chain(elements) else layered(elements)
        centres = [(bx + bw / 2, by + bh / 2) for bx, by, bw, bh in boxes]
    clamp = lambda v: max(-1.0, min(1.0, v))
    return [(el.at, clamp((x - HEAD_X) / 13.0), clamp((y - HEAD_Y) / 5.0))
            for el, (x, y) in zip(elements, centres)]


def _wav_for(audio: Path, ffmpeg: str, work: Path) -> Path:
    """A WAV to analyse. build() narrates to MP3; the pipeline hands us WAV."""
    if str(audio).lower().endswith(".wav"):
        return Path(audio)
    out = work / "for_analysis.wav"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(audio),
                    "-ac", "1", "-ar", "22050", str(out)],
                   check=True, timeout=120)
    return out


def encode(out: Path, elements: list[Element], kind: str, caption: str,
           narration: Narration, variant: str | None = None,
           teacher: str | None = None) -> int:
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

    # The teacher is drawn INTO the frames, not layered over the <video> in
    # HTML. An overlay vanishes the moment anyone fullscreens the video, and
    # it cannot survive download or upload either. Burnt in, she is simply
    # part of the picture. Failing to build her must not cost us the board,
    # so anything here degrades to the board alone.
    poses = shapes_ = None
    palette = {}
    try:
        avatar_render = _avatar_module()
        shapes_ = avatar_render.shapes()
        who = avatar_render.teacher(teacher_id) if teacher_id else None
        if who:
            variant = who.get("variant") or variant
        palette = (who or {}).get("palette") or {}
        wav = _wav_for(Path(narration.audio), ffmpeg, out.parent)
        poses = avatar_render.analyse(wav, FPS, int(total * FPS),
                                      gaze=gaze_track(elements, kind))
    except Exception as exc:
        # Loud, not just logged: a board with no teacher on it is the whole
        # point of the product going quietly missing, and the previous
        # single stderr line went unread through an entire session of it.
        print(f"[avatar] NOT EMBEDDED -- {type(exc).__name__}: {exc}",
              file=sys.stderr)
        import traceback
        traceback.print_exc()
    # Caller's choice wins; the environment stays as the CLI's way in. This
    # used to read the environment only, so "male teacher" in the UI could not
    # reach the renderer -- and setting it per render from a request thread
    # would have raced, since os.environ is process-wide.
    if variant not in ("f", "m"):
        variant = os.environ.get("MENTORA_AVATAR_VARIANT", "f")
    if variant not in ("f", "m"):
        variant = "f"
    teacher_id = teacher or os.environ.get("MENTORA_TEACHER") or ""

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
                if poses:
                    avatar_render.draw_avatar(
                        ax, shapes_, poses[min(f, len(poses) - 1)],
                        AVATAR_X, AVATAR_Y, AVATAR_W, variant,
                        palette=palette)
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
