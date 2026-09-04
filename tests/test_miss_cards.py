"""Offline proof that a missed answer becomes a flashcard rated \"again\".

Exercises orchestrator.answer() and orchestrator.submit_quiz() end to end
against a throwaway SQLite DB (history.db.DB_PATH is redirected) and a fake
LLM, so nothing here touches mentora.db or a network.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.models import (
    Concept, LearnerProfile, LessonPlan, Question, SessionState,
    StudentResponse,
)
import history.db as hdb
import llm
import orchestrator as orch


def _miss_llm(prompt: str) -> str:
    if "You are an expert lesson planner" in prompt:
        return ('{"topic": "Ohm\'s Law", "language": "en", "total_minutes": 20, '
                '"concepts": [{"id": "c1", "name": "Current", "depth": "standard", '
                '"minutes": 5, "prerequisites": []}]}')
    if "You are a human teacher" in prompt:
        return ('{"concept_id": "c1", "script": "Voltage is the push.", '
                '"visual": {"kind": "none", "payload": ""}, '
                '"question": {"id": "ignored", "concept_id": "c1", '
                '"kind": "short", "prompt": "What is the push called?", '
                '"options": null, "expected": "Voltage"}}')
    if "You are a teacher marking one student answer" in prompt:
        return ('{"correct": false, "misconception": "thinks it is current", '
                '"action": "reexplain", "feedback": "Not quite."}')
    if "You are an exam setter" in prompt:
        return ('{"questions": [{"concept_id": "c1", "kind": "mcq", '
                '"prompt": "What flows?", "options": ["electrons", "protons"], '
                '"expected": "electrons"}]}')
    if "You are a teacher re-explaining" in prompt:
        return ('{"concept_id": "c1", "script": "Think of a doorway.", '
                '"visual": {"kind": "none", "payload": ""}, '
                '"question": {"id": "ignored", "concept_id": "c1", '
                '"kind": "short", "prompt": "Tighter door?", '
                '"options": null, "expected": "less flow"}}')
    if "You are a teacher writing a report card" in prompt:
        return ('{"strong": [], "weak": [], "misconceptions": [], '
                '"revise": [], "next_topic": "Series circuits"}')
    raise AssertionError("unhandled prompt: " + prompt[:60])


def _ok_llm(prompt: str) -> str:
    """Same as _miss_llm, but the marker says the answer is correct."""
    if "You are a teacher marking one student answer" in prompt:
        return ('{"correct": true, "misconception": null, '
                '"action": "continue", "feedback": "Right."}')
    return _miss_llm(prompt)


def _session(session_id: str) -> SessionState:
    plan = LessonPlan(topic="Ohm's Law", language="en", total_minutes=20,
                      concepts=[Concept(id="c1", name="Current",
                                        depth="standard", minutes=5)])
    profile = LearnerProfile(level="beginner", language="en", time_minutes=20)
    session = SessionState(session_id=session_id, profile=profile, plan=plan)
    orch._RUNTIME[session_id] = orch.Runtime(student_id="__miss__")
    return session


class MissCardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        hdb.DB_PATH = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        llm.set_handler(None)
        self.tmp.cleanup()
        for sid in list(orch._RUNTIME):
            if sid.startswith("miss"):
                del orch._RUNTIME[sid]

    def test_lesson_miss_becomes_due_card(self):
        llm.set_handler(_miss_llm)
        session = _session("miss1")
        q = Question(id="q_miss_1", concept_id="c1", kind="short",
                     prompt="What is the push called?", options=None,
                     expected="Voltage")
        orch.answer(session, StudentResponse(question_id=q.id, answer="current"),
                    question=q)

        cards = orch.due_reviews("__miss__")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["card_key"], "question:q_miss_1")
        self.assertEqual(cards[0]["ease"], "again")
        self.assertEqual(cards[0]["interval_days"], 0.0)
        self.assertEqual(cards[0]["source"], "question")

    def test_correct_answer_records_no_card(self):
        llm.set_handler(_ok_llm)
        session = _session("miss2")
        q = Question(id="q_ok_1", concept_id="c1", kind="short",
                     prompt="What is the push called?", options=None,
                     expected="Voltage")
        orch.answer(session, StudentResponse(question_id=q.id, answer="Voltage"),
                    question=q)
        self.assertEqual(orch.due_reviews("__miss__"), [])

    def test_quiz_miss_becomes_due_card(self):
        llm.set_handler(_miss_llm)
        session = _session("miss3")
        orch.submit_quiz(session, {"q1": "protons"})
        cards = orch.due_reviews("__miss__")
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]["card_key"].startswith("question:"))
        self.assertEqual(cards[0]["source"], "quiz")

    def test_mcq_miss_card_back_includes_options(self):
        # An MCQ miss must produce a card whose back carries the choices, so
        # the student can relearn against the actual alternatives.
        llm.set_handler(_miss_llm)
        session = _session("miss4")
        q = Question(id="q_mcq_1", concept_id="c1", kind="mcq",
                     prompt="What flows in a circuit?",
                     options=["electrons", "protons"], expected="electrons")
        orch.answer(session,
                    StudentResponse(question_id=q.id, answer="protons"),
                    question=q)
        cards = orch.due_reviews("__miss__")
        self.assertEqual(len(cards), 1)
        self.assertIn("electrons", cards[0]["back"])
        self.assertIn("protons", cards[0]["back"])

    def test_repeat_miss_upserts_single_card(self):
        # The same question missed in two different lessons (same student)
        # must keep exactly one row: the card is upserted by
        # (student_id, card_key), never duplicated.
        llm.set_handler(_miss_llm)
        for sid in ("miss5a", "miss5b"):
            session = _session(sid)
            q = Question(id="q_dup_1", concept_id="c1", kind="short",
                         prompt="What is the push called?", options=None,
                         expected="Voltage")
            orch.answer(session,
                        StudentResponse(question_id=q.id, answer="current"),
                        question=q)
        cards = orch.due_reviews("__miss__")
        dup = [c for c in cards if c["card_key"] == "question:q_dup_1"]
        self.assertEqual(len(dup), 1)

    def test_miss_without_history_store_degrades_gracefully(self):
        # No persistence layer at all: a miss must not crash the lesson and
        # the due queue stays empty.
        saved = orch.history
        orch.history = None
        try:
            llm.set_handler(_miss_llm)
            session = _session("miss6")
            q = Question(id="q_deg_1", concept_id="c1", kind="short",
                         prompt="What is the push called?", options=None,
                         expected="Voltage")
            orch.answer(session,
                        StudentResponse(question_id=q.id, answer="current"),
                        question=q)
            self.assertEqual(orch.due_reviews("__miss__"), [])
        finally:
            orch.history = saved

    def test_quiz_with_no_answers_records_nothing(self):
        llm.set_handler(_miss_llm)
        session = _session("miss7")
        orch.submit_quiz(session, {})
        self.assertEqual(orch.due_reviews("__miss__"), [])


if __name__ == "__main__":
    unittest.main()