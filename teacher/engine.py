import json
from shared.models import (
    LessonPlan, SessionState, SourceChunk, TeachingSegment, 
    Question, StudentResponse, Evaluation, Turn
)
from prompts import SEGMENT_PROMPT, EVALUATE_PROMPT, REEXPLAIN_PROMPT
from llm import generate_json

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

    data = generate_json(prompt)
    data["concept_id"] = concept.id  # Enforce matching concept ID
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
    return Evaluation.model_validate(data)

def reexplain(concept_id: str, misconception: str, attempt: int, state: SessionState) -> TeachingSegment:
    """Generates a new teaching segment tackling a specific misconception with a fresh analogy."""
    concept = next((c for c in state.plan.concepts if c.id == concept_id), None)
    concept_name = concept.name if concept else concept_id
    depth = concept.depth if concept else "standard"
    
    # Force genuinely different analogies based on attempt number
    analogies = [
        "water flowing through a pipe", 
        "a crowd squeezing through a doorway", 
        "traffic on a narrowing road", 
        "heat flowing through a window"
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
        
    data = generate_json(prompt)
    data["concept_id"] = concept_id
    return TeachingSegment.model_validate(data)
