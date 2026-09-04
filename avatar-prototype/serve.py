"""Serve the avatar prototype over a real ASGI server.

    ../.venv/bin/python serve.py            # http://127.0.0.1:8620
    ../.venv/bin/python serve.py --port 9000

`python -m http.server` works for a quick look, but it is single-threaded and
blocks on one request at a time — which shows up here, because the page pulls
two ES modules and a media file while the audio graph is starting.

Self-contained: this serves THIS directory and nothing else. It does not
import or modify server.py, so the branch stays avatar-only.

TO PUT THE AVATAR INSIDE THE REAL APP instead, one line in server.py does it,
after the API routes and before the `/{filename}` catch-all that would
otherwise shadow it:

    from fastapi.staticfiles import StaticFiles
    app.mount("/avatar",
              StaticFiles(directory="avatar-prototype", html=True),
              name="avatar")

Order matters: Starlette matches routes in the order they are registered, so a
mount added after `@app.get("/{filename}")` is never reached.
"""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent

# Some systems map .js to text/plain, and a browser refuses to execute a module
# served with the wrong type — the page then fails silently with a blank stage.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

app = FastAPI(title="Mentora avatar prototype")
app.mount("/", StaticFiles(directory=str(HERE), html=True), name="prototype")


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the avatar prototype.")
    ap.add_argument("--port", type=int, default=8620)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    print(f"avatar prototype -> http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
