"""Draw the 2D teacher INTO a matplotlib frame, driven by the narration WAV.

The avatar used to be an HTML layer sitting on top of a <video>. That works
until someone fullscreens the video, at which point the browser shows the
video element alone and the teacher disappears. Burning her into the frames
means she is part of the picture — fullscreen, scrub, download, upload to
YouTube, she is still there.

TWO HALVES, both ports of the browser prototype:

  shapes()   reads the SVG character out of index.html so the artwork has ONE
             source of truth. The paths use only M, l, q and z, which map
             exactly onto matplotlib's MOVETO / LINETO / CURVE3 / CLOSEPOLY.

  Driver     the same amplitude analysis as driver.js — adaptive loudness,
             asymmetric attack/release, a response curve, spectral tilt for
             mouth shape, plus procedural blink and head drift. The tuning
             numbers are copied across deliberately; if you change one, change
             it in both or the browser and the video stop matching.
"""

from __future__ import annotations

import math
import re
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.transforms import Affine2D

_HTML = Path(__file__).resolve().parent / "index.html"

VIEW_W, VIEW_H = 400.0, 460.0

# Mirrors PARALLAX in character.js.
PARALLAX = {"f": dict(hairBack=4, head=10, hairFront=14, features=17),
            "m": dict(hairBack=9, head=10, hairFront=11, features=17)}
LIP_SEAM_GONE_AT = 0.18


# ---------------------------------------------------------------------------
# The artwork
# ---------------------------------------------------------------------------

@dataclass
class Shape:
    groups: tuple[str, ...]      # ancestor chain, outermost first
    path: MplPath
    fill: str | None
    stroke: str | None
    lw: float
    variant: str | None
    eid: str | None = None
    opacity: float = 1.0


_NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")


def _parse_d(d: str) -> MplPath:
    """SVG path -> matplotlib Path. Handles M, l, q, z only, which is all the
    character uses; anything else would silently distort the drawing, so it
    raises instead."""
    verts, codes = [], []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    for cmd, body in re.findall(r"([MLlQqZz])([^MLlQqZz]*)", d):
        nums = [float(n) for n in _NUM.findall(body)]
        if cmd == "M":
            cur = start = (nums[0], nums[1])
            verts.append(cur); codes.append(MplPath.MOVETO)
            for i in range(2, len(nums), 2):          # implicit lineto
                cur = (nums[i], nums[i + 1])
                verts.append(cur); codes.append(MplPath.LINETO)
        elif cmd in "Ll":
            for i in range(0, len(nums), 2):
                cur = ((nums[i], nums[i + 1]) if cmd == "L"
                       else (cur[0] + nums[i], cur[1] + nums[i + 1]))
                verts.append(cur); codes.append(MplPath.LINETO)
        elif cmd in "Qq":
            for i in range(0, len(nums), 4):
                if cmd == "Q":
                    c = (nums[i], nums[i + 1]); e = (nums[i + 2], nums[i + 3])
                else:
                    c = (cur[0] + nums[i], cur[1] + nums[i + 1])
                    e = (cur[0] + nums[i + 2], cur[1] + nums[i + 3])
                verts += [c, e]; codes += [MplPath.CURVE3, MplPath.CURVE3]
                cur = e
        elif cmd in "Zz":
            verts.append(start); codes.append(MplPath.CLOSEPOLY)
            cur = start
    return MplPath(verts, codes)


def _ellipse_path(cx, cy, rx, ry) -> MplPath:
    return MplPath.circle((0, 0), 1).transformed(
        Affine2D().scale(rx, ry).translate(cx, cy))


def _attr(tag: str, name: str, default=None):
    m = re.search(rf'\s{name}="([^"]*)"', tag)
    return m.group(1) if m else default


def shapes() -> list[Shape]:
    """Every drawable in the character, tagged with the group that moves it."""
    svg = re.search(r'<svg id="avatar".*?</svg>',
                    _HTML.read_text(encoding="utf-8"), re.S).group(0)
    out: list[Shape] = []
    stack: list[str] = []
    for tok in re.findall(r"<(/?)(g|path|ellipse|circle)([^>]*)>", svg):
        closing, tag, attrs = tok
        if tag == "g":
            if closing:
                if stack:
                    stack.pop()
            else:
                stack.append(_attr("<" + attrs + ">", "id") or (stack[-1] if stack else ""))
            continue
        blob = "<" + attrs + ">"
        cls = _attr(blob, "class") or ""
        variant = "f" if "v-f" in cls else "m" if "v-m" in cls else None
        chain = tuple(g for g in stack if g)
        fill = _attr(blob, "fill")
        stroke = _attr(blob, "stroke")
        lw = float(_attr(blob, "stroke-width", "0") or 0)
        opacity = float(_attr(blob, "opacity", "1") or 1)
        eid = _attr(blob, "id")
        if tag == "path":
            path = _parse_d(_attr(blob, "d", ""))
        elif tag == "ellipse":
            path = _ellipse_path(float(_attr(blob, "cx", 0)), float(_attr(blob, "cy", 0)),
                                 float(_attr(blob, "rx", 1)), float(_attr(blob, "ry", 1)))
        else:
            r = float(_attr(blob, "r", 1))
            path = _ellipse_path(float(_attr(blob, "cx", 0)), float(_attr(blob, "cy", 0)), r, r)
        if fill in (None, "none") and stroke in (None, "none"):
            continue
        if fill and fill.startswith("url("):
            continue                      # the blush gradient; skip, not draw wrong
        out.append(Shape(chain, path, None if fill == "none" else fill,
                         None if stroke == "none" else stroke, lw, variant,
                         eid, opacity))
    return out


# ---------------------------------------------------------------------------
# The driver, ported from driver.js. Keep these numbers in step with TUNING
# there, or the browser avatar and the burnt-in one stop matching.
# ---------------------------------------------------------------------------

GATE_DB, RANGE_DB, PEAK_DECAY, PEAK_FLOOR, PEAK_RISE = -55.0, 14.0, 12.0, -50.0, 0.5
OPEN_CURVE, ATTACK_MS, RELEASE_MS, FORM_SMOOTH_MS, FORM_GAIN = 2.2, 22.0, 110.0, 90.0, 5.0
LOW_BAND, HIGH_BAND = (120.0, 1000.0), (2200.0, 6500.0)
BLINK_MIN, BLINK_MAX, BLINK_MS = 2.2, 6.0, 0.13
WINDOW = 1024


def _drift(t: float, seed: float) -> float:
    return (math.sin(t * 0.31 + seed) * 0.55
            + math.sin(t * 0.73 + seed * 2.1) * 0.30
            + math.sin(t * 1.19 + seed * 3.7) * 0.15)


def _coef(ms: float, dt: float) -> float:
    return 1.0 - math.exp(-dt / (ms / 1000.0))


def analyse(wav_path, fps: int, frames: int, seed: int = 7) -> list[dict]:
    """Per-frame avatar parameters for a narration WAV."""
    with wave.open(str(wav_path)) as w:
        rate, n, width = w.getframerate(), w.getnframes(), w.getsampwidth()
        raw = np.frombuffer(w.readframes(n), dtype=np.int16 if width == 2 else np.uint8)
        if w.getnchannels() > 1:
            raw = raw.reshape(-1, w.getnchannels()).mean(axis=1)
    samples = raw.astype(np.float64) / 32768.0
    freqs = np.fft.rfftfreq(WINDOW, 1.0 / rate)
    low = (freqs >= LOW_BAND[0]) & (freqs <= LOW_BAND[1])
    high = (freqs >= HIGH_BAND[0]) & (freqs <= HIGH_BAND[1])

    dt = 1.0 / fps
    peak_db, mouth, form = -60.0, 0.0, 0.0
    energy, next_blink, blink_until = 0.0, 1.2, -1.0
    rng = np.random.default_rng(seed)
    out = []
    for i in range(frames):
        t = i * dt
        start = int(t * rate) - WINDOW // 2
        chunk = samples[max(start, 0):max(start, 0) + WINDOW]
        if chunk.size < WINDOW:
            chunk = np.pad(chunk, (0, WINDOW - chunk.size))

        rms = float(np.sqrt(np.mean(chunk ** 2)))
        db = 20.0 * math.log10(rms + 1e-9)
        decayed = max(peak_db - PEAK_DECAY * dt, PEAK_FLOOR)
        if db < GATE_DB:
            peak_db, level = decayed, 0.0
        else:
            peak_db = (peak_db + (db - peak_db) * PEAK_RISE
                       if db > peak_db else decayed)
            floor = peak_db - RANGE_DB
            level = min(max((db - floor) / max(peak_db - floor, 1e-6), 0.0), 1.0)

        spec = np.abs(np.fft.rfft(chunk * np.hanning(WINDOW)))
        lo, hi = float(spec[low].mean()), float(spec[high].mean())
        if lo + hi > 1e-9:
            form += (min(hi / (lo + hi) * FORM_GAIN, 1.0) - form) * _coef(FORM_SMOOTH_MS, dt)

        shaped = level ** OPEN_CURVE
        mouth += (shaped - mouth) * _coef(ATTACK_MS if shaped > mouth else RELEASE_MS, dt)
        energy += (level - energy) * _coef(400.0, dt)

        if t > next_blink and t > blink_until:
            blink_until = t + BLINK_MS
            next_blink = t + BLINK_MIN + float(rng.random()) * (BLINK_MAX - BLINK_MIN)
        if t < blink_until:
            phase = 1.0 - (blink_until - t) / BLINK_MS
            eye_open = 1.0 - phase / 0.4 if phase < 0.4 else (phase - 0.4) / 0.6
        else:
            eye_open = 1.0

        life = 0.35 + energy * 0.9
        out.append(dict(
            mouthOpen=mouth, mouthForm=form, eyeOpen=eye_open, eyeX=0.0, eyeY=0.0,
            angleX=_drift(t, 1.7) * 3.4 * life, angleY=_drift(t, 4.2) * 2.6 * life,
            angleZ=_drift(t, 8.9) * 2.8 * life,
            breath=(math.sin(t * 1.1) + 1.0) / 2.0, brow=energy * 0.7))
    return out


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _group_transform(chain, p, variant) -> Affine2D:
    """Compose the same per-group transforms character.js applies."""
    px = PARALLAX.get(variant, PARALLAX["f"])
    axn, ayn = p["angleX"] / 26.0, p["angleY"] / 18.0
    tr = Affine2D()
    for g in chain:
        if g == "root":
            tr = tr.rotate_deg_around(200, 300, p["angleZ"])
        elif g == "body":
            tr = tr.translate(0, (1 - p["breath"]) * 2.5)
        elif g == "hairBack":
            tr = tr.translate(axn * px["hairBack"], ayn * px["hairBack"] * 0.8)
        elif g == "hairFront":
            tr = tr.translate(axn * px["hairFront"], ayn * px["hairFront"] * 0.7)
        elif g == "head":
            sq = 1 - abs(axn) * 0.05
            tr = (tr.translate(axn * px["head"], ayn * px["head"] * 0.7)
                    .translate(200, 220).scale(sq, 1).translate(-200, -220))
        elif g == "features":
            tr = tr.translate(axn * px["features"], ayn * px["features"] * 0.65)
        elif g in ("eyeL", "eyeR"):
            cx = 158 if g == "eyeL" else 242
            lid = max(p["eyeOpen"], 0.02)
            tr = tr.translate(cx, 222).scale(1, lid).translate(-cx, -222)
        elif g in ("irisL", "irisR"):
            tr = tr.translate(p["eyeX"] * 7, p["eyeY"] * 5)
        elif g == "brows":
            tr = tr.translate(0, -p["brow"] * 5)
    return tr


def draw_avatar(ax, shapes_, p, x, y, width, variant="f", z=30) -> None:
    """Draw the character with its bottom-left at (x, y), `width` units wide.

    SVG is y-down and the board axes are y-up, so the base transform flips as
    well as scales.
    """
    s = width / VIEW_W
    base = Affine2D().scale(s, -s).translate(x, y + VIEW_H * s)
    lerp = lambda a, b, u: a + (b - a) * u
    rx = lerp(24.0, 13.0, p["mouthForm"])
    mouth = {
        "mouthCavity": _ellipse_path(200, 292, rx, 2 + p["mouthOpen"] * 24),
        "mouthTongue": _ellipse_path(200, 294 + p["mouthOpen"] * 7, rx * 0.62,
                                     max(0.0, p["mouthOpen"] * 11 - 2)),
    }
    seam = max(0.0, 1.0 - p["mouthOpen"] / LIP_SEAM_GONE_AT)

    for sh in shapes_:
        if sh.variant and sh.variant != variant:
            continue
        alpha = sh.opacity
        path = mouth.get(sh.eid, sh.path)
        if sh.eid == "mouthLine":
            alpha *= 0.8 * seam
        if sh.eid == "blush" or alpha <= 0.001:
            continue
        tr = _group_transform(sh.groups, p, variant) + base
        ax.add_patch(PathPatch(
            path.transformed(tr), facecolor=sh.fill or "none",
            edgecolor=sh.stroke or "none",
            linewidth=sh.lw * s * 80.0 if sh.stroke else 0.0,
            alpha=alpha, zorder=z, joinstyle="round", capstyle="round"))
