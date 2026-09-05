# Mentora — AI Teacher

Team Winners · Yenepoya, Bangalore · AI Innovation Hackathon 2026, Round 2

An AI teacher that reads your material, plans a lesson for your level and the
time you have, teaches it with an avatar and visuals, asks you questions,
works out *why* you got something wrong, and changes its approach.

## Problem statement

Digital learning is mostly pre-recorded lectures or a text chatbot. Neither
watches the student. A recorded lecture cannot notice that you did not follow
the third step; a chatbot answers what you asked and never asks anything back.
What is missing is the thing a teacher actually does: read the learner, plan a
route, explain, check, and change the plan when the check fails.

Mentora takes a document or a bare topic and teaches it — as a video lesson
with a spoken, animated teacher, questions during the lesson, and a route that
changes when the answers do.

## Solution overview

    upload or topic
        -> ingest and chunk, embed into a vector store        (Pair A)
        -> plan: concepts, order, minutes each                (Pair B)
        -> per concept: retrieve, teach, draw, narrate, ask   (Pair B + C)
        -> evaluate the answer, name the misconception
        -> continue / re-explain / simplify / harden
        -> final quiz, scored report, what to revise next

Each teaching segment becomes an MP4: a matplotlib board whose elements appear
as the narration reaches them, with the teacher drawn into the frame rather
than laid over it. The same engine drives two surfaces — a web app and a
Streamlit app — so neither is a mock of the other.

## Key features

- **Learns from your material.** PDF, DOCX, PPTX, TXT. Chunked on sentence
  boundaries, embedded with BGE-M3, retrieved per concept, and cited on the
  segment that used it.
- **Or from nothing at all.** Name a topic and it plans the lesson anyway.
- **Teaches, rather than answers.** Explains, draws, questions, marks, names
  the misconception, and re-teaches with a different analogy before moving on.
- **Adapts.** Two wrong answers simplify the lesson; two quick right ones
  harden it. The student's chosen level sets the starting point.
- **Fits the time.** 1 to 60 minutes changes how many concepts are covered and
  how deep each goes.
- **Eighteen languages**, each with a neural voice and the font its script
  needs — narration, board and questions all in the chosen language.
- **A teacher you can see.** Six characters on one SVG rig, lip-synced to the
  narration, glancing at each element as it appears.
- **Talk to it.** Voice mode: speak, and it answers aloud and draws while it
  does.
- **Remembers.** Per-student history, flashcards on an SM-2 schedule,
  transcripts, and a report after every lesson.
- **A classroom view.** Teachers see the class average, the reteach list —
  misconceptions more than one student holds — and a row per student.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "GROQ_API_KEY=your-key-here" > .env     # free, see "Which LLM provider"
.venv/bin/streamlit run app.py
```

Without that key the app boots and the UI works, but the first lesson fails:
every provider needs either a key or a local model server. Groq's is free and
takes a minute to create.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Two roles

The setup screen asks who you are before it asks anything else.

**Student** — upload material or name a topic, get taught, get questioned,
get a report.

**Teacher** — opens on the classroom: how the class scored, which
misconceptions more than one student holds (the reteach list), and a row per
student so nobody disappears inside the average. Underneath it is the same
setup form, so a teacher can preview exactly the lesson the class will get.
Every number is counted from reports in `mentora.db`; nothing is generated.

## Languages

Eighteen, defined once in `shared/languages.py` — voice, font and script
direction together, so a language cannot be added that speaks but cannot draw
its own alphabet.

**Indian:** Hindi, Hinglish, Bengali, Marathi, Tamil, Telugu, Kannada,
Malayalam, Gujarati, Urdu
**Other:** English, Arabic, Spanish, French, German, Portuguese, Russian,
Indonesian

Picking one changes **the whole interface**, on the same click, not just the
teaching — `ui/i18n.py` holds all 83 strings in all 18. Urdu and Arabic render
right-to-left. The picker also works mid-lesson: the interface changes
immediately and the teaching follows from the next segment.

### Voice

Two backends, both free, no key anywhere:

| Backend | Covers | Notes |
|---|---|---|
| edge-tts | all 18 | Neural voices. Leads everywhere. Needs a network connection. |
| Piper | en, hi, te | Local and offline. The fallback, for when the network is not there. |

`MENTORA_VOICE=male` switches voice, `TTS_PROVIDER=piper` forces offline. If
both fail the lesson continues with a silent placeholder rather than stopping.

Piper voices are too big to commit; `setup_assets.py` fetches them, or:

```bash
D=prompt_101/media_pipeline/piper_models; mkdir -p $D
B=https://huggingface.co/rhasspy/piper-voices/resolve/main
curl -sL -o $D/en_US-lessac-medium.onnx      $B/en/en_US/lessac/medium/en_US-lessac-medium.onnx
curl -sL -o $D/en_US-lessac-medium.onnx.json $B/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
curl -sL -o $D/hi_IN-pratham-medium.onnx      $B/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx
curl -sL -o $D/hi_IN-pratham-medium.onnx.json $B/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx.json
```

### Downloads (required for video and voice)

Model weights are ~500MB and cannot live in git, so a fresh clone starts
without them. One command:

```bash
.venv/bin/python setup_assets.py
```

Safe to re-run; anything already present is skipped. Without it the app still
runs, but **the avatar is a still image and narration is silent** — which is
usually why video "does not work" on a new clone. The sidebar warns when they
are missing.

Wav2Lip needs a REAL front-facing photograph at `assets/teacher.jpg` — a drawn
or stylised avatar will not register with the face detector. If detection picks
the wrong face, set `MENTORA_FACE_BOX="x1,y1,x2,y2"` to skip it.
`MENTORA_LOCAL_AVATAR=0` falls back to a still placeholder card instead.

### Which LLM provider

Groq's free tier is thousands per day and serves Llama 3.3 70B. Get a key at
**https://console.groq.com/keys** — sign in with Google or GitHub, click
*Create API Key*, copy it once (it is shown only once).

Then either paste it into the ⚙️ APIs panel in the sidebar, or:

```bash
echo "AI_TEACHER_PROVIDER=groq" >> .env
echo "GROQ_API_KEY=your-key-here" >> .env
```

`AI_TEACHER_PROVIDER` accepts `groq` (the default) or `ollama` — the only two.
Groq is hosted and needs a free key; Ollama runs on your own machine with no
key and no limit, so install it and `ollama pull llama3.1:8b`.

Responses are cached in `.cache/llm` keyed on the exact prompt and model, so
repeating a lesson costs nothing. `AI_TEACHER_CACHE=0` disables it.

### Keys

| Variable | Without it |
|---|---|
| `GROQ_API_KEY` | Pair B cannot run at all. `AI_TEACHER_MOCK=mocks/fixture_mock.json` replays canned answers instead. |

Check the whole loop without a browser:

```bash
.venv/bin/python smoke_test.py
```

## Where things are

| Path | Owner | What it is |
|---|---|---|
| `shared/models.py` | Chezhil | The data shapes from `CONTRACT.txt`. **Nobody edits this alone.** |
| `shared/config.py` | Chezhil | Orchestrator dials — context budget, attempt cap |
| `ingest/config.py` | Chezhil | `MIN_SCORE` — the retrieval threshold |
| `ingest/` (rest) | Utkarsh | Loading, chunking, embedding, retrieval |
| `history/` | Utkarsh | SQLite persistence |
| `orchestrator.py` | Chezhil | `start_session` `step` `answer` `finish` |
| `app.py` | Chezhil | Streamlit — the demo app, tabs + the adaptation panel |
| `wiring.py` | Chezhil | Picks the real module or the stub, per function |
| `stubs/` | Chezhil | Fake Pair B / Pair C / ingest, so nobody is blocked |
| `planner/` `teacher/` | Pair B | Jyothi + Naman |
| `visuals/` `media/` | Pair C | Santosh + Hamza |
| `shared/languages.py` | — | Every language: voice, font, direction. One place. |
| `ui/i18n.py` | — | The interface in 18 languages |
| `ui/style.css` | Frontend | The brutalist styling. Read the rules at the top. |
| `screens/classroom.py` | — | The teacher's view of the class |
| `prompt_101/media_pipeline/renderers/design.py` | — | The house style the visuals are drawn in |

### Two entry points

`app.py` is the demo. `app_v2.py` plus `pages/` is the frontend team's
multipage rebuild — run that one with `streamlit run app_v2.py`. Streamlit
finds a `pages/` directory from wherever the running script lives, and both
scripts are in the repo root, so `app.py` passes `hide_nav=True` to
`ui.apply_theme()` to keep app_v2's navigation out of its sidebar. `app_v2.py`
must not pass it.

## How the stubs work

`wiring.py` tries to import each real module and falls back to `stubs/`
per function. Nothing needs switching on: the moment
`from ingest.pipeline import retrieve` works, the app uses it.

The sidebar shows which is which, live, so we always know what we are
demoing.

## Docs for the team

- `CONTRACT.txt` — the interfaces. Authoritative.
- `PAIR_A_SPLIT.txt` — how Chezhil and Utkarsh divide Pair A
- `GIT_WORKFLOW.txt` — branch rules. Nobody commits to main.

## Known limitations

- **A model is required.** Groq's free tier is capped daily; when it runs out
  the app degrades with an explanation rather than failing silently, but it
  cannot teach. Ollama runs locally with no cap and no key.
- **Voice input is Chrome-only.** It uses the browser's SpeechRecognition,
  which Safari and Firefox do not implement. Those browsers get the typed
  fallback and still hear the reply.
- **Spoken output uses the platform's voices.** Quality varies by OS, and a
  language with no installed voice falls back to the default rather than
  pretending.
- **A segment is capped at 60 seconds of narration.** Longer scripts produce
  audio and a still image instead of a board video.
- **The multi-day learning path and the 7-day planner are in the Streamlit
  app only.** The engine supports them; the web UI does not expose them yet.
- **Wav2Lip weights and Piper voices are not in the repository.** They are
  large; `setup_assets.py` fetches them. Without them the SVG teacher is used,
  which is the default path anyway.
- **Sessions live in memory.** Restarting the server signs everyone out.
- **Single-machine deployment.** SQLite and an in-process job runner are fine
  for a classroom, not for concurrent load.
