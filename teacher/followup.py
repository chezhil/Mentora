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
from llm import generate_json
from prompts import FOLLOWUP_PROMPT, fill
from teacher.engine import fit_script


def _recent_history(state: SessionState) -> str:
    if not state.turns:
        return "No history yet."
    return "\n".join(f"{t.role}: {t.content}" for t in state.turns[-5:])


def answer_followup(question: str, state: SessionState,
                    chunks: list[SourceChunk]) -> str:
    """Answers the student's question aloud and steers back to the lesson."""
    language = state.profile.language

    # Contract: when there is an uploaded document but retrieval returned no
    # relevant chunks, we say plainly the question is not in their material
    # instead of answering from general knowledge.
    if chunks:
        status = "covered"
        material = "\n".join(
            f"[chunk {i}] {c.text}" for i, c in enumerate(chunks)
        )
    elif state.doc_id:
        status = "not in material"
        material = "No relevant passage was retrieved from the document."
    else:
        status = "no document"
        material = "The student has no uploaded document for this lesson."

    prompt = fill(
        FOLLOWUP_PROMPT,
        LANGUAGE=language,
        HISTORY=_recent_history(state),
        QUESTION=question,
        MATERIAL_STATUS=status,
        MATERIAL=material,
    )

    reply = generate_json(prompt).get("answer", "")
    if not reply:
        reply = (
            "That is a good question. Let me hold onto it and we will come "
            "back to it after this part of the lesson."
        )
    return fit_script(reply.strip())
