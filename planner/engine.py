import json
from google import genai
from shared.models import LearnerProfile, LessonPlan, Question, LessonReport, SessionState
from planner.prompts import PLAN_PROMPT, QUIZ_PROMPT, REPORT_PROMPT, LEARNING_PATH_PROMPT

MODEL_ID = "gemini-2.5-flash"

def _clean_json_output(response_text: str) -> str:
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

# Initialize Gemini Client
try:
    client = genai.Client()
except Exception:
    client = None

def plan(topic: str, profile: LearnerProfile, doc_id: str | None) -> LessonPlan:
    """Generates a lesson plan matching the exact minutes requested."""
    if not client:
        raise ValueError("Gemini client is not initialized.")

    prompt = PLAN_PROMPT.format(
        topic=topic,
        level=profile.level,
        language=profile.language,
        total_minutes=profile.time_minutes
    )

    result = client.models.generate_content(model=MODEL_ID, contents=prompt)
    cleaned = _clean_json_output(result.text)
    
    try:
        plan_data = json.loads(cleaned)
        return LessonPlan.model_validate(plan_data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse LessonPlan: {e}\nRaw Output: {result.text}")


def final_quiz(plan: LessonPlan) -> list[Question]:
    if not client:
        raise ValueError("Gemini client is not initialized.")

    prompt = QUIZ_PROMPT.format(plan_context=plan.model_dump_json(indent=2))
    result = client.models.generate_content(model=MODEL_ID, contents=prompt)
    cleaned = _clean_json_output(result.text)
    
    try:
        quiz_data = json.loads(cleaned)
        return [Question.model_validate(q) for q in quiz_data]
    except Exception as e:
        raise RuntimeError(f"Failed to parse final_quiz: {e}\nRaw: {result.text}")


def build_report(session: SessionState) -> LessonReport:
    if not client:
        raise ValueError("Gemini client is not initialized.")

    prompt = REPORT_PROMPT.format(session_context=session.model_dump_json(indent=2))
    result = client.models.generate_content(model=MODEL_ID, contents=prompt)
    cleaned = _clean_json_output(result.text)
    
    try:
        report_data = json.loads(cleaned)
        return LessonReport.model_validate(report_data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse build_report: {e}\nRaw: {result.text}")


def learning_path(topic: str) -> list[str]:
    if not client:
        raise ValueError("Gemini client is not initialized.")

    prompt = LEARNING_PATH_PROMPT.format(topic=topic)
    result = client.models.generate_content(model=MODEL_ID, contents=prompt)
    cleaned = _clean_json_output(result.text)
    
    try:
        return json.loads(cleaned)
    except Exception as e:
        raise RuntimeError(f"Failed to parse learning_path: {e}\nRaw: {result.text}")
