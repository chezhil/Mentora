import itertools
import json
import re
import uuid
from shared.models import (
    LessonPlan, SessionState, SourceChunk, TeachingSegment, 
    Question, StudentResponse, Evaluation
)
from prompts import SEGMENT_PROMPT, EVALUATE_PROMPT, REEXPLAIN_PROMPT
from llm import generate_json
from shared.config import MAX_AVATAR_SECONDS, WORDS_PER_SECOND

# Pair C refuses to render an avatar for narration longer than
# MAX_AVATAR_SECONDS, and rightly — a 60s render costs $0.40, a 20-minute one
# $5-8. Asking the model nicely is not enough: with a real key it produced
# scripts of 74 to 114 seconds and every single segment came back with no
# video. So the limit is enforced here as well as requested in the prompt.
# 0.85 leaves headroom because speech rate varies by language and voice.
MAX_SCRIPT_WORDS = int(MAX_AVATAR_SECONDS * WORDS_PER_SECOND * 0.85)


def fit_script(script: str, limit: int = MAX_SCRIPT_WORDS) -> str:
    """Trim narration to the avatar budget, cutting at a sentence boundary."""
    if not script:
        return script
    words = script.split()
    if len(words) <= limit:
        return script

    clipped = " ".join(words[:limit])
    # Prefer to end on a finished sentence rather than mid-thought.
    for stop in ("।", ".", "!", "?"):          # danda first for Indic scripts
        cut = clipped.rfind(stop)
        if cut > len(clipped) * 0.5:
            return clipped[: cut + 1]
    return clipped.rstrip(",;:") + "..."

# ---------------------------------------------------------------------------
# Question hygiene
#
# Two bugs lived here, and both looked like "the buttons stopped working".
#
# 1. IDS.  The prompt's example JSON literally contains "id": "q__AUX__", so
#    the model copies it verbatim into every single question. app.py keys its
#    double-click guard on answer:<session>:<question.id>, so once the first
#    question is answered the token is spent and EVERY later Answer and Skip
#    button silently does nothing. Ids are assigned here now, not by the model.
#
# 2. OPTIONS.  A question can come back kind="mcq" with options null (the
#    re-explain prompt actively asks for that), or with four options and
#    kind="short". Either way the student gets the wrong widget. Kind and
#    options are reconciled against each other, and `expected` is snapped onto
#    a real option so marking a click can succeed.
# ---------------------------------------------------------------------------

_QUESTION_SEQ = itertools.count(1)

# "b) 30 ohms", "(B) 30 ohms", "B. 30 ohms" -> the letter, and the rest.
_LETTERED = re.compile(r"^\s*[\(\[]?([A-Da-d])[\)\].:-]\s*(.+)$")


def _fresh_question_id(concept_id: str) -> str:
    return f"q{next(_QUESTION_SEQ)}_{concept_id}"


def _match_option(expected: str, options: list[str]) -> str | None:
    """Find the option `expected` refers to, tolerating how models write it."""
    want = (expected or "").strip()
    if not want:
        return None

    lowered = [o.strip().lower() for o in options]
    if want.lower() in lowered:
        return options[lowered.index(want.lower())]

    # A bare letter, or a letter with the text after it.
    letter = None
    if len(want) == 1 and want.upper() in "ABCD":
        letter = want.upper()
    else:
        m = _LETTERED.match(want)
        if m:
            letter = m.group(1).upper()
            tail = m.group(2).strip().lower()
            if tail in lowered:
                return options[lowered.index(tail)]
    if letter is not None:
        i = ord(letter) - ord("A")
        if 0 <= i < len(options):
            return options[i]

    # Last resort: the option that contains the expected answer, or vice versa.
    for option, low in zip(options, lowered):
        if want.lower() in low or low in want.lower():
            return option
    return None


def normalise_question(raw: dict | None, concept_id: str) -> dict | None:
    """Give the question a unique id and make kind agree with options."""
    if not isinstance(raw, dict):
        return None
    if not str(raw.get("prompt", "")).strip():
        return None

    raw = dict(raw)
    raw["id"] = _fresh_question_id(concept_id)
    raw["concept_id"] = concept_id
    # Question.prompt and .expected are typed str, and pydantic does not coerce
    # into str. A model answering a numeric question with "expected": 42 --
    # entirely plausible -- raised ValidationError out of next_segment and took
    # the whole lesson step with it. Coerce here, where the shape is being
    # normalised anyway.
    raw["prompt"] = str(raw.get("prompt", "")).strip()

    options = raw.get("options")
    if isinstance(options, list):
        # Strip "A) " prefixes so the radio reads as answers, not a lettered
        # list the student then has to type a letter for.
        cleaned = []
        for option in options:
            text = str(option).strip()
            m = _LETTERED.match(text)
            cleaned.append(m.group(2).strip() if m else text)
        options = [o for o in dict.fromkeys(cleaned) if o]
    else:
        options = None

    if options and len(options) >= 2:
        raw["kind"] = "mcq"
        raw["options"] = options
        snapped = _match_option(str(raw.get("expected") or ""), options)
        # An mcq whose correct answer is not one of the options cannot be
        # marked by clicking, so it stops being an mcq.
        if snapped is None:
            raw["kind"] = "short"
            raw["options"] = None
        else:
            raw["expected"] = snapped
    else:
        raw["options"] = None
        if raw.get("kind") == "mcq":
            raw["kind"] = "short"

    if raw.get("kind") not in ("mcq", "short", "explain", "problem"):
        raw["kind"] = "short"
    # str(None) is "None", which is not empty — so a model returning
    # "expected": null produced the literal string "None" as the correct
    # answer, and EVALUATE_PROMPT then told the marker that "None" was right.
    expected = raw.get("expected")
    # str(None) is "None", not empty, so "expected": null used to become the
    # literal string "None" and EVALUATE_PROMPT was told that was the answer.
    if expected is None or not str(expected).strip():
        raw["expected"] = "(open answer — mark on understanding)"
    else:
        raw["expected"] = str(expected)
    return raw


VISUAL_KINDS = ("equation", "graph", "diagram", "timeline", "code",
                "concept_map", "none")

# What models reach for when they do not use the exact word we asked for.
_KIND_ALIASES = {
    "flowchart": "diagram", "flow": "diagram", "flow_chart": "diagram",
    "picture": "none", "image": "none", "photo": "none", "illustration": "none",
    "chart": "graph", "plot": "graph", "line_graph": "graph", "bar": "graph",
    "formula": "equation", "math": "equation", "equations": "equation",
    "map": "concept_map", "mindmap": "concept_map", "concept map": "concept_map",
    "conceptmap": "concept_map", "snippet": "code", "program": "code",
    "timeline_chart": "timeline", "none_needed": "none", "null": "none",
}


def _clean_segment(data: dict | None, concept_id: str) -> dict:
    """Coerce a model's segment into the shape TeachingSegment demands.

    Six plausible outputs used to raise straight out of next_segment and take
    the lesson step with them: a numeric script, a visual kind the model
    invented, a null payload, no visual key at all, a numeric caption, and an
    empty object. TeachingSegment is typed and pydantic will not coerce into
    str, so every one of those was a ValidationError mid-lesson.
    """
    data = dict(data) if isinstance(data, dict) else {}
    data["concept_id"] = concept_id
    data["script"] = str(data.get("script") or "")

    visual = data.get("visual")
    if not isinstance(visual, dict):
        visual = {}
    kind = str(visual.get("kind") or "none").strip().lower().replace("-", "_")
    if kind not in VISUAL_KINDS:
        kind = _KIND_ALIASES.get(kind, "none")
    caption = visual.get("caption")
    data["visual"] = {
        "kind": kind,
        "payload": str(visual.get("payload") or ""),
        "caption": None if caption is None else (str(caption).strip() or None),
    }
    return data


def next_segment(plan: LessonPlan, state: SessionState, chunks: list[SourceChunk]) -> TeachingSegment:
    """Generates the next teaching segment based on the plan and current state."""
    concept = plan.concepts[state.current_concept]
    
    # Calculate difficulty
    # "Two wrong answers in a row -> simpler language, more basic examples."
    # "Two quick correct answers -> harder questions, more technical depth."
    difficulty_level = "standard"
    if len(state.evaluations) >= 2:
        last_two_actions = [e.action for e in state.evaluations[-2:]]
        if last_two_actions == ["harden", "harden"]:
            difficulty_level = "harden"
        elif last_two_actions == ["simplify", "simplify"] or last_two_actions == ["reexplain", "reexplain"]:
            difficulty_level = "simplify"

    history_str = "\n".join([f"{t.role}: {t.content}" for t in state.turns[-5:]]) if state.turns else "No history yet."
    chunks_str = json.dumps([c.model_dump() for c in chunks], indent=2) if chunks else "No chunks."

    prompt = SEGMENT_PROMPT \
        .replace("<<TOPIC>>", plan.topic) \
        .replace("<<LANGUAGE>>", state.profile.language) \
        .replace("<<DIFFICULTY>>", difficulty_level) \
        .replace("<<CONCEPT>>", concept.name) \
        .replace("<<MINUTES>>", str(concept.minutes)) \
        .replace("<<HISTORY>>", history_str) \
        .replace("<<CHUNKS>>", chunks_str) \
        .replace("<<ASK>>", "True") \
        .replace("<<CONCEPT_ID>>", concept.id)

    data = _clean_segment(generate_json(prompt), concept.id)
    if data.get("question"):
        data["question"]["id"] = f"q_{concept.id}_{uuid.uuid4().hex[:6]}"
        data["question"]["concept_id"] = concept.id
    # CONTRACT: "citations copied from chunks when material was used".
    # Overwrite rather than trust the model — anything it invents here would be
    # a hallucinated page number, which is worse than none. These are the real
    # chunks retrieval returned.
    data["citations"] = [c.model_dump() for c in chunks]
    data["script"] = fit_script(data.get("script", ""))
    data["question"] = normalise_question(data.get("question"), concept.id)
    return TeachingSegment.model_validate(data)

def evaluate(question: Question, response: StudentResponse) -> Evaluation:
    """Evaluates a student's answer and determines the misconception and next pedagogical action."""
    prompt = EVALUATE_PROMPT \
        .replace("<<PROMPT>>", question.prompt) \
        .replace("<<KIND>>", question.kind) \
        .replace("<<OPTIONS>>", json.dumps(question.options) if question.options else "None") \
        .replace("<<EXPECTED>>", question.expected) \
        .replace("<<ANSWER>>", response.answer)
        
    data = generate_json(prompt)
    if not isinstance(data, dict):
        data = {}

    # Evaluation is a typed model and pydantic will not coerce into str, so
    # every field the model might get wrong is normalised here. A marking call
    # that raises ValidationError ends the lesson on a perfectly good answer,
    # which is a far worse outcome than a slightly-guessed verdict.
    verdict = data.get("correct")
    if isinstance(verdict, str):
        verdict = verdict.strip().lower() in ("true", "yes", "correct", "1", "y")
    data["correct"] = bool(verdict)

    action = str(data.get("action", "")).lower().strip()
    if action not in ("continue", "reexplain", "simplify", "harden", "example"):
        action = "continue" if data.get("correct") else "reexplain"
    data["action"] = action

    # Normalise BEFORE defaulting: a misconception of "   " is truthy, so it
    # skipped the default and was only stripped to None afterwards, leaving a
    # wrong answer with no named mistake. The contract, and the adaptation
    # panel, both require one.
    misconception = data.get("misconception")
    misconception = "" if misconception is None else str(misconception).strip()
    if data["correct"]:
        data["misconception"] = None                 # schema: correct => none
    else:
        data["misconception"] = (misconception
                                 or "Incomplete or inaccurate explanation")

    # `if not feedback` only catches the falsy ones: a numeric feedback of 5
    # is truthy, survived to model_validate and failed the str field there.
    feedback = data.get("feedback")
    feedback = "" if feedback is None else str(feedback).strip()
    data["feedback"] = feedback or (
        "Great work! Let's continue." if data["correct"]
        else "Let's review this concept carefully.")

    return Evaluation.model_validate(data)

def reexplain(concept_id: str, misconception: str, attempt: int, state: SessionState) -> TeachingSegment:
    """Generates a new teaching segment tackling a specific misconception with a fresh analogy."""
    concept = next((c for c in state.plan.concepts if c.id == concept_id), None)
    concept_name = concept.name if concept else concept_id
    depth = concept.depth if concept else "standard"
    topic = state.plan.topic.lower()
    
    # Select or generate topic-aware analogies rather than hardcoding circuit analogies for all subjects
    if any(k in topic for k in ["circuit", "ohm", "electric", "current", "voltage", "physics"]):
        analogies = [
            "water flowing through a narrowing pipe with a pump", 
            "a crowd squeezing through a turnstile doorway", 
            "traffic moving through road construction lanes", 
            "heat conducting through a thick glass window"
        ]
    elif any(k in topic for k in ["bio", "photo", "cell", "plant", "organ"]):
        analogies = [
            "a solar-powered molecular kitchen preparing food",
            "a locked factory assembly line with chemical gatekeepers",
            "a battery pack recharging through captured sunlight",
            "a bustling delivery network transporting nutrients"
        ]
    elif any(k in topic for k in ["code", "program", "react", "python", "data", "software"]):
        analogies = [
            "a chef following an exact recipe step-by-step",
            "a postal sorting center routing labeled parcels",
            "a blueprint for constructing Lego modular houses",
            "a synchronized conveyor belt processing incoming requests"
        ]
    else:
        analogies = [
            f"an intuitive real-world scenario illustrating {concept_name}",
            f"a step-by-step everyday process showing how {concept_name} behaves",
            f"a contrasting visual comparison addressing why {misconception} occurs",
            f"a simplified foundational model breaking down {concept_name}"
        ]

    new_analogy = analogies[(attempt - 1) % len(analogies)]
    used_analogies = "\n".join(analogies[:max(0, attempt - 1)]) or "None"
    
    history_str = "\n".join([f"{t.role}: {t.content}" for t in state.turns[-5:]]) if state.turns else "None"
    
    prompt = REEXPLAIN_PROMPT \
        .replace("<<ATTEMPT>>", str(attempt)) \
        .replace("<<CONCEPT_NAME>>", concept_name) \
        .replace("<<DEPTH>>", depth) \
        .replace("<<MISCONCEPTION>>", misconception) \
        .replace("<<LANGUAGE>>", state.profile.language) \
        .replace("<<ANALOGY>>", new_analogy) \
        .replace("<<USED_ANALOGIES>>", used_analogies) \
        .replace("<<HISTORY>>", history_str) \
        .replace("<<CONCEPT_ID>>", concept_id)
        
    data = _clean_segment(generate_json(prompt), concept_id)
    if data.get("question"):
        data["question"]["id"] = f"q_{concept_id}_{attempt}_{uuid.uuid4().hex[:6]}"
        data["question"]["concept_id"] = concept_id
    data["script"] = fit_script(data.get("script", ""))
    data["question"] = normalise_question(data.get("question"), concept_id)
    return TeachingSegment.model_validate(data)
