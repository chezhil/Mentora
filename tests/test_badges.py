"""Study goals + badges: pure catalog evaluation, daily-goal persistence, and
earning badges through the real orchestrator paths (answers, finish, ratings)
against a throwaway SQLite DB and a fake LLM."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.models import (
    Concept, LearnerProfile, LessonPlan, Question, SessionState,
    StudentResponse,
)
import history.badges as badges
import history.db as hdb
import llm
import orchestrator as orch


def _ok_llm(prompt: str) -> str:
    """Every marking is correct; lesson planner / quiz / report handlers kept."""
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
        return ('{"correct": true, "misconception": null, '
                '"action": "continue", "feedback": "Right."}')
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
        return ('{"strong": ["Current"], "weak": [], "misconceptions": [], '
                '"revise": [], "next_topic": "Voltage"}')
    raise AssertionError("unhandled prompt: " + prompt[:60])


def _wrong_llm(prompt: str) -> str:
    if "You are a teacher marking one student answer" in prompt:
        return ('{"correct": false, "misconception": "thinks it is current", '
                '"action": "reexplain", "feedback": "Not quite."}')
    return _ok_llm(prompt)


def _session(session_id: str, student_id: str = "__badges__") -> SessionState:
    plan = LessonPlan(topic="Ohm's Law", language="en", total_minutes=20,
                      concepts=[Concept(id="c1", name="Current",
                                        depth="standard", minutes=5)])
    profile = LearnerProfile(level="beginner", language="en", time_minutes=20)
    session = SessionState(session_id=session_id, profile=profile, plan=plan)
    orch._RUNTIME[session_id] = orch.Runtime(student_id=student_id)
    return session


class BadgeCatalogTest(unittest.TestCase):
    def test_fresh_student_has_everything_locked_and_first_is_next(self):
        out = badges.evaluate({"lessons": 0, "streak": 0, "reviews": 0,
                               "recovery": False, "perfect": False})
        self.assertEqual(out["earned"], [])
        self.assertEqual(len(out["locked"]), 10)
        self.assertEqual(out["next"]["id"], "first_lesson")
        self.assertEqual(out["next"]["remaining"], 1)

    def test_progression_unlocks_in_catalog_order(self):
        # One lesson: first earned, Scholar is next with 4 to go.
        out = badges.evaluate({"lessons": 1, "streak": 0, "reviews": 0,
                               "recovery": False, "perfect": False})
        self.assertEqual([b["id"] for b in out["earned"]], ["first_lesson"])
        self.assertEqual(out["next"]["id"], "scholar")
        self.assertEqual(out["next"]["remaining"], 4)

    def test_streak_and_review_thresholds(self):
        out = badges.evaluate({"lessons": 5, "streak": 7, "reviews": 50,
                               "recovery": False, "perfect": False})
        ids = {b["id"] for b in out["earned"]}
        self.assertIn("scholar", ids)
        self.assertIn("streak_3", ids)
        self.assertIn("streak_7", ids)
        self.assertIn("cards_10", ids)
        self.assertNotIn("streak_30", ids)
        self.assertNotIn("cards_100", ids)
        self.assertNotIn("veteran", ids)
        # Next is the first locked milestone in order (Veteran).
        self.assertEqual(out["next"]["id"], "veteran")
        self.assertEqual(out["next"]["remaining"], 5)

    def test_flag_badges(self):
        out = badges.evaluate({"lessons": 1, "streak": 1, "reviews": 1,
                               "recovery": True, "perfect": True})
        ids = {b["id"] for b in out["earned"]}
        self.assertIn("comeback", ids)
        self.assertIn("flawless", ids)


class DailyGoalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._db = hdb.DB_PATH
        hdb.DB_PATH = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        hdb.DB_PATH = self._db
        self.tmp.cleanup()

    def test_goal_defaults_zero_and_persists(self):
        self.assertEqual(hdb.get_daily_goal("s"), 0)
        hdb.set_daily_goal("s", 15)
        self.assertEqual(hdb.get_daily_goal("s"), 15)
        hdb.set_daily_goal("s", 0)  # clearing is allowed
        self.assertEqual(hdb.get_daily_goal("s"), 0)

    def test_daily_review_count_counts_todays_ratings(self):
        card = {"card_key": "concept:c1", "front": "Current", "back": "Flow",
                "source": "concept"}
        for _ in range(3):
            orch.record_flashcard("s", card, "good")
        self.assertEqual(hdb.review_summary("s")["today"], 3)
        self.assertEqual(orch.goals_today("s"),
                         {"goal": 0, "done": 3})
        orch.set_daily_goal("s", 5)
        self.assertEqual(orch.goals_today("s"), {"goal": 5, "done": 3})


class BadgeEarnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._db = hdb.DB_PATH
        hdb.DB_PATH = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        llm.set_handler(None)
        hdb.DB_PATH = self._db
        self.tmp.cleanup()
        for sid in list(orch._RUNTIME):
            if sid.startswith("bg"):
                del orch._RUNTIME[sid]

    def _q(self, qid: str) -> Question:
        return Question(id=qid, concept_id="c1", kind="short",
                        prompt="What is the push called?", options=None,
                        expected="Voltage")

    def test_perfect_lesson_earns_first_lesson_and_flawless(self):
        llm.set_handler(_ok_llm)
        session = _session("bg1")
        orch.answer(session,
                    StudentResponse(question_id="q1", answer="Voltage"),
                    question=self._q("q1"))
        orch.answer(session,
                    StudentResponse(question_id="q2", answer="Voltage"),
                    question=self._q("q2"))
        orch.finish(session)

        out = orch.badges_for("__badges__")
        ids = {b["id"] for b in out["earned"]}
        self.assertIn("first_lesson", ids)
        self.assertIn("flawless", ids)
        self.assertNotIn("comeback", ids)
        self.assertEqual(out["next"]["id"], "scholar")

    def test_flawless_survives_quiz_overwriting_perfect_finish(self):
        """Regression: finish() saves a 100% report, then the student bombs
        the quiz on the same session and submit_quiz overwrites that report
        row — flawless must stay earned (the perfect fact is recorded when it
        happens, not re-derived from the last-written report)."""
        llm.set_handler(_ok_llm)
        session = _session("bg3")
        orch.answer(session,
                    StudentResponse(question_id="q1", answer="Voltage"),
                    question=self._q("q1"))
        orch.finish(session)
        earned = {b["id"] for b in orch.badges_for("__badges__")["earned"]}
        self.assertIn("flawless", earned)

        llm.set_handler(_wrong_llm)
        quiz_ids = [q.id for q in orch.runtime(session).quiz]
        self.assertTrue(quiz_ids)
        orch.submit_quiz(session, {qid: "wrong on purpose" for qid in quiz_ids})
        earned = {b["id"] for b in orch.badges_for("__badges__")["earned"]}
        self.assertIn("flawless", earned,
                      "a later worse quiz must not un-earn a perfect lesson")

    def test_review_milestone_survives_a_failed_review(self):
        """Regression: the review milestones must count rating events from the
        append-only review log, not SUM(repetitions) — a card's repetition
        counter resets on 'again', which previously dropped the aggregate and
        un-earned the badge despite the reviews having happened."""
        card = {"card_key": "concept:c1", "front": "Current", "back": "Flow",
                "source": "concept"}
        for _ in range(10):
            orch.record_flashcard("__badges__", card, "good")
        earned = {b["id"] for b in orch.badges_for("__badges__")["earned"]}
        self.assertIn("cards_10", earned)

        # Failing the same card resets its repetitions to 0 in SM-2.
        orch.record_flashcard("__badges__", card, "again")
        earned = {b["id"] for b in orch.badges_for("__badges__")["earned"]}
        self.assertIn("cards_10", earned,
                      "an 'again' after ten reviews must not un-earn the badge")
        self.assertEqual(hdb.review_summary("__badges__")["all_time"], 11)

    def test_miss_then_correct_earns_comeback(self):
        llm.set_handler(_wrong_llm)
        session = _session("bg2")
        orch.answer(session,
                    StudentResponse(question_id="q1", answer="current"),
                    question=self._q("q1"))
        llm.set_handler(_ok_llm)
        orch.answer(session,
                    StudentResponse(question_id="q2", answer="Voltage"),
                    question=self._q("q2"))
        ids = {b["id"] for b in orch.badges_for("__badges__")["earned"]}
        self.assertIn("comeback", ids)

    def test_ratings_earn_review_milestones(self):
        card = {"card_key": "concept:c1", "front": "Current", "back": "Flow",
                "source": "concept"}
        for _ in range(10):
            orch.record_flashcard("__badges__", card, "good")
        ids = {b["id"] for b in orch.badges_for("__badges__")["earned"]}
        self.assertIn("cards_10", ids)
        self.assertNotIn("cards_100", ids)


if __name__ == "__main__":
    unittest.main()