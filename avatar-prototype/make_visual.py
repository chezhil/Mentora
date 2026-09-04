"""Render an animated teaching visual to lesson.mp4, with matplotlib.

    python make_visual.py            # Ohm's Law, the default
    python make_visual.py --seconds 12

WHY THIS EXISTS

Mentora's teaching visuals are already drawn with matplotlib rather than an
image model, which is the right call: a generative model gets equations and
labels subtly wrong and a student cannot tell. But they are rendered ONCE per
segment and then held motionless for the whole of the narration, so the
"teaching video" is a slideshow with a talking head in the corner.

Nothing here is new drawing technology. It is the same matplotlib, with the
reveal driven by time: each element appears when the teacher would be talking
about it. That is the difference between a diagram and an explanation.

This is a prototype: the schedule below is hand-written for one topic. In the
real pipeline the beats would come from the segment script, so the diagram
builds in step with what is being said.

Self-contained — it imports nothing from the rest of the repo.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FFMpegWriter
from matplotlib.patches import FancyBboxPatch, Rectangle

# Mentora's palette, so the visual and the app are obviously the same product.
PAPER, INK = "#F5F1E8", "#12100E"
YELLOW, BLUE, CORAL, TEAL = "#FFD400", "#4A7DFF", "#FF6B4A", "#12A594"
MUTED = "#6B6459"

W, H, DPI, FPS = 1280, 720, 100, 25

# The teacher stands in the bottom-right of the frame, so nothing that carries
# meaning may be drawn there. In the 16x9 units this file works in, the avatar
# occupies roughly x > 13.1 and y < 3.3. Losing the tail of a curve or the one
# line that states the result behind a talking head is the failure this reserve
# exists to prevent — and it is exactly what the ffmpeg composite does today,
# where the avatar covers the subject label in the corner of every segment.
AVATAR_SAFE_X, AVATAR_SAFE_Y = 13.1, 3.3


def ease(t: float, start: float, dur: float) -> float:
    """0 before `start`, 1 after, eased-out cubic between.

    Everything on screen is a function of this. Linear fades read as a
    slideshow transition; an ease-out arrives quickly and settles, which is
    how a hand-drawn annotation lands.
    """
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    x = (t - start) / dur
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    return 1 - (1 - x) ** 3


def card(ax, x, y, w, h, face, z=2, lw=3):
    """A flat panel with a hard offset shadow — the house style."""
    ax.add_patch(Rectangle((x + 0.06, y - 0.06), w, h, facecolor=INK,
                           edgecolor="none", zorder=z))
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="square,pad=0",
                                facecolor=face, edgecolor=INK, linewidth=lw,
                                zorder=z + 1))


def draw(ax, t: float, total: float) -> None:
    ax.clear()
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis("off")
    ax.set_facecolor(PAPER)

    # --- title bar, always present -----------------------------------------
    a = ease(t, 0.0, 0.6)
    card(ax, 0.4, 7.6, 15.2 * a, 1.1, YELLOW, z=2)
    if a > 0.55:
        ax.text(0.8, 8.15, "Ohm's Law", fontsize=34, fontweight="bold",
                color=INK, va="center", zorder=5,
                alpha=min(1.0, (a - 0.55) / 0.45))

    # --- the three quantities, appearing one at a time ---------------------
    labels = [("Voltage", "V", "volts", BLUE), ("Current", "I", "amps", CORAL),
              ("Resistance", "R", "ohms", TEAL)]
    for i, (name, sym, unit, colour) in enumerate(labels):
        a = ease(t, 1.0 + i * 0.9, 0.5)
        if a <= 0:
            continue
        x = 0.45 + i * 2.5
        # Slide up into place as it appears.
        y = 5.9 - (1 - a) * 0.5
        card(ax, x, y, 2.3, 1.4, colour, z=4)
        ax.text(x + 0.3, y + 0.88, sym, fontsize=26, fontweight="bold",
                color=INK, alpha=a, zorder=7)
        ax.text(x + 0.92, y + 0.92, name, fontsize=11, fontweight="bold",
                color=INK, alpha=a, zorder=7)
        ax.text(x + 0.92, y + 0.45, unit, fontsize=10, color=INK, alpha=a * .75,
                zorder=7)

    # --- the equation, built term by term ----------------------------------
    terms = [("V", BLUE, 0.0), ("=", None, 0.45), ("I", CORAL, 0.9),
             ("x", None, 1.35), ("R", TEAL, 1.8)]
    base = 4.6
    eq_y = 4.3
    for sym, colour, delay in terms:
        a = ease(t, base + delay, 0.35)
        if a <= 0:
            continue
        i = [s for s, _, _ in terms].index(sym)
        x = 1.1 + i * 1.35
        glyph = "×" if sym == "x" else sym
        ax.text(x, eq_y, glyph, fontsize=52, fontweight="bold",
                color=colour or INK, alpha=a, ha="center", va="center",
                zorder=6)

    # A pulse under the equation once it is complete, so the eye returns to it.
    if t > base + 2.4:
        pulse = 0.35 + 0.25 * math.sin((t - base - 2.4) * 3.0)
        ax.plot([0.8, 6.4], [3.35, 3.35], color=YELLOW, linewidth=9,
                alpha=pulse, solid_capstyle="round", zorder=3)

    # --- the graph, drawn as it is explained -------------------------------
    gx0, gy0, gw, gh = 8.1, 3.5, 7.3, 3.8
    a = ease(t, 7.2, 0.6)
    if a > 0:
        card(ax, gx0, gy0, gw, gh, "#FFFFFF", z=4)
        ax.text(gx0 + 0.3, gy0 + gh - 0.45,
                "Fix V. Raise R, and I falls.", fontsize=15,
                fontweight="bold", color=INK, alpha=a, zorder=7)

        ox, oy = gx0 + 0.95, gy0 + 1.0
        aw, ah = gw - 1.7, gh - 1.9
        axis = ease(t, 7.8, 0.5)
        ax.plot([ox, ox + aw * axis], [oy, oy], color=INK, lw=2.5, zorder=7)
        ax.plot([ox, ox], [oy, oy + ah * axis], color=INK, lw=2.5, zorder=7)
        if axis > 0.9:
            ax.text(ox + aw / 2, oy - 0.42, "Resistance  R", fontsize=13,
                    fontweight="bold", color=MUTED, ha="center", zorder=7)
            ax.text(ox - 0.45, oy + ah / 2, "Current  I", fontsize=13,
                    fontweight="bold", color=MUTED, rotation=90,
                    va="center", zorder=7)

        # I = V/R, drawn left to right rather than appearing whole.
        grow = ease(t, 8.6, 3.4)
        if grow > 0:
            r = np.linspace(1.0, 10.0, 400)
            i_curve = 12.0 / r
            n = max(2, int(len(r) * grow))
            px = ox + (r[:n] - 1) / 9 * aw
            py = oy + (i_curve[:n] - 1.2) / 10.8 * ah
            ax.plot(px, py, color=CORAL, lw=5, solid_capstyle="round",
                    zorder=8)
            ax.fill_between(px, py, oy, color=CORAL, alpha=0.10, zorder=7)
            # The dot is the reading head: it is where the explanation is.
            ax.plot([px[-1]], [py[-1]], "o", ms=13, color=CORAL,
                    markeredgecolor=INK, markeredgewidth=2.5, zorder=9)

        # --- the actual point of the lesson, called out on the curve -------
        show = ease(t, 12.4, 0.7)
        if show > 0:
            for r_at, colour in ((2.0, INK), (4.0, INK)):
                i_at = 12.0 / r_at
                mx = ox + (r_at - 1) / 9 * aw
                my = oy + (i_at - 1.2) / 10.8 * ah
                ax.plot([mx, mx], [oy, my], "--", color=colour, lw=2,
                        alpha=show * 0.55, zorder=8)
                ax.plot([mx], [my], "o", ms=11, color=YELLOW,
                        markeredgecolor=INK, markeredgewidth=2.5,
                        alpha=show, zorder=9)
            ax.text(gx0 + gw / 2, gy0 + 0.35,
                    "R doubles  →  I halves", fontsize=16,
                    fontweight="bold", color=INK, ha="center", alpha=show,
                    zorder=9)

    # --- closing recap ------------------------------------------------------
    out = ease(t, total - 2.6, 0.7)
    if out > 0:
        ax.add_patch(Rectangle((0, 0), 16, 9, facecolor=PAPER,
                               alpha=out * 0.93, zorder=20))
        ax.text(8, 5.0, "V = I × R", fontsize=64, fontweight="bold",
                color=INK, ha="center", va="center", alpha=out, zorder=21)
        ax.text(8, 3.7, "Voltage is current times resistance.", fontsize=20,
                color=MUTED, ha="center", va="center", alpha=out, zorder=21)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=17.0)
    ap.add_argument("--out", default="lesson.mp4")
    args = ap.parse_args()

    # imageio-ffmpeg ships the binary; there is no system ffmpeg on this repo's
    # machines and matplotlib will not look for one on its own.
    try:
        import imageio_ffmpeg
        matplotlib.rcParams["animation.ffmpeg_path"] = \
            imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])

    frames = int(args.seconds * FPS)
    writer = FFMpegWriter(fps=FPS, bitrate=2400,
                          extra_args=["-pix_fmt", "yuv420p"])
    out = Path(args.out)
    with writer.saving(fig, str(out), DPI):
        for f in range(frames):
            draw(ax, f / FPS, args.seconds)
            writer.grab_frame(facecolor=PAPER)
    plt.close(fig)

    print(f"{out}  {out.stat().st_size / 1024:.0f} KB  "
          f"{args.seconds:g}s  {W}x{H}@{FPS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
