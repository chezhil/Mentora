PLAN_PROMPT = """
You are the AI Teacher lesson planner.
Create a LessonPlan for the given topic and student profile.

CRITICAL RULE: The sum of 'minutes' across all concepts MUST EXACTLY EQUAL {total_minutes}. Do not deviate.

PROFILE:
Level: {level}
Language: {language}
Topic: {topic}

INSTRUCTIONS:
1. Break the topic into logical concepts.
2. Order them by prerequisites (e.g., cannot teach Ohm's Law before current and voltage). Set the 'prerequisites' array in each concept.
3. Set concept 'depth' (brief, standard, deep) according to the student's level ({level}).
   - beginner: brief, simple words, analogies
   - intermediate: standard, technical terms
   - advanced: deep, full terminology, formulas
4. Allocate time so the sum is exactly {total_minutes}.

OUTPUT FORMAT:
Return ONLY a raw JSON object matching the LessonPlan schema. Do not include markdown formatting, no explanations, just the JSON.
Schema Reference:
{{
  "topic": "{topic}",
  "language": "{language}",
  "total_minutes": {total_minutes},
  "concepts": [
    {{
      "id": "c1",
      "name": "...",
      "depth": "brief" | "standard" | "deep",
      "minutes": 5,
      "prerequisites": []
    }}
  ]
}}
"""

QUIZ_PROMPT = """
You are generating a final quiz for a lesson that just completed.

LESSON PLAN:
{plan_context}

INSTRUCTIONS:
Generate a list of Questions. Include a mix of 'mcq', 'short', 'explain', and 'problem'.
Generate 1 or 2 questions per concept taught.

OUTPUT FORMAT:
Return ONLY a raw JSON array matching the list[Question] schema.
"""

REPORT_PROMPT = """
You are evaluating a student's performance at the end of a session to generate a LessonReport.

SESSION STATE (including history and evaluations):
{session_context}

INSTRUCTIONS:
Calculate a score (0 to 100) based on correct answers and difficulty adjustments.
Identify strong areas, weak areas, specific misconceptions observed, what they need to revise, and suggest the logical next topic.

OUTPUT FORMAT:
Return ONLY a raw JSON object matching the LessonReport schema.
"""

LEARNING_PATH_PROMPT = """
You are an educational curriculum designer.
Given a broad topic, return an ordered list of sub-topics to work through from beginner to advanced.

TOPIC: {topic}

OUTPUT FORMAT:
Return ONLY a raw JSON array of strings. (e.g. ["Subtopic 1", "Subtopic 2"])
"""
