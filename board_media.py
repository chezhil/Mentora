"""Render the restyled animated board video for a lesson segment.

Wires avatar-prototype/lesson_video.py board renderer (the board-and-ink
visual language) into the media pipeline without a second TTS call: it takes
the WAV the pipeline already synthesised, splits the script on audible pauses
to approximate sentence boundaries, schedules the payload elements against
them, and muxes that same audio into the finished MP4.

Anything that can fail here returns None and logs why, so orchestrator.
_build_media falls back to the previous static-visual + avatar-compose path.
The product never regresses because of this module.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import struct
import sys
import wave
from pathlib import Path

_AP_DIR = Path(__file__).resolve().parent / "avatar-prototype"
_AP_MODULE = _AP_DIR / "lesson_video.py"

GAP_SECONDS = float(os.environ.get("MENTORA_BOARD_GAP", "0.22"))


def _lesson_video():
    """Import avatar-prototype/lesson_video.py (hyphenated dir)."""
    if not _AP_MODULE.exists():
        raise FileNotFoundError("board renderer missing at " + str(_AP_MODULE))
    spec = importlib.util.spec_from_file_location("lesson_video_board", _AP_MODULE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def split_sentences_by_pause(wav, script, min_gap=GAP_SECONDS):
    """Approximate sentence boundaries from amplitude pauses in PCM16 WAV.

    Mentora TTS backends (edge-tts, piper) pause between sentences. We find
    those pauses and give each script sentence the span of the utterance it
    lands in; more sentences than pauses are distributed proportionally by
    text length. An approximation of the prototype real SentenceBoundary
    timing, but it needs no second TTS call and no model.
    """
    lv = _lesson_video()
    with wave.open(str(wav), "rb") as w:
        rate = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("need 16-bit PCM, got %d-bit" % (width * 8))
    samples = struct.unpack("<%dh" % (len(frames) // 2), frames)
    if ch > 1:
        samples = samples[0::ch]
    if not samples:
        return []

    win = max(1, int(rate * 0.020))  # 20 ms windows -> RMS envelope
    rms = []
    for i in range(0, len(samples) - win, win):
        chunk = samples[i:i + win]
        acc = 0
        for s in chunk:
            acc += s * s
        rms.append((acc / len(chunk)) ** 0.5)
    peak = max(rms) if rms else 0
    if peak <= 0:
        raise ValueError("silent audio; cannot time the board")
    floor = peak * 0.035

    speech = [v > floor for v in rms]
    runs = []
    start = None
    for i, on in enumerate(speech):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(speech)))
    if not runs:
        raise ValueError("no voiced audio detected")

    merged = [list(runs[0])]
    for lo, hi in runs[1:]:
        if (lo - merged[-1][1]) * 0.020 < min_gap:
            merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    spans = [(lo * 0.020, hi * 0.020) for lo, hi in merged]

    # sentences are delimited by danda / full stops
    seps = re.split("([।.!?]+)", script)
    parts = []
    cur = ""
    for tok in seps:
        if re.fullmatch("[।.!?]+", tok):
            if cur.strip():
                parts.append(cur.strip())
            cur = ""
        else:
            cur += tok
    if cur.strip():
        parts.append(cur.strip())
    n = len(parts)
    if n == 0:
        raise ValueError("script has no sentences")
    dur = len(samples) / rate

    # Sentences must tile the WHOLE audio: take the n-1 longest internal
    # pauses as boundaries and add 0 and dur, so the last sentence always
    # runs to the end and -shortest never cuts the narration short.
    cuts = []
    for k in range(len(spans) - 1):
        gap = spans[k + 1][0] - spans[k][1]
        if gap >= min_gap:
            cuts.append(((spans[k][1] + spans[k + 1][0]) / 2.0, gap))
    cuts.sort(key=lambda c: -c[1])
    cuts = sorted(c[0] for c in cuts[: max(0, n - 1)])

    # Fewer audible pauses than sentences is common: a script with short
    # clauses, or a backend that runs them together. The docstring promised
    # these were "distributed proportionally by text length" but that was
    # never implemented, so bounds came up short and bounds[k + 1] raised
    # IndexError -- which render_board_video swallows, so the animated board
    # silently did not render and the lesson quietly fell back to a still.
    if len(cuts) < n - 1:
        lengths = [max(len(part), 1) for part in parts]
        total = float(sum(lengths))
        acc, proportional = 0.0, []
        for length in lengths[:-1]:
            acc += length
            proportional.append(dur * acc / total)
        cuts = proportional

    bounds = [0.0] + cuts + [dur]
    # Walk the boundaries so spans can never overlap or run backwards. The
    # 0.05s minimum length pushed each span past the next one when there were
    # more sentences than seconds, and subtitle() picks the FIRST span
    # containing t, so out-of-order spans show the wrong line.
    out = []
    prev = 0.0
    for k in range(n):
        lo = min(max(bounds[k], prev), dur)
        hi = min(max(bounds[k + 1], lo + 0.05), dur)
        if hi <= lo:
            hi = min(lo + 0.05, dur)
        out.append(lv.Sentence(parts[k], lo, hi))
        prev = hi
    return out


def render_board_video(script, kind, payload, caption, out_dir, audio_wav,
                       max_seconds=60.0):
    """Build the narrated board MP4 for one segment; None on any failure."""
    try:
        lv = _lesson_video()
        wav = Path(audio_wav)
        if not wav.exists():
            return None
        with wave.open(str(wav), "rb") as w:
            secs = w.getnframes() / float(w.getframerate())
        if secs <= 0.2:
            return None
        if secs > max_seconds:
            print("board: script %.0fs over %.0fs cap" % (secs, max_seconds),
                  file=sys.stderr)
            return None

        sentences = split_sentences_by_pause(wav, script)
        if not sentences:
            return None
        narration = lv.Narration(audio=wav, sentences=sentences)

        elements = (lv.parse_equation(payload) if kind == "equation"
                    else lv.parse_diagram(payload))
        caption = (caption or script[:60]).strip()
        lv.schedule(elements, sentences)

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(script[:40].encode("utf-8", "ignore")).hexdigest()[:10]
        out = out_dir / ("board_%s_%s.mp4" % (kind, key))
        lv.encode(out, elements, kind, caption, narration)
        return str(out)
    except Exception as exc:
        print("board render failed: %r" % (exc,), file=sys.stderr)
        return None

