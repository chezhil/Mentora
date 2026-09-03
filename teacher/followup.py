"""Answering a student's own question mid-lesson.  OWNER: Jyothi.

Task 2 of the brief: "Answer follow-up questions while maintaining lesson
context." We score nothing for this today.

CONTRACT — this signature is fixed. Chezhil's UI calls it through
wiring.answer_followup, and wiring falls back to the placeholder below until
you replace it, so the app keeps running while you work.

    answer_followup(question: str, state: SessionState,
                    chunks: list[SourceChunk]) -> str

    IN:   what the student asked, the session so far, and the chunks the
          orchestrator retrieved for their question (may be empty).
    OUT:  the teacher's spoken reply. Plain text, no JSON, no markdown.

    MUST: answer in state.profile.language
    MUST: stay under 130 words — the same avatar cap as a teaching script
          (see teacher.engine.fit_script, reuse it)
    MUST: if chunks is empty AND state.doc_id is set, say plainly that the
          question is not covered by their material rather than answering
          from general knowledge. That honesty is worth more than a guess.
    MUST: end by steering back to the lesson, so the flow is not lost.
"""

from shared.models import SessionState, SourceChunk


def answer_followup(question: str, state: SessionState,
                    chunks: list[SourceChunk]) -> str:
    """PLACEHOLDER — Jyothi replaces this body. Signature is fixed."""
    return (
        "That's a good question — I can't answer it properly yet, so let's "
        "carry on with the lesson and come back to it."
    )
