# Prompt & Agent Architecture

Every model call in Mentora goes through a single, thin agent design: one
prompt template per job, filled with `prompts.fill(...)`, sent to Gemini via
`llm.generate_json`, and validated into a `shared/models` shape. There is no
chain-of-thought scaffold and no tool-use layer — each step is one focused
call, which keeps cost low on the free Gemini tier and keeps failures simple
to debug.

## The one rule that holds it together

All prompts live in `prompts.py`, as named constants with `<<PLACEHOLDER>>`
markers. Because the JSON examples we ask the model for contain braces, the
placeholders use `<<NAME>>` instead of `{name}` so `format()` braces never
clash with JSON (see the module docstring). Fill them with `fill(PROMPT,
name=value, ...)`, which does a literal string replace.

Every prompt ends with the same instruction: return ONLY a JSON object with
no markdown fences and no explanation. `llm._parse_json` strips code fences
anyway, then `json.loads`es the object (falling back to a raw-decode scan if
Gemini wraps it in prose). `generate_json` retries once on a parse failure.

## The prompts we ship

| Prompt | Where | What one call produces |
|---|---|---|
| `PLAN_PROMPT` | `planner.plan` | The `LessonPlan` for the session |
| `FINAL_QUIZ_PROMPT` | `planner.quiz` | The end-of-lesson questions |
| `REPORT_PROMPT` | `planner.report` | The `LessonReport` card |
| `LEARNING_PATH_PROMPT` | `planner.path` | The ordered `steps` list |
| `SEGMENT_PROMPT` | `teacher.engine.next_segment` | One `TeachingSegment` |
| `EVALUATE_PROMPT` | `teacher.engine.evaluate` | One `Evaluation` |
| `REEXPLAIN_PROMPT` | `teacher.engine.reexplain` | One re-teaching `TeachingSegment` |
| `FOLLOWUP_PROMPT` | `teacher.followup` | The spoken reply to a student's own question |

## The teacher agent loop

Within a segment the "agent" is not a free-running LLM — it is the
orchestrator deciding which prompt to fire next based on the last
`Evaluation.action`:

1. **segment** — teach one idea (`next_segment`), ask one `Question`.
2. **evaluate** — judge the answer, NAME the misconception, pick an action
   (`continue | reexplain | simplify | harden | example`).
3. **adapt** — two `harden`s raise difficulty; two `simplify`/`reexplain`s
   lower it or re-teach with a rotating analogy.
4. **followup** — a student's own mid-lesson question is answered separately
   (`answer_followup`) so it never derails the main loop.

Each prompt is handed just the context it needs — the last few `Turn`s and
the retrieved `SourceChunk`s — rather than the whole session, which is what
keeps the token budget inside the rate limit on a 60-minute lesson. The
context trim is tuned in `shared/config.py` (`CONTEXT_FULL_TURNS`,
`CONTEXT_SUMMARY_MAX_CHARS`).

## Deterministic enforcement after the call

Trusting the model is not enough, so each caller hard-fixes what must be
true regardless of what Gemini guessed:

- `next_segment` overwrites `citations` with the real retrieved chunks, so we
  never ship a hallucinated page number.
- `next_segment` and `reexplain` run the script through `fit_script`, which
  trims to the avatar budget at a sentence boundary, because an over-long
  narration makes Pair C refuse to render a video at all.
- `planner.plan._fit_budget` rescales concept minutes so they sum exactly to
  `profile.time_minutes`.
- `wiring.py` enforces the same contract at the seams: it resolves each
  function to the real module or a stub per call, so a half-finished piece
  never crashes the lesson.

## Why this shape

The work-split is by file, not feature, so prompts are small, owner-stable
units: `prompts.py` is one person's file, each planner/teacher module is one
person's file, and the interface between them is fixed by `CONTRACT.txt`.
Keeping the model calls JSON-in/JSON-out through `llm.py` means every
step is independently testable offline with `set_handler` or
`AI_TEACHER_MOCK` — no live API needed.
