# Mentora — AI Teacher

Team Winners · Yenepoya, Bangalore · AI Innovation Hackathon 2026, Round 2

An AI teacher that reads your material, plans a lesson for your level and the
time you have, teaches it with an avatar and visuals, asks you questions,
works out *why* you got something wrong, and changes its approach.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

### Voice models (needed for real speech)

Piper voices are too big to commit. Download them once:

```bash
D=prompt_101/media_pipeline/piper_models; mkdir -p $D
B=https://huggingface.co/rhasspy/piper-voices/resolve/main
curl -sL -o $D/en_US-lessac-medium.onnx      $B/en/en_US/lessac/medium/en_US-lessac-medium.onnx
curl -sL -o $D/en_US-lessac-medium.onnx.json $B/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
curl -sL -o $D/hi_IN-pratham-medium.onnx      $B/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx
curl -sL -o $D/hi_IN-pratham-medium.onnx.json $B/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx.json
```

Two backends, both free, no keys anywhere:

| Languages | Backend | Notes |
|---|---|---|
| en, hi, te | Piper | local, offline, needs the voice models below |
| ta, kn, bn, mr | edge-tts | free neural voices, needs a network connection |

Piper leads where it has a voice because it works offline; edge-tts covers the
rest and backs up the others. If both fail the lesson continues with a silent
placeholder rather than stopping.

Verified real speech in all seven: en, hi, ta, kn, te, bn, mr.

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
`MENTORA_LOCAL_AVATAR=0` forces Pair C's Replicate path instead.

### Which LLM provider

Gemini's free tier is **20 requests per day**, per key, per model. One lesson
costs **22** (measured), so a lesson cannot finish on a single free key.

Groq's free tier is thousands per day and serves Llama 3.3 70B. Get a key at
**https://console.groq.com/keys** — sign in with Google or GitHub, click
*Create API Key*, copy it once (it is shown only once).

Then either paste it into the ⚙️ APIs panel in the sidebar, or:

```bash
echo "AI_TEACHER_PROVIDER=groq" >> .env
echo "GROQ_API_KEY=your-key-here" >> .env
```

`AI_TEACHER_PROVIDER` accepts `gemini`, `groq` or `ollama`. Ollama runs
locally with no key and no limit; install it and `ollama pull llama3.1:8b`.

Responses are cached in `.cache/llm` keyed on the exact prompt and model, so
repeating a lesson costs nothing. `AI_TEACHER_CACHE=0` disables it.

### Keys

| Variable | Without it |
|---|---|
| `GEMINI_API_KEY` | Pair B cannot run at all. `AI_TEACHER_MOCK=mocks/fixture_mock.json` replays canned answers instead. |
| `REPLICATE_API_TOKEN` | The avatar is a still image, not a talking head. |

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
| `app.py` | Chezhil | Streamlit — 4 screens + the adaptation panel |
| `wiring.py` | Chezhil | Picks the real module or the stub, per function |
| `stubs/` | Chezhil | Fake Pair B / Pair C / ingest, so nobody is blocked |
| `planner/` `teacher/` | Pair B | Jyothi + Naman |
| `visuals/` `media/` | Pair C | Santosh + Hamza |

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
