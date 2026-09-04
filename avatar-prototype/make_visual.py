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
from matplotlib.patches import Circle, FancyBboxPatch

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
    """A rounded rectangle; rounding is clamped to the half-dimensions."""
    r = max(0.0, min(r, w / 2, h / 2))
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r:.3f}",
        facecolor=face, edgecolor=edge if edge else "none",
        linewidth=lw, zorder=z, alpha=alpha))


def draw(ax, t: float, total: float) -> None:
    ax.clear()
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis("off")
    ax.set_facecolor(PAPER)

    # --- header: ink type beside a yellow tick, always present ------------
    a = ease(t, 0.0, 0.45)
    if a > 0:
        rrect(ax, 0.62, 7.66, 0.30, 0.98, 0.15, face=YELLOW, z=6, alpha=a)
        ax.text(1.18, 8.15, "Ohm's Law", fontsize=30, fontweight="bold",
                color=INK, va="center", zorder=8, alpha=a)

    # --- the three quantities, appearing one at a time ---------------------
    # One pale tinted chip per quantity, each carrying an accent medallion
    # with the symbol -- colour labels the quantity, not the chrome.
    quantities = [("V", "Voltage", "volts", BLUE),
                  ("I", "Current", "amps", CORAL),
                  ("R", "Resistance", "ohms", TEAL)]
    for i, (sym, name, unit, accent) in enumerate(quantities):
        a = ease(t, 1.0 + i * 0.9, 0.5)
        if a <= 0:
            continue
        x = 0.45 + i * 2.5
        y = 5.95 - (1 - a) * 0.45
        w, h = 2.4, 1.5
        rrect(ax, x + 0.09, y - 0.11, w, h, 0.18, face=INK, z=4,
              alpha=0.09 * a)
        rrect(ax, x, y, w, h, 0.18, face=mix("#FFFFFF", accent, 0.10), z=5,
              alpha=a)
        rrect(ax, x, y, w, h, 0.18, edge=INK, lw=1.2, z=6, alpha=0.12 * a)
        mx, my = x + 0.55, y + h / 2
        ax.add_patch(Circle((mx, my), 0.34, facecolor=accent,
                            edgecolor="none", zorder=7))
        ax.text(mx, my, sym, fontsize=16, fontweight="bold", color="#FFFFFF",
                ha="center", va="center", zorder=8)
        ax.text(x + 1.02, my + 0.28, name, fontsize=12.5, fontweight="bold",
                color=INK, va="center", zorder=8)
        ax.text(x + 1.02, my - 0.28, unit, fontsize=10.5, color=MUTED,
                va="center", zorder=8)

    # --- the equation, built term by term ----------------------------------
    # Terms arrive in ink; each flashes its accent for the instant it lands.
    terms = [("V", BLUE, 0.0), ("=", None, 0.45), ("I", CORAL, 0.9),
             ("x", None, 1.35), ("R", TEAL, 1.8)]
    base = 4.6
    eq_y = 4.3
    for sym, accent, delay in terms:
        a = ease(t, base + delay, 0.35)
        if a <= 0:
            continue
        i = [s for s, _, _ in terms].index(sym)
        x = 1.1 + i * 1.35
        glyph = "×" if sym == "x" else sym
        colour = INK if accent is None else mix(accent, INK, a)
        ax.text(x, eq_y, glyph, fontsize=52, fontweight="bold",
                color=colour, alpha=a, ha="center", va="center", zorder=6)

    # A soft yellow rule settles beneath the equation once it is complete --
    # one pop of emphasis, then it stays.
    if t > 7.0:
        since = t - 7.0
        alpha = 0.60 * ease(since, 0.0, 0.6) + \
            0.30 * max(0.0, math.sin(since * 4.2)) * math.exp(-since * 2.0)
        if alpha > 0.01:
            rrect(ax, 0.75, 3.32, 6.0, 0.16, 0.08, face=YELLOW, z=6,
                  alpha=min(alpha, 0.9))

    # --- the graph, drawn as it is explained -------------------------------
    gx0, gy0, gw, gh = 8.1, 3.5, 7.3, 3.8
    a = ease(t, 7.2, 0.6)
    if a > 0:
        rrect(ax, gx0 + 0.09, gy0 - 0.11, gw, gh, 0.22, face=INK, z=4,
              alpha=0.09 * a)
        rrect(ax, gx0, gy0, gw, gh, 0.22, face="#FFFFFF", z=5, alpha=a)
        rrect(ax, gx0, gy0, gw, gh, 0.22, edge=INK, lw=1.2, z=6,
              alpha=0.14 * a)
        ax.text(gx0 + 0.35, gy0 + gh - 0.42, "Fix V. Raise R, and I falls.",
                fontsize=15.5, fontweight="bold", color=INK, alpha=a, zorder=7)

        ox, oy = gx0 + 0.95, gy0 + 1.05
        aw, ah = gw - 1.8, gh - 2.0
        axis = ease(t, 7.8, 0.5)
        ax.plot([ox, ox + aw * axis], [oy, oy], color=INK, lw=2.2,
                solid_capstyle="round", zorder=7)
        ax.plot([ox, ox], [oy, oy + ah * axis], color=INK, lw=2.2,
                solid_capstyle="round", zorder=7)
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
            ax.plot(px, py, color=CORAL, lw=4.5, solid_capstyle="round",
                    zorder=8)
            ax.fill_between(px, py, oy, color=CORAL, alpha=0.08, zorder=7)
            # The dot is the reading head: it is where the explanation is.
            ax.plot([px[-1]], [py[-1]], "o", ms=12, color=CORAL,
                    markeredgecolor=INK, markeredgewidth=2.2, zorder=9)

        # --- the actual point of the lesson, called out on the curve -------
        show = ease(t, 12.4, 0.7)
        if show > 0:
            for r_at in (2.0, 4.0):
                i_at = 12.0 / r_at
                mx = ox + (r_at - 1) / 9 * aw
                my = oy + (i_at - 1.2) / 10.8 * ah
                ax.plot([mx, mx], [oy, my], "--", color=INK, lw=1.8,
                        alpha=show * 0.5, zorder=8)
                ax.plot([mx], [my], "o", ms=10, color=YELLOW,
                        markeredgecolor=INK, markeredgewidth=2.2,
                        alpha=show, zorder=9)
            ax.text(gx0 + gw / 2, gy0 + 0.42, "R doubles  →  I halves",
                    fontsize=16.5, fontweight="bold", color=INK, ha="center",
                    alpha=show, zorder=9)

    # --- closing recap: a card, not a fade-to-paper wash -------------------
    out = ease(t, total - 2.6, 0.7)
    if out > 0:
        w, h = 11.4, 3.1
        x, y = 8 - w / 2, 3.45
        rrect(ax, x + 0.12, y - 0.14, w, h, 0.30, face=INK, z=20,
              alpha=0.10 * out)
        rrect(ax, x, y, w, h, 0.30, face="#FFFFFF", z=21, alpha=out)
        rrect(ax, x, y, w, h, 0.30, edge=INK, lw=1.4, z=22, alpha=0.18 * out)
        ax.text(8, y + h / 2 + 0.62, "V = I × R", fontsize=58,
                fontweight="bold", color=INK, ha="center", va="center",
                alpha=out, zorder=23)
        ax.text(8, y + h / 2 - 0.55, "Voltage is current times resistance.",
                fontsize=19, color=MUTED, ha="center", va="center",
                alpha=out, zorder=23)

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
