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

## System architecture

    upload / topic
      |
      v
    ingest/            extract -> chunk (sentence bounded) -> embed -> ChromaDB
      |
      v
    planner/           concepts, order, minutes per concept, from the level
      |                and the time budget
      v
    teacher/engine.py  per concept: retrieve -> teach -> draw -> narrate -> ask
      |                            -> evaluate -> name the misconception
      |                            -> continue / reexplain / simplify / harden
      v
    prompt_101/media_pipeline   board frames + narration + avatar -> MP4
      |
      v
    history/           reports, answers, flashcards (SM-2), transcripts
                       -> mentora.db

One engine, two front ends. `web/` (FastAPI) and `app.py` (Streamlit) both
call the same `teacher/`, `planner/` and `ingest/` packages, so neither is a
mock of the other and a fix lands in both.

| Layer | Where |
|---|---|
| Ingest, chunking, embeddings | `ingest/` |
| Lesson planning | `planner/` |
| Teaching, evaluation, adaptation | `teacher/engine.py` |
| Board video, avatar, narration | `prompt_101/media_pipeline/`, `avatar-prototype/` |
| Web app | `web/server.py`, `web/lesson_api.py`, `web/static/` |
| Streamlit app | `app.py`, `screens/` |
| History, SRS, accounts | `history/`, `web/auth.py`, `mentora.db` |

## AI/ML models used

| Role | Model | Where it runs |
|---|---|---|
| Teaching, planning, evaluation | `openai/gpt-oss-120b` via Groq | Groq API |
| Same, offline alternative | `llama3.1:8b` via Ollama | This machine |
| Embeddings for retrieval | `BAAI/bge-m3` (sentence-transformers) | This machine |
| Narration | Microsoft Edge neural voices (`edge-tts`) | Free web service |
| Voice mode speech | Browser `speechSynthesis` / `SpeechRecognition` | The browser |

The provider is chosen in `llm.py`; only Groq and Ollama are supported.
Responses cache to `.cache/llm` keyed on prompt and model, so repeating a
lesson costs nothing and returns instantly.

## RAG implementation

1. **Extract** — PDF via PyMuPDF, DOCX, PPTX, TXT.
2. **Chunk** — `ingest/chunk.py`, on sentence boundaries, 200–500 words with a
   40-word overlap. The overlap is measured in *words*, not sentences: a page
   with no punctuation used to produce chunks at twice the maximum.
3. **Embed** — BGE-M3, stored in ChromaDB.
4. **Retrieve** — per concept, not per lesson, so each segment is grounded in
   the passage that concept actually needs.
5. **Cite** — the segment carries the chunk it used, and the UI shows it.

Name a topic instead of uploading, and the planner runs without the retrieval
step; nothing else changes.

## Prompt/agent architecture

The teaching loop is a small state machine, not one long prompt. Each concept
runs: **retrieve → teach → draw → narrate → ask → evaluate → decide**. The
decision step returns one of `continue`, `reexplain`, `simplify`, `harden` or
`example`, together with the misconception it believes the answer revealed.
That verdict is what feeds the next iteration, which is what makes the lesson
a route rather than a script. Prompts live beside the code that calls them in
`teacher/` and `planner/`; see `docs/prompts_agents.md`.

## Personalization approach

- **Level** sets where the lesson starts — beginner opens simplified,
  advanced opens hardened (`teacher/engine.py`).
- **Answers move it from there.** Two reexplains or two simplifies in a row
  and the lesson simplifies; two hardens and it hardens.
- **Time budget** (1–60 minutes) decides how many concepts are covered and how
  long each gets.
- **Teacher persona** — six characters, each with its own voice and manner.
- **History carries over.** Every account keeps its own settings, materials,
  lessons, flashcards and reports; see `docs/personalization.md`.

## Assessment methodology

Questions during the lesson, then a final quiz. An answer is not marked
right/wrong and dropped — it is evaluated for *which misconception it shows*,
and that name drives both the re-teach and the report.

The report gives score, concepts understood, weak areas, incorrect concepts,
recommended revision and the suggested next topic. Wrong answers become
flashcards on an SM-2 schedule (`history/srs.py`), so the material returns on
the day it is about to be forgotten. Details in `docs/assessment.md`.

## Multilingual implementation

Eighteen languages, defined once in `shared/languages.py` as voice, font and
script direction together — so a language cannot be added that speaks but
cannot draw its own alphabet. Narration, board text, questions and the whole
interface all switch on one click; `ui/i18n.py` holds every interface string
in all eighteen. Urdu and Arabic render right-to-left.

## Voice implementation

Narration uses `edge-tts` with a neural voice per language, rendered per
sentence: edge-tts emits a `SentenceBoundary` event carrying a real offset, so
the board reveals each element exactly as it is spoken rather than on a timer.

Voice mode (`/voice`) is the browser's own `SpeechRecognition` and
`speechSynthesis` — the student talks, the teacher answers aloud and draws
while it answers. Chrome only; other browsers get a typed box and still hear
the reply. See `docs/voice.md`.

## Avatar/video generation approach

The teacher is an SVG rig — six characters sharing one skeleton, recoloured at
draw time — animated from the narration: lip-synced per sentence boundary,
glancing at each board element as it appears, with idle sway, blink and nod.

For lesson video, matplotlib draws the board frame by frame through
`FFMpegWriter`, with the avatar **drawn into the frame** rather than laid over
it as a floating head, and the narration muxed in. ffmpeg comes from
`imageio-ffmpeg`, which ships its own binary — there is no system ffmpeg
dependency and no ffprobe. See `docs/avatar.md` and `docs/composite.md`.

## APIs and third-party services

| Service / library | Used for | Key needed |
|---|---|---|
| Groq API | LLM inference (`openai/gpt-oss-120b`) | Yes, free |
| Ollama | Local LLM, offline alternative | No |
| `edge-tts` | Neural narration voices | No |
| `sentence-transformers` + `BAAI/bge-m3` | Embeddings | No |
| ChromaDB | Vector store | No |
| PyMuPDF, python-docx, python-pptx | Document extraction | No |
| matplotlib, `imageio-ffmpeg` | Board rendering, video encoding | No |
| FastAPI + uvicorn, Streamlit | The two front ends | No |
| three.js (CDN) | Optional 3D avatar on `/voice` | No |

No paid service is required. Groq's free tier is the only account needed, and
Ollama replaces even that.

## Setup instructions

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

## Deployment instructions

The web app is a normal ASGI application, so anything that runs uvicorn runs
Mentora.

```bash
.venv/bin/uvicorn web.server:app --host 0.0.0.0 --port 8000
```

Before exposing it beyond your own machine:

- **Set `GROQ_API_KEY` in the environment**, not in a committed file. `.env`
  is gitignored and read at startup.
- **Change the seeded passwords.** `student`, `teacher` and `admin` ship with
  known ones for the demo; `seed_demo_class.py --clear` removes the invented
  classroom entirely.
- `mentora.db` (SQLite) holds accounts, history and flashcards. Back it up;
  it is the whole state of the install.
- Generated media under `prompt_101/media_pipeline/output/` and `out/avatar`
  is regenerable and safe to clear.
- Reset codes are returned in the response only to loopback callers, so a
  remote deployment needs a mail path before the reset flow is usable. Set
  `MENTORA_DEBUG_RESET_TOKENS=0` to disable that convenience entirely.

Ollama instead of Groq removes the last external dependency:

```bash
ollama pull llama3.1:8b
AI_TEACHER_PROVIDER=ollama .venv/bin/uvicorn web.server:app --port 8000
```

## Mandatory requirements

Where each of the brief's twelve required capabilities lives.

| # | Requirement | Where |
|---|---|---|
| 1 | Learning from uploaded material | `ingest/` — PDF, DOCX, PPTX, TXT, chunked, embedded, cited |
| 2 | Topic-based teaching | Name a topic; the planner runs with no document |
| 3 | AI-generated lesson structure | `planner/` — concepts, order, minutes each |
| 4 | Personalized teaching | Level, time, persona, language, and the student's own history |
| 5 | Human-like teaching interaction | Explains, asks, marks, names the misconception, re-teaches |
| 6 | Video-based presentation | matplotlib board + narration + avatar, encoded to MP4 |
| 7 | AI voice | `edge-tts` neural voices, one per language |
| 8 | Human-like AI avatar | Six SVG characters, lip-synced, gaze and nod |
| 9 | Multilingual | Eighteen languages, interface and teaching together |
| 10 | Student questioning | Questions mid-lesson and a final quiz; answering gates progress |
| 11 | Adaptive response | `continue` / `reexplain` / `simplify` / `harden` from the answers |
| 12 | Working prototype | Two front ends on one engine; `pytest` and `tests_e2e.py` |

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
