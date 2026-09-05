"""Drive the real Streamlit app through the answer flow (setup → lesson →
wrong answer) with Streamlit's AppTest, against the offline mock LLM and a
throwaway SQLite DB.

This is the closest thing to clicking the app: it exercises app.py's actual
form handling, the busy/done-token double-click guard, and the miss→card
recording in orchestrator.answer() — the real entry point of the feature.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import history.db as hdb


class AppAnswerFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_env = {k: os.environ.get(k) for k in (
            "AI_TEACHER_MOCK", "AI_TEACHER_PROVIDER", "GROQ_API_KEY")}
        os.environ["AI_TEACHER_MOCK"] = "mocks/fixture_mock.json"
        os.environ["AI_TEACHER_PROVIDER"] = "local"
        os.environ["GROQ_API_KEY"] = "test"

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._db = hdb.DB_PATH
        hdb.DB_PATH = Path(self.tmp.name) / "app.db"

    def tearDown(self):
        hdb.DB_PATH = self._db
        self.tmp.cleanup()

    def _start_lesson(self):
        from streamlit.testing.v1 import AppTest
        app_path = str(Path(__file__).resolve().parent.parent / "app.py")
        at = AppTest.from_file(app_path, default_timeout=180)
        at.run()
        topic = next(t for t in at.text_input if "want to learn" in t.label)
        topic.set_value("Ohm's law")
        at.run()
        start = next(b for b in at.button if b.label.upper() == "START LESSON")
        start.click()
        at.run()
        return at

    def test_wrong_answer_writes_due_card_through_the_app(self):
        at = self._start_lesson()
        self.assertEqual(at.exception, [], "lesson start must not raise")

        answer = next(t for t in at.text_input if t.label == "Your answer")
        answer.set_value("current")
        at.run()
        next(b for b in at.button if b.label.upper() == "ANSWER").click()
        at.run()
        self.assertEqual(at.exception, [], "marking a wrong answer must not raise")
        # The marking lock is released — the answer flow is not wedged.
        self.assertIsNone(at.session_state["busy"])

        cards = hdb.due_flashcards("student")
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]["card_key"].startswith("question:"))
        self.assertEqual(cards[0]["ease"], "again")
        self.assertEqual(cards[0]["interval_days"], 0.0)

    def test_stale_busy_lock_does_not_wedge_the_answer_flow(self):
        """Regression for the 'already being marked' wedge: a lock left behind
        by a killed run must not block the next answer. Any busy flag present
        when a new run reaches the answer form is stale (a run that completed
        normally always releases before ending)."""
        at = self._start_lesson()
        self.assertEqual(at.exception, [], "lesson start must not raise")

        at.session_state["busy"] = "answer:stale-lock"
        answer = next(t for t in at.text_input if t.label == "Your answer")
        answer.set_value("current")
        at.run()
        next(b for b in at.button if b.label.upper() == "ANSWER").click()
        at.run()

        self.assertEqual(at.exception, [], "a stale lock must not raise")
        self.assertIsNone(at.session_state["busy"])
        self.assertEqual(len(hdb.due_flashcards("student")), 1)

    def test_dashboard_due_queue_rates_card_out_of_the_queue(self):
        """The Path dashboard lists the due card (the miss from the lesson)
        and rating it Good there moves it out of the queue — the loop closes
        without leaving the dashboard."""
        at = self._start_lesson()
        self.assertEqual(at.exception, [], "lesson start must not raise")

        answer = next(t for t in at.text_input if t.label == "Your answer")
        answer.set_value("current")
        at.run()
        next(b for b in at.button if b.label.upper() == "ANSWER").click()
        at.run()
        self.assertEqual(at.exception, [], "marking a wrong answer must not raise")

        cards = hdb.due_flashcards("student")
        self.assertEqual(len(cards), 1)
        key = cards[0]["card_key"]

        # The dashboard renders the actionable due queue for that card.
        self.assertTrue(
            any("Due for review" in m.value for m in at.markdown),
            "Path dashboard should list the due card under 'Due for review'",
        )

        # Flip and rate it Good, entirely inside the queue widget.
        at.button(key=f"pd_queue:{key}:flip").click().run()
        at.button(key=f"pd_queue:{key}:rate_good").click().run()
        self.assertEqual(at.exception, [], "rating from the queue must not raise")
        self.assertEqual(hdb.due_flashcards("student"), [],
                         "Good schedules the card for later — out of the due queue")
        self.assertFalse(
            any("Due for review" in m.value for m in at.markdown),
            "the queue heading should disappear once nothing is due",
        )

    def _full_correct_llm(self, prompt: str) -> str:
        """A correct-answer grading override on top of the canned fixture, so
        the app can run a whole lesson offline (every mark advances)."""
        import json
        if "You are a teacher marking one student answer" in prompt:
            return json.dumps({"correct": True, "misconception": None,
                               "action": "continue", "feedback": "Right."})
        with open("mocks/fixture_mock.json", encoding="utf-8") as f:
            fixture = json.load(f)
        for key, value in fixture.items():
            if key in prompt:
                return value if isinstance(value, str) else json.dumps(value)
        raise AssertionError("unhandled prompt: " + prompt[:60])

    def _answer_questions(self, at, limit: int = 8):
        """Answer every lesson question correctly; stops when the lesson ends
        or the answer box disappears."""
        for _ in range(limit):
            box = [t for t in at.text_input if t.label == "Your answer"]
            btn = [b for b in at.button if b.label.upper() == "ANSWER"]
            if not box or not btn:
                break
            box[0].set_value("2A")
            at.run()
            btn = [b for b in at.button if b.label.upper() == "ANSWER"]
            if not btn:
                break
            btn[0].click()
            at.run()
            if any("Finish and see my report" in b.label for b in at.button):
                break

    def test_full_lesson_finish_earns_badges_on_the_dashboard(self):
        """The whole badge loop through the real app: answer a lesson with the
        correct-grading offline handler, finish it, and the dashboard renders
        the earned 'First lesson' and 'Flawless' badges (report scored 100%)."""
        import llm
        llm.set_handler(self._full_correct_llm)
        try:
            at = self._start_lesson()
            self.assertEqual(at.exception, [], "lesson start must not raise")
            self._answer_questions(at)
            self.assertEqual(at.exception, [], "answering the lesson must not raise")

            finish = [b for b in at.button if "Finish and see my report" in b.label]
            self.assertTrue(finish, "all concepts answered — the finish button appears")
            finish[0].click()
            at.run()
            self.assertEqual(at.exception, [], "finishing the lesson must not raise")

            # The report row landed with a perfect score and the badges follow.
            import orchestrator as orch
            out = orch.badges_for("student")
            earned = {b["id"] for b in out["earned"]}
            self.assertIn("first_lesson", earned)
            self.assertIn("flawless", earned)
            self.assertEqual(out["next"]["id"], "scholar")

            # The dashboard actually renders the earned badge row.
            self.assertTrue(
                any("First lesson" in m.value and "Flawless" in m.value
                    for m in at.markdown),
                "earned badges render on the Path dashboard",
            )
        finally:
            llm.set_handler(None)

    def test_daily_goal_persists_and_tracks_a_review(self):
        """Daily goal on the real surface: set 5 cards/day, miss a lesson
        question, and rating the resulting card Good from the due queue moves
        today's count to 1 — shown as the goal progress caption."""
        at = self._start_lesson()
        self.assertEqual(at.exception, [], "lesson start must not raise")

        goal = next(n for n in at.number_input if n.key == "dg_student")
        goal.set_value(5)
        at.run()
        at.run()  # the goal write reruns the script once more
        import orchestrator as orch
        self.assertEqual(orch.goals_today("student")["goal"], 5)

        answer = next(t for t in at.text_input if t.label == "Your answer")
        answer.set_value("current")
        at.run()
        next(b for b in at.button if b.label.upper() == "ANSWER").click()
        at.run()
        self.assertEqual(at.exception, [], "marking must not raise")

        cards = hdb.due_flashcards("student")
        self.assertEqual(len(cards), 1)
        key = cards[0]["card_key"]
        at.button(key=f"pd_queue:{key}:flip").click().run()
        at.button(key=f"pd_queue:{key}:rate_good").click().run()
        self.assertEqual(at.exception, [], "rating from the queue must not raise")

        # done=2: the lesson miss auto-logs an "again" review (the card's SRS
        # state change — the same event a self-rated miss records) and the
        # queue rating Good is the second.
        self.assertEqual(orch.goals_today("student"), {"goal": 5, "done": 2})
        self.assertTrue(
            any("2 of 5 cards reviewed today" in c.value for c in at.caption),
            "the goal caption reflects today's reviews",
        )

        # The three legibility surfaces render on the real app:
        # (1) the goal's 7-day memory strip on the dashboard (2 < goal 5, so
        #     today does not count as met yet),
        self.assertTrue(
            any("Goal met 0 of the last 7 days" in c.value for c in at.caption),
            "the 7-day memory strip renders on the dashboard",
        )
        # (2) the compact goal chip on the Flashcards tab header — same
        #     goals_today seam as the dashboard, no second source of truth,
        self.assertTrue(
            any(c.value == "🎯 2/5 today" for c in at.caption),
            "the Flashcards tab shows the live goal chip",
        )
        # (3) a locked badge explains how to earn it with live progress
        #     (streak today is 1, so On a roll shows 1/3).
        self.assertTrue(
            any("On a roll" in c.value and "Study 3 days in a row" in c.value
                and "1/3" in c.value for c in at.caption),
            "locked badges show how-to-earn plus live n/m progress",
        )

    def test_browse_edits_then_deletes_a_card(self):
        """Deck management on the real surface: Browse lists the missed card,
        Edit rewrites front/back in the DB without touching scheduling, and
        Delete removes the card and its review history."""
        at = self._start_lesson()
        self.assertEqual(at.exception, [], "lesson start must not raise")

        answer = next(t for t in at.text_input if t.label == "Your answer")
        answer.set_value("current")
        at.run()
        next(b for b in at.button if b.label.upper() == "ANSWER").click()
        at.run()
        self.assertEqual(at.exception, [], "marking a wrong answer must not raise")

        cards = hdb.due_flashcards("student")
        self.assertEqual(len(cards), 1)
        key = cards[0]["card_key"]

        # Switch the Flashcards view to Browse.
        view = next(r for r in at.radio if r.key == "fc_view_student")
        view.set_value("Browse deck")
        at.run()
        self.assertEqual(at.exception, [], "browse view must not raise")

        # --- Edit --------------------------------------------------------
        at.button(key=f"browse_edit_btn:{key}").click().run()
        at.text_area(key=f"browse_front:{key}").set_value(
            "What is the push that moves charge?")
        at.text_area(key=f"browse_back:{key}").set_value(
            "Voltage — the electromotive push.")
        at.run()
        at.button(key=f"browse_save:{key}").click().run()
        self.assertEqual(at.exception, [], "saving an edit must not raise")

        edited = hdb.list_flashcards("student")
        self.assertEqual(len(edited), 1)
        self.assertEqual(edited[0]["front"], "What is the push that moves charge?")
        self.assertEqual(edited[0]["back"], "Voltage — the electromotive push.")
        # Scheduling survived the edit (interval 0 from the Again miss).
        self.assertEqual(edited[0]["interval_days"], 0.0)
        self.assertEqual(edited[0]["ease"], "again")

        # --- Delete ------------------------------------------------------
        at.button(key=f"browse_del_btn:{key}").click().run()
        at.button(key=f"browse_del_yes:{key}").click().run()
        self.assertEqual(at.exception, [], "deleting a card must not raise")
        self.assertEqual(hdb.list_flashcards("student"), [])
        conn = hdb._get_connection()
        n = conn.execute("SELECT COUNT(*) FROM flashcard_reviews "
                         "WHERE student_id='student'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 0, "review history is deleted with the card")


if __name__ == "__main__":
    unittest.main()