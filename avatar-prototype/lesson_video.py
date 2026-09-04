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
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

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
# ---------------------------------------------------------------------------

def ease(t: float, start: float, dur: float = 0.45) -> float:
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    x = (t - start) / dur
    return 0.0 if x <= 0 else 1.0 if x >= 1 else 1 - (1 - x) ** 3


def card(ax, x, y, w, h, face, z=2, lw=3):
    ax.add_patch(Rectangle((x + 0.06, y - 0.06), w, h, facecolor=INK,
                           edgecolor="none", zorder=z))
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="square,pad=0",
                                facecolor=face, edgecolor=INK, linewidth=lw,
                                zorder=z + 1))


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
    which is the opposite of the direction the lesson is going.
    """
    if n <= 0:
        return []
    cols = min(n, 4) if n <= 4 else 3
    rows = (n + cols - 1) // cols
    x0, y0, x1, y1 = 0.7, 1.5, 12.5, 7.1          # x1 < SAFE_X
    cw, ch = (x1 - x0) / cols, (y1 - y0) / rows
    # Cap the height: a single row filling the whole band gave boxes four
    # units tall holding one line of text, which reads as columns rather than
    # as steps in a flow. Centre whatever is left in the cell.
    bh = min(ch * 0.72, 2.5)
    boxes = []
    for i in range(n):
        r, c = divmod(i, cols)
        bx = x0 + c * cw + cw * 0.06
        by = y1 - (r + 1) * ch + (ch - bh) / 2
        boxes.append((bx, by, cw * 0.88, bh))
    return boxes


def mathtext(term: str) -> str:
    return f"${term}$" if term not in ("=", "+", "-") else term


def draw(ax, t, elements, kind, caption, sentences, total):
    ax.clear()
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis("off")

    # --- title bar ---------------------------------------------------------
    a = ease(t, 0.0, 0.5)
    card(ax, 0.4, 7.5, 15.2 * a, 1.15, YELLOW, z=2)
    if a > 0.5:
        ax.text(0.8, 8.08, wrap(caption, 58).split("\n")[0], fontsize=27,
                fontweight="bold", color=INK, va="center", zorder=6,
                alpha=(a - 0.5) / 0.5)

    if kind == "equation":
        # Centre the terms with a fixed gap rather than spreading them across
        # the whole frame: three terms distributed over eleven units left the
        # equation reading as three unrelated symbols.
        gap, cx, y = 2.3, 6.4, 4.9
        first = cx - gap * (len(elements) - 1) / 2
        for i, el in enumerate(elements):
            e = ease(t, el.at)
            if e <= 0:
                continue
            x = first + gap * i
            colour = INK if el.label in ("=", "+", "-", "\\times", "\\cdot") \
                else ACCENTS[i % len(ACCENTS)]
            try:
                ax.text(x, y - (1 - e) * 0.35, mathtext(el.label), fontsize=54,
                        fontweight="bold", color=colour, ha="center",
                        va="center", alpha=e, zorder=6)
            except Exception:
                ax.text(x, y, el.label, fontsize=40, color=colour,
                        ha="center", va="center", alpha=e, zorder=6)
        if elements and t > elements[-1].at + 0.5:
            pulse = 0.30 + 0.22 * np.sin((t - elements[-1].at - 0.5) * 3.0)
            ax.plot([first - 1.0, first + gap * (len(elements) - 1) + 1.0],
                    [3.6, 3.6], color=YELLOW, lw=9,
                    alpha=pulse, solid_capstyle="round", zorder=3)
    else:
        boxes = grid(len(elements))
        for i, (el, (bx, by, bw, bh)) in enumerate(zip(elements, boxes)):
            e = ease(t, el.at)
            if e <= 0:
                continue
            # The arrow that reaches this node is drawn with it, so the
            # connection appears as the relationship is described.
            if el.edge_from is not None and el.edge_from < len(boxes):
                tail, head = anchors(boxes[el.edge_from], (bx, by, bw, bh))
                ax.add_patch(FancyArrowPatch(
                    tail, head, arrowstyle="-|>", mutation_scale=22,
                    color=INK, lw=2.6, alpha=e * 0.9,
                    shrinkA=3, shrinkB=3, zorder=9))
            card(ax, bx, by - (1 - e) * 0.3, bw, bh,
                 ACCENTS[i % len(ACCENTS)], z=5)
            ax.text(bx + bw / 2, by + bh / 2 - (1 - e) * 0.3,
                    wrap(el.label, max(11, int(bw * 5.2))),
                    fontsize=15 if len(boxes) <= 3 else 12,
                    fontweight="bold", color=INK, ha="center", va="center",
                    alpha=e, zorder=8)

        if not elements:
            # Junk payload — one cached segment's is literally a .png filename.
            # Say what is being taught rather than drawing an apology.
            ax.text(6.5, 4.6, wrap(caption, 34), fontsize=30,
                    fontweight="bold", color=INK, ha="center", va="center",
                    alpha=ease(t, 0.6), zorder=6)

    # --- the sentence being spoken, as it is spoken ------------------------
    live = next((s for s in sentences if s.start <= t < s.end), None)
    if live:
        text = "\n".join(wrap(live.text.strip(), 72).split("\n")[:2])
        card(ax, 0.4, 0.2, 12.4, 1.1, "#FFFFFF", z=10, lw=2.5)
        ax.text(0.7, 0.75, text, fontsize=14, color=INK, va="center",
                linespacing=1.35, zorder=13)

    # --- narration progress ------------------------------------------------
    if total > 0:
        ax.add_patch(Rectangle((0, 8.93), 16 * min(t / total, 1.0), 0.07,
                               facecolor=CORAL, edgecolor="none", zorder=15))


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

        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            matplotlib.rcParams["animation.ffmpeg_path"] = ffmpeg
        except Exception:
            ffmpeg = "ffmpeg"

        silent = work / "silent.mp4"
        fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=PAPER)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor(PAPER)
        writer = FFMpegWriter(fps=FPS, bitrate=2600,
                              extra_args=["-pix_fmt", "yuv420p"])
        with writer.saving(fig, str(silent), DPI):
            for f in range(int(total * FPS)):
                draw(ax, f / FPS, elements, kind, caption,
                     narration.sentences, total)
                writer.grab_frame(facecolor=PAPER)
        plt.close(fig)

        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(silent),
             "-i", str(narration.audio), "-c:v", "copy", "-c:a", "aac",
             "-shortest", "-movflags", "+faststart", str(out)],
            check=True, timeout=300)

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
