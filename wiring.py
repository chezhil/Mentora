"""Resolves each dependency to the real module if it exists, else the stub.

This is what lets six people work in parallel. Nobody waits for anybody: the
orchestrator calls wiring.plan(), and whether that is Jyothi's real planner or
a hardcoded stub is decided at import time.

status() reports which is which, and the app shows it in the sidebar so we
always know what we are actually demoing.
"""

from stubs import pair_a_ingest, pair_b, pair_c

_STATUS: dict[str, bool] = {}


def _resolve(name: str, real, stub):
    """Prefer the real module's attribute; fall back to the stub's."""
    fn = getattr(real, name, None) if real is not None else None
    _STATUS[name] = fn is not None
    return fn if fn is not None else getattr(stub, name)


# --- Utkarsh: ingest/ -------------------------------------------------------
try:
    from ingest import pipeline as _real_ingest       # type: ignore
except Exception:
    _real_ingest = None

ingest = _resolve("ingest", _real_ingest, pair_a_ingest)
retrieve = _resolve("retrieve", _real_ingest, pair_a_ingest)

# --- Pair B: planner/ and teacher/ -----------------------------------------
try:
    import planner as _real_planner                   # type: ignore
except Exception:
    _real_planner = None

try:
    import teacher as _real_teacher                   # type: ignore
except Exception:
    _real_teacher = None

plan = _resolve("plan", _real_planner, pair_b)
learning_path = _resolve("learning_path", _real_planner, pair_b)
next_segment = _resolve("next_segment", _real_teacher, pair_b)
evaluate = _resolve("evaluate", _real_teacher, pair_b)
reexplain = _resolve("reexplain", _real_teacher, pair_b)
final_quiz = _resolve("final_quiz", _real_teacher, pair_b)
build_report = _resolve("build_report", _real_teacher, pair_b)

# --- Pair C: visuals/ and media/ -------------------------------------------
try:
    import visuals as _real_visuals                   # type: ignore
except Exception:
    _real_visuals = None

try:
    import media as _real_media                       # type: ignore
except Exception:
    _real_media = None

render = _resolve("render", _real_visuals, pair_c)
choose_visual = _resolve("choose_visual", _real_visuals, pair_c)
speak = _resolve("speak", _real_media, pair_c)
render_avatar = _resolve("render_avatar", _real_media, pair_c)
compose = _resolve("compose", _real_media, pair_c)
stitch = _resolve("stitch", _real_media, pair_c)

# audio_seconds is a stub-only helper; the real media module may not have it.
audio_seconds = getattr(_real_media, "audio_seconds", pair_c.audio_seconds)


def status() -> dict[str, str]:
    """{'retrieve': 'LIVE', 'plan': 'STUB', ...} for the sidebar."""
    return {k: ("LIVE" if v else "STUB") for k, v in sorted(_STATUS.items())}


def summary() -> dict[str, str]:
    """Per-pair rollup: LIVE only when every function from that pair is real."""
    groups = {
        "Pair A · ingest": ["ingest", "retrieve"],
        "Pair B · teaching": ["plan", "next_segment", "evaluate", "reexplain",
                              "final_quiz", "build_report", "learning_path"],
        "Pair C · media": ["render", "choose_visual", "speak", "render_avatar",
                           "compose", "stitch"],
    }
    out = {}
    for label, names in groups.items():
        live = sum(1 for n in names if _STATUS.get(n))
        out[label] = "LIVE" if live == len(names) else f"STUB ({live}/{len(names)} live)"
    return out
