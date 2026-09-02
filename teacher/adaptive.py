"""teacher.adaptive — shared helpers for the live teaching loop.

Difficulty, question cadence, and language switching live here so every
part of the engine behaves the same way.
"""

from __future__ import annotations

from datetime import datetime

from shared.models import SessionState, Turn


def difficulty_of(state: SessionState) -> str:
    """Returns 'simplify' | 'standard' | 'harden' from recent history.

    Contract rule: two wrong answers in a row -> simplify. Two quick
    correct answers in a row -> harden. Otherwise standard.
    """
    recent = [e.correct for e in state.evaluations][-2:]
    if len(recent) == 2:
        if recent == [True, True]:
            return "harden"
        if recent == [False, False]:
            return "simplify"
    return "standard"


def should_ask(state: SessionState) -> bool:
    """Ask every ~3rd teaching segment so it is neither a monologue nor an
    interrogation. The first question comes after at least two segments."""
    teacher_segments = len([t for t in state.turns if t.role == "teacher"])
    answered = len(state.evaluations)
    if answered == 0:
        return teacher_segments >= 2 and teacher_segments % 2 == 0
    return (teacher_segments - answered) >= 2


def recent_history(state: SessionState, n: int = 8) -> str:
    """Last n turns, formatted for a prompt."""
    lines = []
    for t in state.turns[-n:]:
        lines.append(f"- {t.role}: {t.content[:400]}")
    return "\n".join(lines) or "this is the start of the lesson"


def switch_language(state: SessionState, language: str) -> SessionState:
    """Switch the lesson output language without losing position. The
    conversation history stays in session.turns; only the output language
    changes. Returns a copy of the state."""
    state.profile.language = language
    state.turns.append(
        Turn(
            role="system",
            content=f"Student switched the lesson language to {language}. "
            f"Continue from the exact same point, in {language}.",
            timestamp=datetime.now(),
        )
    )
    return state


def record_turn(turns: list[Turn], role: str, content: str,
                concept_id: str | None = None) -> None:
    """Append a turn to the session history."""
    turns.append(
        Turn(
            role=role,
            content=content,
            concept_id=concept_id,
            timestamp=datetime.now(),
        )
    )


def advance(state: SessionState) -> None:
    """Move to the next concept. Stays on the last concept at the end."""
    if state.current_concept < len(state.plan.concepts) - 1:
        state.current_concept += 1