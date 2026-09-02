"""End-to-end run of the orchestrator against whatever wiring resolves to.

Run it after every change:

    python smoke_test.py

It teaches a whole lesson to a fake student who gets the first question wrong
twice and everything else right, so the re-explain path, the analogy change
and the escalation to 'simplify' all get exercised.
"""

import orchestrator as orch
import wiring
from shared.models import LearnerProfile, StudentResponse


def main() -> int:
    print("wiring:")
    for pair, state in wiring.summary().items():
        print(f"  {pair:22} {state}")
    print()

    profile = LearnerProfile(
        level="beginner",
        language="hi",
        time_minutes=20,
        goal="pass the unit test on electricity",
    )

    session = orch.start_session("Ohm's Law", profile, "fixtures/sample.pdf")
    print(f"session {session.session_id}  doc={session.doc_id}")
    print(f"plan: {len(session.plan.concepts)} concepts, "
          f"{sum(c.minutes for c in session.plan.concepts):g} min total")
    assert sum(c.minutes for c in session.plan.concepts) == profile.time_minutes, \
        "CONTRACT: concept minutes must sum to profile.time_minutes"
    print()

    wrong_answers = ["current increases", "it goes up"]
    guard = 0

    while not orch.is_finished(session) and guard < 25:
        guard += 1
        seg = orch.step(session)
        media = orch.media_for(session, seg)

        print(f"[{seg.concept_id}] {seg.script[:78]}")
        print(f"     visual={seg.visual.kind:11} png={bool(media.visual_png)} "
              f"wav={bool(media.audio_wav)} mp4={bool(media.video_mp4)} "
              f"citations={len(seg.citations)}")
        for note in media.notes:
            print(f"     note: {note}")

        if seg.question is None:
            continue

        reply = wrong_answers.pop(0) if wrong_answers else "it decreases"
        ev = orch.answer(session, StudentResponse(
            question_id=seg.question.id, answer=reply))
        panel = orch.runtime(session).panel

        print(f"     student: {reply!r} -> correct={ev.correct}")
        if not ev.correct:
            assert ev.misconception, \
                "CONTRACT: misconception must NAME the error when incorrect"
            print(f"     misconception: {ev.misconception}")
            print(f"     pair B said {panel.action_from_pair_b!r}, "
                  f"we did {panel.action_taken!r} "
                  f"(attempt {panel.attempt}"
                  f"{', escalated' if panel.escalated else ''})")
            if panel.analogy:
                print(f"     analogy: {panel.analogy}")
        print()

    report = orch.finish(session)
    print(f"score {report.score}")
    print(f"strong        {report.strong}")
    print(f"weak          {report.weak}")
    print(f"misconceptions{report.misconceptions}")
    print(f"next topic    {report.next_topic}")
    print(f"turns stored  {len(session.turns)}")

    # The empty-list rule — the strongest grounding evidence we have.
    off_topic = wiring.retrieve(session.doc_id, "who won the 1998 world cup", 4)
    assert off_topic == [], "CONTRACT: retrieve() must return [] when off-topic"
    print(f"off-topic query returned {off_topic} (correct)")

    trimmed = orch.trim_state(session)
    print(f"context budget: {len(session.turns)} turns -> "
          f"{len(trimmed.turns)} sent to the LLM")

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
