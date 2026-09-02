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
