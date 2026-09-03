"""Resolves each dependency to the real module if it exists, else the stub.

This is what lets six people work in parallel. Nobody waits for anybody: the
orchestrator calls wiring.plan(), and whether that is Jyothi's real planner or
a hardcoded stub is decided at import time.

status() reports which is which, and the app shows it in the sidebar so we
always know what we are actually demoing.
"""

import hashlib
import importlib
import inspect
import os

from stubs import pair_a_ingest, pair_b, pair_c

_STATUS: dict[str, bool] = {}


def _resolve(name: str, real, stub):
    """Prefer the real module's attribute; fall back to the stub's.

    The callable() check matters: `planner.plan` is both a module name and a
    function name, so getattr can hand back a MODULE. Without this, wiring
    reports LIVE and the lesson dies later on "module object is not callable".
    """
    fn = getattr(real, name, None) if real is not None else None
    if not callable(fn):
        fn = None
    _STATUS[name] = fn is not None
    return fn if fn is not None else getattr(stub, name)


def _from_modules(name: str, *module_paths: str, stub):
    """Find `name` in the first submodule that actually provides it.

    Pair B does not re-export at package level, and final_quiz/build_report
    live under planner/ rather than teacher/. So look where the code is,
    not where the package index says it should be.
    """
    for path in module_paths:
        try:
            mod = importlib.import_module(path)
        except Exception:
            continue
        fn = getattr(mod, name, None)
        if callable(fn):
            _STATUS[name] = True
            return fn
    _STATUS[name] = False
    return getattr(stub, name)


def _adapt_reexplain(fn):
    """CONTRACT amended: reexplain now takes the session state as a 4th arg.

    Tolerate both shapes so a pair mid-update never breaks the lesson.
    """
    try:
        takes_state = len(inspect.signature(fn).parameters) >= 4
    except (TypeError, ValueError):
        takes_state = False

    if takes_state:
        return fn

    def _without_state(concept_id, misconception, attempt, state=None):
        return fn(concept_id, misconception, attempt)

    return _without_state


def _first_param(fn) -> str:
    try:
        return next(iter(inspect.signature(fn).parameters))
    except (TypeError, ValueError, StopIteration):
        return ""


def _adapt_render(fn):
    """CONTRACT: render(spec: VisualSpec, out_dir: str) -> png path.

    Pair C's is render(kind, content, subject="", data=None, output_path=None)
    — it never takes a VisualSpec. Unpack the spec for them rather than making
    them rewrite against shared/models.py mid-week.
    """
    if _first_param(fn) == "spec":
        return fn

    def _render(spec, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        key = hashlib.sha1(f"{spec.kind}{spec.payload}".encode()).hexdigest()[:12]
        data = {"title": spec.caption} if spec.caption else {}
        return fn(spec.kind, spec.payload, data=data,
                  output_path=os.path.join(out_dir, f"visual_{key}.png"))

    return _render


def _adapt_compose(fn):
    """CONTRACT: compose(avatar_mp4, visual_png, audio_wav).

    Pair C's is compose(visual_path, audio_path, avatar_path, ...) — same
    three inputs, different order. Reorder rather than guess at call sites.
    """
    if _first_param(fn) == "avatar_mp4":
        return fn

    def _compose(avatar_mp4, visual_png, audio_wav):
        return fn(visual_png, audio_wav or None, avatar_mp4 or None)

    return _compose


# --- Utkarsh: ingest/ -------------------------------------------------------
try:
    from ingest import pipeline as _real_ingest       # type: ignore
except Exception:
    _real_ingest = None

ingest = _resolve("ingest", _real_ingest, pair_a_ingest)
retrieve = _resolve("retrieve", _real_ingest, pair_a_ingest)

# --- Pair B: planner/ and teacher/ -----------------------------------------
# planner/__init__.py is empty and teacher/ has no __init__.py at all, so
# nothing is exposed at package level. Resolve against the submodules.

plan = _from_modules("plan", "planner.plan", "planner", stub=pair_b)
learning_path = _from_modules("learning_path", "planner.path", "planner", stub=pair_b)
next_segment = _from_modules("next_segment", "teacher.engine", "teacher", stub=pair_b)
evaluate = _from_modules("evaluate", "teacher.engine", "teacher", stub=pair_b)
final_quiz = _from_modules("final_quiz", "planner.quiz", "teacher.engine", "teacher", stub=pair_b)
build_report = _from_modules("build_report", "planner.report", "teacher.engine", "teacher", stub=pair_b)
answer_followup = _from_modules("answer_followup", "teacher.followup",
                                "teacher", stub=pair_b)
reexplain = _adapt_reexplain(
    _from_modules("reexplain", "teacher.engine", "teacher", stub=pair_b)
)

# --- Pair C: visuals/ and media/ -------------------------------------------
# Their work landed in prompt_101/media_pipeline rather than visuals/ and
# media/, so look there too. visuals/ and media/ come first in case they ever
# move it to where the contract says.
_PAIR_C = ("visuals", "media", "prompt_101.media_pipeline")

render = _adapt_render(_from_modules("render", *_PAIR_C, stub=pair_c))
choose_visual = _from_modules("choose_visual", *_PAIR_C, stub=pair_c)
speak = _from_modules("speak", *_PAIR_C, stub=pair_c)
render_avatar = _from_modules("render_avatar", *_PAIR_C, stub=pair_c)
compose = _adapt_compose(_from_modules("compose", *_PAIR_C, stub=pair_c))
stitch = _from_modules("stitch", *_PAIR_C, stub=pair_c)

# Length check before we pay for an avatar render. Theirs is named differently.
try:
    from prompt_101.media_pipeline.utils import get_audio_duration as audio_seconds
except Exception:
    audio_seconds = pair_c.audio_seconds


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
