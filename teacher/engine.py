import json
import os
from google import genai
from shared.models import (
    LessonPlan, SessionState, SourceChunk, TeachingSegment, 
    Question, StudentResponse, Evaluation, Turn
)
from teacher.prompts import NEXT_SEGMENT_PROMPT, EVALUATE_PROMPT, REEXPLAIN_PROMPT

# Initialize Gemini Client
# Assumes GEMINI_API_KEY is set in the environment
try:
    client = genai.Client()
except Exception:
    client = None # For testing purposes if API key is not set

MODEL_ID = "gemini-2.5-flash"

def _clean_json_output(response_text: str) -> str:
    """Strip markdown backticks if Gemini includes them despite instructions."""
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def next_segment(plan: LessonPlan, state: SessionState, chunks: list[SourceChunk]) -> TeachingSegment:
    """Generates the next teaching segment based on the plan and current state."""
    if not client:
        raise ValueError("Gemini client is not initialized. Please set GEMINI_API_KEY.")

    concept_id = plan.concepts[state.current_concept].id
    
    # Calculate difficulty
    # "Two wrong answers in a row -> simpler language, more basic examples."
    # "Two quick correct answers -> harder questions, more technical depth."
    difficulty_level = "standard"
    if len(state.evaluations) >= 2:
        last_two_actions = [e.action for e in state.evaluations[-2:]]
        if last_two_actions == ["harden", "harden"]:
            difficulty_level = "hard"
        elif last_two_actions == ["simplify", "simplify"]:
            difficulty_level = "simple"
        elif last_two_actions == ["reexplain", "reexplain"]:
            # two wrongs also lead to simplification according to brief
            difficulty_level = "simple"

    prompt = NEXT_SEGMENT_PROMPT.format(
        level=state.profile.level,
        language=state.profile.language,
        topic=plan.topic,
        plan_context=plan.model_dump_json(indent=2),
        chunks_text=json.dumps([c.model_dump() for c in chunks], indent=2) if chunks else "None",
        history_text=json.dumps([t.model_dump() for t in state.turns[-5:]], indent=2) if state.turns else "None",
        difficulty=difficulty_level
    )

    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt
    )
    
    cleaned_json = _clean_json_output(response.text)
    
    try:
        segment_data = json.loads(cleaned_json)
        # Ensure concept_id matches current state
        segment_data["concept_id"] = concept_id
        return TeachingSegment.model_validate(segment_data)
    except Exception as e:
        # Simple retry logic could go here; raising for simplicity in first pass
        raise RuntimeError(f"Failed to parse Gemini output as TeachingSegment: {e}\nRaw Output: {response.text}")


def evaluate(question: Question, response: StudentResponse) -> Evaluation:
    """Evaluates a student's answer and determines the misconception and next pedagogical action."""
    if not client:
        raise ValueError("Gemini client is not initialized. Please set GEMINI_API_KEY.")

    prompt = EVALUATE_PROMPT.format(
        question_prompt=question.prompt,
        expected_answer=question.expected,
        student_answer=response.answer
    )

    result = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt
    )
    
    cleaned_json = _clean_json_output(result.text)
    
    try:
        eval_data = json.loads(cleaned_json)
        return Evaluation.model_validate(eval_data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse Gemini output as Evaluation: {e}\nRaw Output: {result.text}")


def reexplain(concept_id: str, misconception: str, attempt: int, state: SessionState) -> TeachingSegment:
    """Generates a new teaching segment tackling a specific misconception with a fresh analogy based on attempt count."""
    if not client:
        raise ValueError("Gemini client is not initialized. Please set GEMINI_API_KEY.")

    concept_name = next((c.name for c in state.plan.concepts if c.id == concept_id), concept_id)

    prompt = REEXPLAIN_PROMPT.format(
        level=state.profile.level,
        language=state.profile.language,
        concept_name=concept_name,
        misconception=misconception,
        attempt=attempt
    )

    result = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt
    )
    
    cleaned_json = _clean_json_output(result.text)
    
    try:
        segment_data = json.loads(cleaned_json)
        segment_data["concept_id"] = concept_id
        return TeachingSegment.model_validate(segment_data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse Gemini output as TeachingSegment: {e}\nRaw Output: {result.text}")
