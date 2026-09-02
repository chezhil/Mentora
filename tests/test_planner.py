"""Offline tests for planner.plan / planner.quiz / planner.report /
planner.path. Uses a fake LLM so nothing here needs an API key.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from shared.models import (
    Evaluation,
    LearnerProfile,
    Question,
    SessionState,
)
import llm

prompts_called: list[str] = []


def _plan_canned(prompt: str) -> str:
    advanced = "level: advanced" in prompt
    depths = (["deep"] * 4) if advanced else (
        ["brief", "brief", "standard", "standard"])
    if "offsum" in prompt:
        minutes = [4.0, 4.0, 5.0, 8.3]  # intentionally does NOT sum to 20
    else:
        minutes = [4.0, 4.0, 5.0, 7.0]  # sums to 20 already
    return (
        '{"topic": "Ohm\'s Law", "language": "en", "total_minutes": 20, '
        '"concepts": ['
        '{"name": "Current", "depth": "%s", "minutes": %s, "prerequisites": []},'
        '{"name": "Voltage", "depth": "%s", "minutes": %s, '
        '"prerequisites": ["c1"]},'
        '{"name": "Resistance", "depth": "%s", "minutes": %s, '
        '"prerequisites": ["c1"]},'
        '{"name": "Ohm\'s Law", "depth": "%s", "minutes": %s, '
        '"prerequisites": ["c2", "c3"]}]}'
        % (depths[0], minutes[0], depths[1], minutes[1],
           depths[2], minutes[2], depths[3], minutes[3])
    )


def fake_llm(prompt: str) -> str:
    prompts_called.append(prompt)
    if "You are an expert lesson planner" in prompt:
        return _plan_canned(prompt)
    if "You are an exam setter" in prompt:
        return (
            '{"questions": ['
            '{"concept_id": "c1", "kind": "mcq", "prompt": "What flows in a '
            'circuit?", "options": ["electrons", "protons", "light", "heat"], '
            '"expected": "electrons"},'
            '{"concept_id": "c4", "kind": "problem", '
            '"prompt": "V=10, R=5, find I.", "options": null, '
            '"expected": "2A"}]}'
        )
    if "You are a teacher writing a report card" in prompt:
        return (
            '{"strong": ["Current"], "weak": ["Resistance"], '
            '"misconceptions": ["believes current and resistance are '
            'directly proportional"], "revise": ["Ohm\'s Law"], '
            '"next_topic": "Series and parallel circuits"}'
        )
    if "You are a curriculum designer" in prompt:
        return (
            '{"steps": ["Python Fundamentals", "Mathematics for ML", '
            '"Data Processing", "Supervised Learning", "Unsupervised '
            'Learning", "Model Evaluation", "Neural Networks"]}'
        )
    raise AssertionError("unhandled prompt: " + prompt[:60])


def _profile(**kw) -> LearnerProfile:
    defaults = dict(level="beginner", language="en", time_minutes=20)
    defaults.update(kw)
    return LearnerProfile(**defaults)


REPORT_STATE = SessionState.model_validate({
    "session_id": "s1",
    "profile": {
        "level": "beginner", "language": "en", "time_minutes": 20,
        "goal": "understand Ohm's law", "known_concepts": [],
        "weak_concepts": ["resistance"],
    },
    "plan": {
        "topic": "Electricity Basics", "language": "en", "total_minutes": 20,
        "concepts": [
            {"id": "c1", "name": "Current", "depth": "brief",
             "minutes": 4, "prerequisites": []},
            {"id": "c2", "name": "Voltage", "depth": "brief",
             "minutes": 5, "prerequisites": ["c1"]},
            {"id": "c3", "name": "Resistance", "depth": "standard",
             "minutes": 5, "prerequisites": ["c1"]},
            {"id": "c4", "name": "Ohm's Law", "depth": "standard",
             "minutes": 6, "prerequisites": ["c2", "c3"]},
        ],
    },
    "turns": [
        {"role": "teacher", "content": "Voltage is the push.",
         "concept_id": "c2", "timestamp": "2026-09-02T10:00:00"},
    ],
    "current_concept": 0,
    "evaluations": [
        {"correct": True, "misconception": None, "action": "continue",
         "feedback": "Good."},
        {"correct": False, "misconception": "inverted the relationship",
         "action": "reexplain", "feedback": "Not quite."},
    ],
})


class PlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        llm.set_handler(fake_llm)

    def setUp(self):
        prompts_called.clear()

    def test_plan_minutes_sum_exact(self):
        from planner.plan import plan
        result = plan("Ohm's Law", _profile())
        total = sum(c.minutes for c in result.concepts)
        self.assertAlmostEqual(total, result.total_minutes, places=6)

    def test_plan_corrects_off_budget_from_model(self):
        from planner.plan import plan
        result = plan("Ohm's Law offsum", _profile())
        total = sum(c.minutes for c in result.concepts)
        self.assertAlmostEqual(total, 20.0, places=6)

    def test_plan_depth_follows_level(self):
        from planner.plan import plan
        beginner = plan("Ohm's Law", _profile(level="beginner"))
        advanced = plan("Ohm's Law", _profile(level="advanced"))
        self.assertTrue(all(c.depth in ("brief", "standard")
                            for c in beginner.concepts))
        self.assertTrue(all(c.depth == "deep" for c in advanced.concepts))

    def test_plan_works_with_and_without_document(self):
        from planner.plan import plan
        with_doc = plan("Chapter 4", _profile(),
                        doc_id="doc-abc123")
        no_doc = plan("Chapter 4", _profile())
        self.assertGreaterEqual(len(with_doc.concepts), 1)
        self.assertGreaterEqual(len(no_doc.concepts), 1)

    def test_plan_sets_prerequisites(self):
        from planner.plan import plan
        result = plan("Ohm's Law", _profile())
        by_id = {c.id: c for c in result.concepts}
        self.assertEqual(by_id["c1"].prerequisites, [])
        self.assertEqual(by_id["c2"].prerequisites, ["c1"])

    def test_final_quiz_shapes(self):
        from planner.quiz import final_quiz
        qs = final_quiz(REPORT_STATE.plan)
        self.assertIsInstance(qs[0], Question)
        self.assertEqual(qs[0].id, "q1")
        self.assertIn(qs[0].concept_id,
                      {c.id for c in REPORT_STATE.plan.concepts})

    def test_report_score_and_parts(self):
        from planner.report import build_report
        report = build_report(REPORT_STATE)
        self.assertEqual(report.score, 50.0)
        self.assertIn("Current", report.strong)
        self.assertIn("believes current and resistance are directly "
                      "proportional", report.misconceptions)
        self.assertTrue(report.next_topic)

    def test_learning_path(self):
        from planner.path import learning_path
        steps = learning_path("Machine Learning")
        self.assertGreaterEqual(len(steps), 4)
        self.assertIsInstance(steps[0], str)


if __name__ == "__main__":
    unittest.main()