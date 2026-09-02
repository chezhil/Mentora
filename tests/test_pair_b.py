"""Offline tests for Pair B (planner + teacher). Uses a fake LLM handler so
nothing here needs an API key. Each test simulates what Gemini would say.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import re
import unittest

from shared.models import (
    Evaluation,
    LearnerProfile,
    LessonPlan,
    Question,
    SessionState,
    SourceChunk,
    StudentResponse,
)
import llm

prompts_called: list[str] = []


def _plan_canned(prompt: str) -> str:
    advanced = "level: advanced" in prompt
    depths = ["deep"] * 4 if advanced else ["brief", "brief", "standard", "standard"]
    if "offsum" in prompt:
        minutes = [4.0, 4.0, 5.0, 8.3]  # intentionally does NOT sum to 20
    else:
        minutes = [4.0, 4.0, 5.0, 7.0]  # sums to 20 already
    return (
        '{"topic": "Ohm\'s Law", "language": "en", "total_minutes": 20, '
        '"concepts": ['
        '{"name": "Current", "depth": "%s", "minutes": %s, "prerequisites": []},'
        '{"name": "Voltage", "depth": "%s", "minutes": %s, "prerequisites": ["c1"]},'
        '{"name": "Resistance", "depth": "%s", "minutes": %s, "prerequisites": ["c1"]},'
        '{"name": "Ohm\'s Law", "depth": "%s", "minutes": %s, '
        '"prerequisites": ["c2", "c3"]}]}'
        % (
            depths[0], minutes[0], depths[1], minutes[1],
            depths[2], minutes[2], depths[3], minutes[3],
        )
    )


def _language_from(prompt: str) -> str:
    m = re.search(r"lesson language:\s*([A-Za-z_]+)", prompt)
    if not m:
        m = re.search(r"LESSON LANGUAGE:\s*([A-Za-z_]+)", prompt)
    return m.group(1) if m else "en"


def _analogy_from(prompt: str) -> str:
    m = re.search(r"NEW ANALOGY:\s*(.*)", prompt)
    return m.group(1).strip() if m else ""


def fake_llm(prompt: str) -> str:
    prompts_called.append(prompt)
    if "You are an expert lesson planner" in prompt:
        return _plan_canned(prompt)
    if "You are an exam setter" in prompt:
        return (
            '{"questions": ['
            '{"concept_id": "c1", "kind": "mcq", "prompt": "What flows in a circuit?",'
            ' "options": ["electrons", "protons", "light", "heat"], '
            '"expected": "electrons"},'
            '{"concept_id": "c4", "kind": "problem", '
            '"prompt": "V=10, R=5, find I.", "options": null, "expected": "2A"}]}'
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
            '"Data Processing", "Supervised Learning", "Unsupervised Learning", '
            '"Model Evaluation", "Neural Networks"]}'
        )
    if "You are a human teacher" in prompt:
        lang = _language_from(prompt)
        ask = "true" in prompt and "ASK is <<ASK>>" in prompt or "true"
        q = (
            '{"id": "q_AUX_", "concept_id": "c2", "kind": "short", '
            '"prompt": "V+? in %s", "options": null, "expected": "push"}'
        ) % lang if ask else None
        q_json = q if q else "null"
        return (
            '{"concept_id": "c2", "script": "agi in %s: volts are the push",'
            ' "visual": {"kind": "equation", "payload": "V=IR", '
            '"caption": "Ohm\'s law"}, "question": %s, '
            '"used_chunk_indexes": [0, 1]}' % (lang, q_json)
        )
    if "You are a teacher marking one student answer" in prompt:
        return (
            '{"correct": false, '
            '"misconception": "believes current and resistance are directly '
            'proportional", "action": "reexplain", '
            '"feedback": "Not quite — a narrower pipe lets less water through."}'
        )
    if "You are a teacher re-explaining" in prompt:
        analogy = _analogy_from(prompt)
        lang = _language_from(prompt)
        return (
            '{"concept_id": "c3", '
            '"script": "agi in %s: think again using %s", '
            '"visual": {"kind": "diagram", "payload": "graph TD; '
            'A[Pipe] --> B[Less flow]", "caption": null}, '
            '"question": {"id": "q_AUX_", "concept_id": "c3", '
            '"kind": "short", "prompt": "new check", "options": null, '
            '"expected": "decreases"}}' % (lang, analogy)
        )
    raise AssertionError("unhandled prompt: " + prompt[:60])


def _session_with_evals(flags: list[bool]) -> SessionState:
    profile = LearnerProfile(
        level="beginner", language="en", time_minutes=20
    )
    plan = LessonPlan(
        topic="T", language="en", total_minutes=20,
        concepts=[
            {"id": "c1", "name": "Current", "depth": "brief",
             "minutes": 4, "prerequisites": []},
            {"id": "c2", "name": "Voltage", "depth": "brief",
             "minutes": 4, "prerequisites": []},
        ],
    )
    return SessionState(
        session_id="t", profile=profile, plan=plan,
        evaluations=[Evaluation(
            correct=f, misconception=None if f else "some mistake",
            action="continue" if f else "reexplain", feedback="x",
        ) for f in flags],
    )


class PairBTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        llm.set_handler(fake_llm)

    def setUp(self):
        prompts_called.clear()

    def test_1_plan_minutes_sum_exact(self):
        from planner.plan import plan
        profile = LearnerProfile(level="beginner", language="en",
                                 time_minutes=20)
        result = plan("Ohm's Law", profile, doc_id=None)
        self.assertIsInstance(result, LessonPlan)
        total = sum(c.minutes for c in result.concepts)
        self.assertAlmostEqual(total, result.total_minutes, places=6)

    def test_2_plan_corrects_off_budget_from_model(self):
        from planner.plan import plan
        profile = LearnerProfile(level="beginner", language="en",
                                 time_minutes=20)
        result = plan("Ohm's Law offsum", profile)
        total = sum(c.minutes for c in result.concepts)
        self.assertAlmostEqual(total, 20.0, places=6)

    def test_3_plan_depth_follows_level(self):
        from planner.plan import plan
        beginner = plan("Ohm's Law", LearnerProfile(
            level="beginner", language="en", time_minutes=20))
        advanced = plan("Ohm's Law", LearnerProfile(
            level="advanced", language="en", time_minutes=20))
        self.assertTrue(all(c.depth in ("brief", "standard")
                            for c in beginner.concepts))
        self.assertTrue(all(c.depth == "deep" for c in advanced.concepts))

    def test_4_plan_works_with_document_id(self):
        from planner.plan import plan
        profile = LearnerProfile(level="beginner", language="hi",
                                 time_minutes=20)
        result = plan("Chapter 4", profile, doc_id="doc-abc123")
        self.assertGreaterEqual(len(result.concepts), 1)

    def test_5_evaluate_names_misconception(self):
        from teacher.evaluate import evaluate
        from fixtures_data import wrong_question, wrong_answer
        ev = evaluate(wrong_question, wrong_answer)
        self.assertFalse(ev.correct)
        self.assertEqual(ev.action, "reexplain")
        self.assertEqual(
            ev.misconception,
            "believes current and resistance are directly proportional",
        )
        self.assertNotIn("wrong answer", ev.misconception.lower())

    def test_6_evaluate_exact_match_is_continue(self):
        from teacher.evaluate import evaluate
        from fixtures_data import wrong_question
        ev = evaluate(wrong_question, StudentResponse(
            question_id="q3", answer="Current decreases."))
        self.assertTrue(ev.correct)
        self.assertEqual(ev.action, "continue")
        self.assertIsNone(ev.misconception)

    def test_7_reexplain_uses_different_analogy_per_attempt(self):
        from teacher.reexplain import reexplain, ANALOGY_BANK
        from fixtures_data import reexplain_plan
        s1 = reexplain("c3", "misconception", 1, plan=reexplain_plan)
        s2 = reexplain("c3", "misconception", 2, plan=reexplain_plan)
        s3 = reexplain("c3", "misconception", 3, plan=reexplain_plan)
        p1, p2, p3 = prompts_called[0], prompts_called[1], prompts_called[2]
        a1 = re.search(r"NEW ANALOGY:\s*(.*)", p1).group(1)
        a2 = re.search(r"NEW ANALOGY:\s*(.*)", p2).group(1)
        a3 = re.search(r"NEW ANALOGY:\s*(.*)", p3).group(1)
        self.assertEqual(a1, ANALOGY_BANK[0])
        self.assertEqual(a2, ANALOGY_BANK[1])
        self.assertEqual(a3, ANALOGY_BANK[2])
        self.assertTrue(a1 != a2 != a3)
        self.assertTrue(s1.script != s2.script != s3.script)

    def test_8_difficulty_moves_after_two_results(self):
        from teacher.adaptive import difficulty_of
        self.assertEqual(difficulty_of(_session_with_evals([True, True])),
                         "harden")
        self.assertEqual(difficulty_of(_session_with_evals([False, False])),
                         "simplify")
        self.assertEqual(difficulty_of(_session_with_evals([True, False])),
                         "standard")

    def test_9_segment_script_language_and_citations(self):
        from teacher.segment import next_segment
        from fixtures_data import segment_plan, segment_state, segment_chunks
        seg = next_segment(segment_plan, segment_state, segment_chunks)
        self.assertEqual(seg.concept_id, "c2")
        self.assertTrue(seg.script.startswith("agi in en"))
        self.assertEqual(seg.visual.kind, "equation")
        self.assertEqual([c.page for c in seg.citations], [41, 39])

    def test_10_question_cadence(self):
        from teacher.adaptive import should_ask
        state = _session_with_evals([])
        self.assertFalse(should_ask(state))  # nothing taught yet

    def test_11_language_switching_keeps_position(self):
        from teacher.adaptive import switch_language
        state = _session_with_evals([])
        state.current_concept = 2
        switched = switch_language(state, "hinglish")
        self.assertEqual(switched.profile.language, "hinglish")
        self.assertEqual(switched.current_concept, 2)  # position kept
        self.assertEqual(switched.turns[-1].role, "system")

    def test_12_final_quiz_shapes(self):
        from planner.quiz import final_quiz
        from fixtures_data import segment_plan
        qs = final_quiz(segment_plan)
        self.assertIsInstance(qs[0], Question)
        self.assertEqual({q.concept_id for q in qs},
                         {"c1", "c4"})
        self.assertEqual(qs[0].id, "q1")

    def test_13_report_score_and_parts(self):
        from planner.report import build_report
        from fixtures_data import report_session
        report = build_report(report_session)
        self.assertEqual(report.score, 50.0)
        self.assertIn("Current", report.strong)
        self.assertIn("believes current and resistance are directly "
                      "proportional", report.misconceptions)
        self.assertTrue(report.next_topic)

    def test_14_learning_path(self):
        from planner.path import learning_path
        steps = learning_path("Machine Learning")
        self.assertGreaterEqual(len(steps), 4)
        self.assertIsInstance(steps[0], str)


if __name__ == "__main__":
    unittest.main()