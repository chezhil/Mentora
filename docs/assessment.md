# Assessment Methodology

Mentora's assessment answers two different questions at two different
scales, and we keep them apart deliberately:

1. **Per answer** — was this attempt right or wrong, and *why*? Produced by
   `teacher.engine.evaluate`.
2. **Per session** — what did this student actually learn? Produced by
   `planner.report.build_report` at `orchestrator.finish`.

## Per answer: the `Evaluation`

Each student answer goes to `EVALUATE_PROMPT`, which returns an
`Evaluation`:

- `correct` — is the answer right (equivalent phrasing allowed)?
- `misconception` — the concrete misunderstanding that would *produce* this
  answer. This is where the marks live.
- `action` — the next pedagogical move, from exactly one of
  `continue | reexplain | simplify | harden | example`.
- `feedback` — what to actually say, in a warm teacher voice.

### The misconception is the whole point

"Wrong answer" is worth nothing. Section 5 of the brief is graded on naming
the specific mistake, e.g. *"believes current and resistance are directly
proportional"* rather than *"misunderstood"*. So `EVALUATE_PROMPT` is
explicit:

> Never write "wrong answer" or "misunderstood" — NAME the specific mistake
> in the misconception field.

and `smoke_test.py` asserts the contract:

```python
assert ev.misconception, "CONTRACT: misconception must NAME the error when incorrect"
```

The `misconception` field is designed to be copied verbatim into the
session report, so the report's `misconceptions` list never invents new
wording — it reuses the teacher's own named misunderstandings.

### Escalation ladder

The action field drives the adaptation loop, not just a score:

| Wrong streaks | Action | What happens |
|---|---|---|
| 1 wrong | `reexplain` | Re-teach the concept with a different analogy |
| 2 wrong | `simplify` | Drop to a lower level, plainer words |
| correct + effortless | `harden` | Sharper wording / more depth |

Two consecutive `harden`s raise the difficulty; two consecutive
`simplify`/`reexplain`s lower it (see `teacher.engine.next_segment`). This
is the "adapts to the learner" behavior the brief scores.

## Per session: the `LessonReport`

`build_report` computes a score and the `strong` / `weak` /
`misconceptions` / `revise` / `next_topic` lists. The design rules:

- The score is derived from the accumulating `Evaluation`s, so a student who
  needed `simplify` on every concept is not granted a passing score.
- `strong` / `weak` reflect how each concept's evaluations landed
  (`continue`/`harden` → strong; `reexplain`/`simplify` → weak).
- `misconceptions` are copied from the named `Evaluation.misconception`
  values — never AI-invented at report time.
- The quiz at the end of the lesson appends its answers to
  `session.evaluations` exactly like mid-lesson answers, so the report's
  scoring sees *all* of the student's evidence, not just the first few
  evaluations.
- `next_topic` is one concrete topic that naturally follows what was taught,
  so the student always has an onward path.

## Honesty over guessing

A "teacher" that hallucinates is worse than one that admits a gap. That
shows up in two places:

- **Confirming material** — `teacher.engine.next_segment` overwrites the
  model's `citations` with the actual retrieved chunks, so we never present
  a made-up page number as evidence.
- **Out-of-material follow-ups** — when a student asks something the
  retrieved chunks do not cover and the session has an uploaded document,
  `teacher.followup.answer_followup` says plainly it is not in their
  material rather than answering from general knowledge.

## Why two independent steps

A single confidence number is not a teacher. The brief is graded on both
"what did they get wrong" (per answer) and "what should they revise" (per
session), and the two need different evidence. Keeping evaluate() and
build_report() separate means a wrong answer can be acted on immediately
during the lesson while the session-long judgement stays grounded in the
full run of evaluations.
