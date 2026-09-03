# Personalization approach

Mentora uses a multi-faceted approach to personalize learning:
- Follows the user's explicit language preference and learning goal.
- Adjusts concept depth based on the user's level (beginner, intermediate, advanced).
- Times the lesson to exactly match the available time budget (5, 20, 60 minutes) or over a multi-day horizon.
- Adapts mid-lesson based on evaluations, identifying misconceptions and dynamically re-explaining, simplifying, or hardening the content.

# AI/ML models used

- **LLM Generation**: Google Gemini Flash via `google-genai` SDK is used as the core engine for planning, teaching, generating quizzes, and evaluating answers.
- **Embeddings**: BAAI BGE-M3 for multilingual vector retrieval of document chunks.
