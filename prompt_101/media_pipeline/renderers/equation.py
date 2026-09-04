"""Equation renderer — the formula, set large, with its derivation under it.

The teacher's payload for this kind is LaTeX, and the old renderer drew it as
plain text. So a student asked to learn Ohm's law was shown the string

    V = I \\times R \\quad \\text{(volts)}

backslashes and all. matplotlib has mathtext built in, which renders a useful
subset of LaTeX with no TeX installation, so the maths is now typeset. When a
payload uses something mathtext cannot parse the raw source is shown instead,
tidied of its backslashes — wrong-looking is better than blank.
"""

from __future__ import annotations

import re

import matplotlib
matplotlib.use("Agg")

from . import register, save_figure
from . import design

# mathtext understands $...$ and most of the maths commands, but none of the
# text-mode ones. Strip the wrappers rather than fail on them.
_STRIP = [
    (re.compile(r"\\(?:text|mathrm|mathbf|textbf|mbox)\s*\{([^{}]*)\}"), r"\\mathrm{\1}"),
    (re.compile(r"\\(?:begin|end)\{[^}]*\}"), ""),
    (re.compile(r"\\(?:quad|qquad|,|;|!)"), " "),
    (re.compile(r"\\\\"), "\n"),
    (re.compile(r"\$+"), ""),
]


# A sentence is not an equation. mathtext drops every space it is given, so
# "Voltage in volts, current in amps" typeset as maths came out as
# "Voltageinvolts,currentinamps". Three or more ordinary words means prose.
_WORDS = re.compile(r"[A-Za-z]{3,}")


def _looks_like_prose(text: str) -> bool:
    if "\\" in text or "^" in text or "_" in text:
        return False
    return len(_WORDS.findall(text)) >= 3


def _as_mathtext(raw: str) -> tuple[str, bool]:
    """(string to draw, whether it is maths). Never raises."""
    text = str(raw).strip()
    if not text:
        return "", False
    if _looks_like_prose(text):
        return text, False
    for pattern, repl in _STRIP:
        text = pattern.sub(repl, text)
    text = text.strip()
    if not text:
        return "", False

    candidate = f"${text}$"
    try:
        from matplotlib import mathtext
        mathtext.MathTextParser("path").parse(candidate)
        return candidate, True
    except Exception:
        # Not parseable as maths. Show the source with its backslashes taken
        # out, which is at least readable.
        return re.sub(r"\\([A-Za-z]+)", r"\1", text), False


@register("equation")
def render_equation(content: str, subject: str, data: dict) -> str:
    """Render the equation large, with any derivation steps beneath it.

    Data options:
      data["steps"]  ordered derivation or explanation lines
      data["title"]  heading; defaults to "Equation"
    """
    lines = [l for l in str(content).split("\n") if l.strip()] or [str(content)]
    main_raw = lines[0]
    steps = [str(s) for s in (data.get("steps") or [])] + lines[1:]

    title = str(data.get("title") or "").strip()
    fig, ax, area = design.canvas(title or "Equation", subject, accent_index=0)
    left, bottom, right, top = area
    cx = (left + right) / 2

    main, is_maths = _as_mathtext(main_raw)
    if not main:
        design.empty(ax, area, "No equation given",
                     "the teacher's payload was empty")
        return save_figure(fig, "equation")

    # The equation sits in a plate of its own: white, keylined, hard shadow.
    # Long formulas get smaller type rather than a wider plate, because the
    # plate is what makes it read as "the thing to remember".
    length = len(re.sub(r"[${}\\]", "", main))
    size = 60 if length < 16 else 46 if length < 28 else 34 if length < 46 else 26

    plate_y = top - 20 if steps else (top + bottom) / 2
    ax.text(cx, plate_y, main, fontsize=size, fontweight="bold",
            color=design.INK, ha="center", va="center", zorder=6,
            math_fontfamily="dejavusans" if is_maths else None,
            bbox=dict(boxstyle="square,pad=0.55", facecolor="#FFFFFF",
                      edgecolor=design.INK, linewidth=design.BORDER + 0.6))

    if not steps:
        return save_figure(fig, "equation")

    # Steps below, numbered, each on its own keyline so the eye can step down
    # them one at a time.
    room = plate_y - 10 - bottom
    shown = steps[:5]
    pitch = min(11.0, room / max(len(shown), 1))
    step_size = 19 if pitch > 9 else 16
    y = plate_y - 13

    for i, step in enumerate(shown):
        drawn, maths = _as_mathtext(step)
        if not drawn:
            continue
        ax.text(left + 3, y, f"{i + 1}", fontsize=step_size, fontweight="bold",
                color=design.INK, ha="center", va="center", zorder=7,
                bbox=dict(boxstyle="circle,pad=0.32",
                          facecolor=design.accent(i + 1)[0],
                          edgecolor=design.INK, linewidth=2.0))
        # Never truncate maths: cutting inside $...$ unbalances the delimiters
        # and mathtext then renders the whole line as literal source.
        shown_text = drawn if maths else design._shorten(drawn, 64)
        ax.text(left + 9, y, shown_text, fontsize=step_size,
                color=design.INK, ha="left", va="center", zorder=7,
                math_fontfamily="dejavusans" if maths else None)
        y -= pitch

    return save_figure(fig, "equation")
