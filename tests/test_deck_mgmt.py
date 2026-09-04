"""Deck-management persistence: list every card with stats, edit front/back
without touching scheduling, delete a card with its review history, and the
signature that tells a screen its in-memory deck went stale."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import history.db as hdb


class DeckMgmtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._db = hdb.DB_PATH
        hdb.DB_PATH = Path(self.tmp.name) / "test.db"
        # A card with two ratings: good → 1d, good → 6d.
        hdb.save_flashcard_review("s1", "question:q1", "What is voltage?",
                                  "Voltage", "question", "good")
        hdb.save_flashcard_review("s1", "question:q1", "What is voltage?",
                                  "Voltage", "question", "good")
        hdb.save_flashcard_review("s1", "concept:c1", "Current", "Flow of charge",
                                  "concept", "again")
        hdb.save_flashcard_review("s2", "question:other", "X", "Y",
                                  "quiz", "easy")

    def tearDown(self):
        hdb.DB_PATH = self._db
        self.tmp.cleanup()

    def test_list_returns_every_card_with_stats(self):
        cards = hdb.list_flashcards("s1")
        self.assertEqual(len(cards), 2)
        by_key = {c["card_key"]: c for c in cards}
        q1 = by_key["question:q1"]
        self.assertEqual(q1["source"], "question")
        self.assertLess(q1["ease_factor"], 2.5)   # Goods ease the EF (SM-2)
        self.assertEqual(q1["interval_days"], 6.0)
        self.assertEqual(q1["repetitions"], 2)
        self.assertIsNotNone(q1["last_reviewed"])
        self.assertIsNotNone(q1["next_review"])
        # Other students' cards stay out.
        self.assertNotIn("question:other", by_key)

    def test_edit_changes_text_but_keeps_scheduling_state(self):
        before = {c["card_key"]: c for c in hdb.list_flashcards("s1")}
        self.assertTrue(hdb.update_flashcard("s1", "question:q1",
                                             "What pushes charge?",
                                             "The electromotive force"))
        after = {c["card_key"]: c for c in hdb.list_flashcards("s1")}["question:q1"]
        self.assertEqual(after["front"], "What pushes charge?")
        self.assertEqual(after["back"], "The electromotive force")
        # Scheduling untouched by an edit.
        self.assertEqual(after["ease_factor"], before["question:q1"]["ease_factor"])
        self.assertEqual(after["interval_days"], 6.0)
        self.assertEqual(after["repetitions"], 2)
        self.assertEqual(after["next_review"],
                         before["question:q1"]["next_review"])
        # Editing someone else's card (or a missing key) is a no-op.
        self.assertFalse(hdb.update_flashcard("s1", "question:nope", "a", "b"))
        self.assertFalse(hdb.update_flashcard("s9", "question:q1", "a", "b"))

    def test_delete_removes_card_and_review_history(self):
        self.assertTrue(hdb.delete_flashcard("s1", "question:q1"))
        self.assertFalse(hdb.delete_flashcard("s1", "question:q1"))  # gone
        remaining = hdb.list_flashcards("s1")
        self.assertEqual([c["card_key"] for c in remaining], ["concept:c1"])
        # Review history went with the card.
        conn = hdb._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM flashcard_reviews WHERE student_id='s1'")
        self.assertEqual(cur.fetchone()[0], 1)   # only concept:c1's Again
        conn.close()

    def test_signature_tracks_insert_update_delete(self):
        sig0 = hdb.flashcard_signature("s1")
        self.assertTrue(any(r[0] == "question:q1" for r in sig0))
        # Another rating changes the signature (updated_at moves).
        hdb.save_flashcard_review("s1", "question:q1", "What is voltage?",
                                  "Voltage", "question", "again")
        sig1 = hdb.flashcard_signature("s1")
        self.assertNotEqual(sig0, sig1)
        # An edit changes it too.
        hdb.update_flashcard("s1", "question:q1", "Edited?", "Yes")
        sig2 = hdb.flashcard_signature("s1")
        self.assertNotEqual(sig1, sig2)
        # And so does a delete — a held deck would spot the missing row.
        hdb.delete_flashcard("s1", "question:q1")
        sig3 = hdb.flashcard_signature("s1")
        self.assertNotEqual(sig2, sig3)
        self.assertNotIn(("question:q1",), sig3)


if __name__ == "__main__":
    unittest.main()