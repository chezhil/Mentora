"""FastAPI backend for the Session Review UI.

Serves the static HTML page and provides API endpoints that return
real data from mentora.db. No UI edits — the HTML fetches from these
endpoints and populates itself via JavaScript.

Run:  python web/server.py
URL:  http://localhost:8000/mentora-session-review
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# `python web/server.py` puts web/ on sys.path, not the repo root, so an
# absolute "web.auth" import fails outright -- the documented way to start
# the server crashed with ModuleNotFoundError. Put the root on the path
# first and the import works however the file is invoked.
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

try:
    import web.auth as auth                      # run as a module / from root
except ModuleNotFoundError:
    import auth                                  # run as `python web/server.py`

app = FastAPI(title="Mentora Session Review")

# Initialize SQLite tables including users table
auth.init_auth_db()

DB_PATH = Path(__file__).resolve().parent.parent / "mentora.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# API: session review data
# ---------------------------------------------------------------------------

@app.get("/api/session-review")
def session_review(request: Request, student_id: str = "student",
                   session_id: str = "") -> dict:
    """Return all data the Session Review HTML needs, in one call.

    Shape matches what the JS in the HTML expects:
    {
      "lesson_title": str,
      "topic": str,
      "improvement_pct": int | None,
      "total_minutes": int,
      "concepts_mastered": int,
      "questions_handled": int,
      "concepts": [{"name": str, "description": str, "status": "Mastered"|"Partial"}],
      "next_topic": str,
      "next_description": str,
      "difficulty": str,
    }
    """
    # A lesson just finished in the browser hands us the live handle, not the
    # stored id; translate before looking anything up.
    try:
        import lesson_api
        student_id = lesson_api.who(request, student_id)
        session_id = lesson_api._lesson_id(session_id) if session_id else session_id
    except Exception:
        pass

    conn = _db()
    try:
        return _build_review(conn, student_id, session_id)
    finally:
        conn.close()


def _build_review(conn: sqlite3.Connection, student_id: str,
                  session_id: str = "") -> dict:
    cur = conn.cursor()

    # --- Latest report (the one we're reviewing) ---
    # A named session, so Recent Activity can open the report for the lesson
    # that was clicked rather than always the newest one.
    if session_id:
        cur.execute("SELECT * FROM reports WHERE student_id=? AND session_id=?",
                    (student_id, session_id))
        report = cur.fetchone()
        cur.execute("SELECT * FROM study_sessions WHERE student_id=? AND session_id=?",
                    (student_id, session_id))
        session = cur.fetchone()
    else:
        report = session = None

    if report is None:
        cur.execute(
            "SELECT * FROM reports WHERE student_id=? ORDER BY id DESC LIMIT 1",
            (student_id,),
        )
        report = cur.fetchone()
    if session is None:
        cur.execute(
            "SELECT * FROM study_sessions WHERE student_id=? ORDER BY id DESC LIMIT 1",
            (student_id,),
        )
        session = cur.fetchone()

    # --- Topic ---
    topic = ""
    if session and session["topic"]:
        topic = session["topic"]
    elif report and report["next_topic"]:
        topic = report["next_topic"]

    # --- How long THIS session took ---
    # This summed minutes_planned across every session the student had ever
    # started, so a two-minute lesson's own review page reported 160 minutes.
    # It is a session review: it reports the session.
    total_minutes = 0
    if session:
        if session["started_at"] and session["ended_at"]:
            try:
                start = datetime.fromisoformat(session["started_at"])
                end = datetime.fromisoformat(session["ended_at"])
                total_minutes = max(0, int(round((end - start).total_seconds() / 60)))
            except Exception:
                total_minutes = 0
        if not total_minutes:
            total_minutes = int(session["minutes_planned"] or 0)

    # --- Answers for this session ---
    session_id = report["session_id"] if report else (session["session_id"] if session else None)
    concepts_mastered = 0
    questions_handled = 0
    concepts = []

    if session_id:
        cur.execute(
            "SELECT concept_name, COUNT(*) as cnt, SUM(correct) as correct_cnt "
            "FROM answers WHERE session_id=? GROUP BY concept_name",
            (session_id,),
        )
        answer_rows = cur.fetchall()
        questions_handled = sum(r["cnt"] for r in answer_rows)

        for r in answer_rows:
            name = r["concept_name"] or "Unknown Concept"
            correct = r["correct_cnt"] or 0
            total = r["cnt"]
            # A concept is mastered if all answers for it were correct
            is_mastered = correct == total and total > 0
            if is_mastered:
                concepts_mastered += 1
            concepts.append({
                "name": name,
                "description": _concept_description(name, report),
                "status": "Mastered" if is_mastered else "Partial",
            })

    # If no answers table data, fall back to report's strong/weak
    if not concepts and report:
        strong = _parse_json_list(report["strong_json"])
        weak = _parse_json_list(report["weak_json"])
        for s in strong:
            concepts.append({"name": s, "description": "", "status": "Mastered"})
            concepts_mastered += 1
        for w in weak:
            concepts.append({"name": w, "description": "", "status": "Partial"})

    # --- Also count student turns as interactions ---
    if session_id:
        cur.execute(
            "SELECT COUNT(*) FROM turns WHERE session_id=? AND role='student'",
            (session_id,),
        )
        student_turns = cur.fetchone()[0]
        questions_handled = max(questions_handled, student_turns)

    # --- Improvement % ---
    improvement = _compute_improvement(cur, student_id)

    # --- Next topic ---
    next_topic = ""
    next_description = ""
    if report and report["next_topic"]:
        next_topic = report["next_topic"]
        revise = _parse_json_list(report["revise_json"])
        if revise:
            next_description = revise[0]
        else:
            next_description = f"Building on your progress, we'll continue with {next_topic}."

    # --- Score for the "You crushed it" message ---
    score = report["score"] if report else 0

    has_session = report is not None or session is not None

    return {
        "has_session": has_session,
        # Which lesson this review is actually about. Without it, the
        # transcript and download buttons on a bare /review have no session
        # to point at: the download 422s and the transcript bounces home.
        "session_id": session_id or "",
        "lesson_title": topic or "Welcome to Mentora",
        "topic": topic or "your first lesson",
        "score": score,
        "improvement_pct": improvement,
        "total_minutes": total_minutes,
        "concepts_mastered": concepts_mastered,
        "questions_handled": questions_handled,
        "concepts": concepts,
        "next_topic": next_topic,
        "next_description": next_description,
        "difficulty": "Intermediate",
    }


def _parse_json_list(val: str | None) -> list[str]:
    if not val:
        return []
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except Exception:
        pass
    return []


def _concept_description(name: str, report) -> str:
    """Generate a short description for a concept based on context."""
    # Use revise items if they mention this concept
    if report:
        revise = _parse_json_list(report["revise_json"])
        for r in revise:
            if name.lower() in r.lower():
                return r[:60]
    # Default: just return the name as-is
    return name


def _compute_improvement(cur: sqlite3.Cursor, student_id: str) -> int | None:
    """Compare latest two session scores to compute improvement %."""
    cur.execute(
        "SELECT score FROM reports WHERE student_id=? AND score IS NOT NULL ORDER BY id DESC LIMIT 2",
        (student_id,),
    )
    rows = cur.fetchall()
    if len(rows) >= 2:
        latest = rows[0]["score"]
        previous = rows[1]["score"]
        if previous > 0:
            return int(round(((latest - previous) / previous) * 100))
    return None


# ---------------------------------------------------------------------------
# Dashboard API — real data for the student dashboard HTML
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
def dashboard_api(request: Request, student_id: str = "student") -> dict:
    # Follow whoever is signed in; the literal "student" made every profile
    # share one dashboard.
    try:
        import lesson_api
        student_id = lesson_api.who(request, student_id)
    except Exception:
        pass
    """Everything the student dashboard needs in one call."""
    conn = _db()
    try:
        cur = conn.cursor()

        # Reports
        cur.execute(
            "SELECT * FROM reports WHERE student_id=? ORDER BY id DESC LIMIT 20",
            (student_id,),
        )
        reports = [dict(r) for r in cur.fetchall()]

        # Study sessions
        cur.execute(
            "SELECT * FROM study_sessions WHERE student_id=? ORDER BY id DESC LIMIT 20",
            (student_id,),
        )
        sessions = [dict(r) for r in cur.fetchall()]

        # Total stats
        # Time actually spent, not time planned. Summing minutes_planned
        # credited a full 20 minutes to a lesson abandoned after one segment,
        # so "hours learned" only ever went up.
        cur.execute(
            "SELECT started_at, ended_at, minutes_planned FROM study_sessions "
            "WHERE student_id=?", (student_id,),
        )
        total_minutes = 0.0
        for row in cur.fetchall():
            spent = None
            if row["started_at"] and row["ended_at"]:
                try:
                    spent = (datetime.fromisoformat(row["ended_at"])
                             - datetime.fromisoformat(row["started_at"])
                             ).total_seconds() / 60.0
                except Exception:
                    spent = None
            if spent is None or spent < 0:
                spent = 0.0
            total_minutes += min(spent, float(row["minutes_planned"] or 0) + 30)
        total_minutes = round(total_minutes, 1)

        cur.execute(
            "SELECT COUNT(DISTINCT session_id) FROM reports WHERE student_id=?",
            (student_id,),
        )
        total_lessons = cur.fetchone()[0]

        # Streak
        cur.execute(
            "SELECT DATE(started_at) as day FROM study_sessions "
            "WHERE student_id=? AND started_at IS NOT NULL "
            "GROUP BY day ORDER BY day DESC",
            (student_id,),
        )
        days = [r["day"] for r in cur.fetchall()]
        streak = 0
        if days:
            from datetime import date, timedelta
            today = date.today().isoformat()
            expected = today
            for d in days:
                if d == expected:
                    streak += 1
                    expected = (datetime.strptime(expected, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                elif d < expected:
                    break

        # Scores
        scores = [r["score"] for r in reports if r.get("score") is not None]
        avg_score = round(sum(scores) / len(scores)) if scores else 0

        # Level from XP (100 XP per level)
        # total_minutes became a float when it started measuring real
        # elapsed time, and XP is a whole number in the UI.
        xp = int(round(total_minutes * 5 + total_lessons * 50))
        level = xp // 200 + 1
        xp_into = xp % 200

        # Weak/strong concepts
        weak = []
        strong = []
        for r in reports:
            try:
                w = json.loads(r.get("weak_json", "[]"))
                s = json.loads(r.get("strong_json", "[]"))
                weak.extend(w)
                strong.extend(s)
            except Exception:
                pass
        weak = list(dict.fromkeys(weak))[:5]
        strong = list(dict.fromkeys(strong))[:5]

        # Recent lessons for the dashboard list. The topic lives on
        # study_sessions; reports only carries next_topic, which is what to
        # study NEXT -- so every row in "recent activity" was labelled with a
        # subject the student had not been taught yet.
        titles = {row["session_id"]: (row["topic"] or "").strip()
                  for row in sessions}
        recent = []
        for r in reports[:5]:
            recent.append({
                "session_id": r.get("session_id", ""),
                "topic": titles.get(r.get("session_id"))
                         or r.get("next_topic") or "Untitled",
                "next_topic": r.get("next_topic", ""),
                "score": r.get("score", 0),
                "date": r.get("created_at", "")[:10],
                "strong": json.loads(r.get("strong_json", "[]")),
                "weak": json.loads(r.get("weak_json", "[]")),
            })

        # Flashcard stats
        cur.execute(
            "SELECT COUNT(*) FROM flashcards WHERE student_id=?",
            (student_id,),
        )
        total_cards = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM flashcards WHERE student_id=? AND next_review <= datetime('now')",
            (student_id,),
        )
        due_cards = cur.fetchone()[0]

        return {
            "student_name": student_id,
            "total_lessons": total_lessons,
            "total_minutes": total_minutes,
            "streak": streak,
            "avg_score": avg_score,
            "level": level,
            "xp": xp,
            "xp_into": xp_into,
            "weak": weak,
            "strong": strong,
            "recent_lessons": recent,
            "total_cards": total_cards,
            "due_cards": due_cards,
            "total_sessions": len(sessions),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: discuss endpoint — returns an AI-like answer
# ---------------------------------------------------------------------------

@app.post("/api/discuss")
def discuss_api(payload: dict = None) -> dict:
    """Return a contextual answer based on the student's history.
    In mock mode this returns a smart fallback from the DB.
    """
    if payload is None:
        payload = {}
    question = payload.get("question", "")
    student_id = payload.get("student_id", "student")
    if not question:
        return {"answer": "Please ask a question!", "role": "teacher"}

    # Actually answer it. Everything below this was a set of keyword branches
    # over the student's own report rows -- so "what is Ohm's law?" came back
    # as "Great question! We've been working on ...", which is not an answer
    # to anything. Ask the model that teaches the lessons, and keep the
    # history-shaped reply below as the fallback for when there is no key or
    # the call fails.
    try:
        import llm
        from history import db as _hdb

        prefs = _hdb.get_preferences(student_id)
        recent = _hdb.list_reports(student_id)[:2] if hasattr(_hdb, "list_reports") else []
        context = ""
        if recent:
            weak_bits = []
            for r in recent:
                weak_bits += (r.get("weak") or [])
            if weak_bits:
                context = ("\nThe student has recently struggled with: "
                           + "; ".join(weak_bits[:5]) + ".")

        answer = llm.generate_json(
            "You are Mentora, the student's tutor, answering a follow-up "
            "question between lessons. Answer it directly and concretely in "
            f"at most 90 words, in the language with code '{prefs.get('language', 'en')}'. "
            "Do not greet, do not restate the question, do not mention their "
            "progress unless they asked about it." + context +
            f"\n\nQuestion: {question}\n\n"
            'Return ONLY {"answer": "..."} as JSON.'
        )
        text = (answer or {}).get("answer")
        if isinstance(text, str) and text.strip():
            return {"answer": text.strip(), "role": "teacher"}
        # Fell through with a reply the model did not shape as expected.
        print(f"[discuss] unusable model reply: {str(answer)[:160]}", flush=True)
    except Exception as exc:
        # Silent fallback made this impossible to diagnose: the page looked
        # like it was answering while quietly serving the canned text.
        print(f"[discuss] falling back to history reply: "
              f"{type(exc).__name__}: {str(exc)[:180]}", flush=True)

    conn = _db()
    try:
        cur = conn.cursor()

        # Get recent topics and weak areas for context
        cur.execute(
            "SELECT next_topic, strong_json, weak_json, score FROM reports "
            "WHERE student_id=? ORDER BY id DESC LIMIT 3",
            (student_id,),
        )
        reports = cur.fetchall()

        weak = []
        strong = []
        topics = []
        for r in reports:
            try:
                weak.extend(json.loads(r["weak_json"] or "[]"))
                strong.extend(json.loads(r["strong_json"] or "[]"))
            except Exception:
                pass
            if r["next_topic"]:
                topics.append(r["next_topic"])

        weak = list(dict.fromkeys(weak))[:5]
        strong = list(dict.fromkeys(strong))[:5]
        topics = list(dict.fromkeys(topics))[:3]

        q = question.lower()

        # Build a contextual answer from real data
        if "weak" in q or "struggle" in q or "hard" in q:
            if weak:
                answer = (f"Based on your recent sessions, your areas for improvement are: {', '.join(weak)}. "
                         f"Let's focus on these. Would you like me to explain one of these concepts or give you a practice problem?")
            else:
                answer = "You haven't completed enough lessons yet for me to identify weak areas. Complete a few lessons and I'll track your progress!"
        elif "strong" in q or "good" in q or "master" in q:
            if strong:
                answer = f"You're doing great with: {', '.join(strong)}! Keep building on these strengths."
            else:
                answer = "Complete some lessons and I'll track your strong areas!"
        elif "topic" in q or "lesson" in q or "next" in q:
            if topics:
                answer = f"Your recent topics have been: {', '.join(topics)}. What would you like to explore next?"
            else:
                answer = "Start your first lesson by uploading material and choosing a topic!"
        elif "quiz" in q or "test" in q:
            answer = "I can quiz you on any topic. Tell me which concept you'd like to be tested on, and I'll generate questions for you."
        elif "explain" in q:
            answer = f"I'd be happy to explain! Based on your current topics ({', '.join(topics) if topics else 'your lesson'}), let me break this down into simple terms. Could you specify which concept you'd like explained?"
        else:
            if topics:
                answer = f"Great question! We've been working on {topics[0]}. Let me help you understand this better. Could you tell me which specific part is confusing you?"
            else:
                answer = "That's a great question! Upload some study material first, and I'll help you explore that topic in depth."

        return {"answer": answer, "role": "teacher"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: config bridge (FastAPI ↔ Streamlit via DB)
# ---------------------------------------------------------------------------

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import history.db as hdb


@app.get("/api/config")
def get_config(student_id: str = "student") -> dict:
    """Read student preferences from DB."""
    return hdb.get_preferences(student_id)


@app.post("/api/config")
def save_config(payload: dict = None, student_id: str = "student") -> dict:
    """Save student preferences to DB."""
    if payload is None:
        payload = {}
    hdb.set_preferences(student_id, payload)
    return {"ok": True, **hdb.get_preferences(student_id)}


@app.post("/api/upload")
def upload_files(files: list[dict] = None, topic: str = "", student_id: str = "student") -> dict:
    """Accept file metadata from the brutalist upload page.
    Streamlit reads pending_uploads on next lesson start.
    """
    from datetime import datetime as _dt
    import json as _json
    import base64

    prefs = hdb.get_preferences(student_id)
    pending = prefs.get("pending_uploads", [])

    # The brutalist upload page sends file metadata (name, size, base64 content)
    if files:
        upload_dir = STATIC_DIR.parent.parent / "out" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            fname = f.get("name", "upload")
            content_b64 = f.get("content", "")
            if content_b64:
                try:
                    data = base64.b64decode(content_b64)
                    fpath = upload_dir / fname
                    fpath.write_bytes(data)
                except Exception:
                    pass
            pending.append({
                "name": fname,
                "size": f.get("size", 0),
                "topic": topic,
            })

    hdb.set_preferences(student_id, {**prefs, "pending_uploads": pending})
    return {"ok": True, "pending_count": len(pending)}


# ---------------------------------------------------------------------------
# Serve the HTML pages
# ---------------------------------------------------------------------------

def _page_guard(request: Request, *roles: str):
    """Redirect an unauthorised visitor to /login rather than render a shell."""
    try:
        import lesson_api
        return lesson_api.page_guard(request, *roles)
    except Exception:
        return None


@app.get("/")
def serve_root(request: Request):
    """The front door is the login page.

    It used to be a role chooser -- two cards, Student and Teacher -- which
    was a decision the account already answers. Picking "Teacher" there did
    not make anyone a teacher; it just walked into a classroom with no
    session behind it. Signed in, this goes straight to where that role
    belongs; signed out, it is the login form itself rather than a page that
    links to it.
    """
    from fastapi.responses import RedirectResponse
    try:
        import lesson_api
        user = lesson_api.current_user(request)
    except Exception:
        user = None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    home = {"teacher": "/teacher", "admin": "/admin"}.get(
        user.get("role"), "/dashboard")
    return RedirectResponse(home, status_code=303)


@app.get("/dashboard")
def serve_dashboard(request: Request):
    blocked = _page_guard(request)
    if blocked is not None:
        return blocked

    html_path = STATIC_DIR / "mentora-dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/mentora-session-review")
def serve_session_review(request: Request):
    blocked = _page_guard(request)
    if blocked is not None:
        return blocked

    html_path = STATIC_DIR / "session-review.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>session-review.html not found</h1>", status_code=404)


@app.get("/upload")
def serve_upload(request: Request):
    blocked = _page_guard(request)
    if blocked is not None:
        return blocked

    html_path = STATIC_DIR / "upload.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Upload not found</h1>", status_code=404)


@app.get("/config")
def serve_config(request: Request):
    blocked = _page_guard(request)
    if blocked is not None:
        return blocked

    html_path = STATIC_DIR / "config.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Config not found</h1>", status_code=404)


@app.get("/discuss")
def serve_discuss(request: Request, q: str = ""):
    blocked = _page_guard(request)
    if blocked is not None:
        return blocked

    html_path = STATIC_DIR / "discuss.html"
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        if q:
            # Inject the user's question on load
            inject = f'<script>window.addEventListener("load",function(){{setTimeout(function(){{sendQuick("{q}")}},500)}});</script>'
            content = content.replace('</body>', inject + '</body>')
        return HTMLResponse(content)
    return HTMLResponse("<h1>Discuss not found</h1>", status_code=404)


@app.get("/review")
def serve_review(request: Request):
    blocked = _page_guard(request)
    if blocked is not None:
        return blocked

    html_path = STATIC_DIR / "session-review.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Session Review not found</h1>", status_code=404)


@app.get("/vtutor")
def serve_vtutor(request: Request):
    blocked = _page_guard(request)
    if blocked is not None:
        return blocked

    html_path = STATIC_DIR / "vtutor.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>VTutor not found</h1>", status_code=404)


# ---------------------------------------------------------------------------
# Authentication UI Pages & APIs
# ---------------------------------------------------------------------------

@app.get("/login")
def serve_login():
    html_path = STATIC_DIR / "login.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Login page not found</h1>", status_code=404)


@app.get("/signup")
def serve_signup():
    html_path = STATIC_DIR / "signup.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Signup page not found</h1>", status_code=404)


@app.get("/forgot-password")
def serve_forgot_password():
    html_path = STATIC_DIR / "forgot-password.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Forgot password page not found</h1>", status_code=404)


@app.post("/api/auth/login")
async def api_login(request: Request, response: Response):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request body"}, status_code=400)

    identifier = data.get("identifier", "")
    password = data.get("password", "")

    user = auth.authenticate_user(identifier, password)
    if not user:
        return JSONResponse({"ok": False, "error": "Invalid email/username or password"}, status_code=401)

    token = auth.create_session(user)
    redirect = {"teacher": "/teacher", "admin": "/admin"}.get(
        user.get("role"), "/dashboard")

    res = JSONResponse({"ok": True, "user": user, "token": token, "redirect": redirect})
    res.set_cookie(
        key="session_token",
        value=token,
        max_age=auth.SESSION_EXPIRY_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return res


@app.post("/api/auth/signup")
async def api_signup(request: Request, response: Response):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request body"}, status_code=400)

    username = data.get("username", "")
    email = data.get("email", "")
    password = data.get("password", "")
    role = data.get("role", "student")

    try:
        user = auth.create_user(email=email, username=username, password=password, role=role)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    token = auth.create_session(user)
    redirect = "/dashboard" if user.get("role") == "student" else "/config"

    res = JSONResponse({"ok": True, "user": user, "token": token, "redirect": redirect})
    res.set_cookie(
        key="session_token",
        value=token,
        max_age=auth.SESSION_EXPIRY_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return res


# There is no mail server here, so the reset code has to reach the user
# through the response for the flow to work at all. That is safe enough for
# someone sitting at the machine and not safe at all over a network, so it
# goes only to loopback callers -- and MENTORA_DEBUG_RESET_TOKENS=0 turns off
# even that. Anyone else gets the same answer with no code in it.
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _may_see_reset_token(request: Request) -> bool:
    if os.environ.get("MENTORA_DEBUG_RESET_TOKENS") == "0":
        return False
    return bool(request.client) and request.client.host in LOOPBACK


@app.post("/api/auth/forgot-password")
async def api_forgot_password(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request body"}, status_code=400)

    email = data.get("email", "")
    token = auth.generate_reset_token(email)

    # The same answer either way. Returning 404 for an unknown address tells
    # an anonymous caller which emails hold accounts, and returning the token
    # itself hands out the reset without the mailbox ever being involved.
    reply = {"ok": True, "message":
             "If that address has an account, a recovery code has been sent."}
    if token and _may_see_reset_token(request):
        reply["token"] = token
    return JSONResponse(reply)


@app.post("/api/auth/reset-password")
async def api_reset_password(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request body"}, status_code=400)

    email = data.get("email", "")
    token = data.get("token", "")
    new_password = data.get("new_password", "")

    try:
        success = auth.reset_password(email, token, new_password)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    if not success:
        return JSONResponse({"ok": False, "error": "Invalid or expired recovery code."}, status_code=400)

    return JSONResponse({"ok": True, "message": "Password updated successfully."})


@app.get("/api/auth/me")
def api_me(request: Request):
    token = request.cookies.get("session_token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    user = auth.get_session_user(token)
    return JSONResponse({"ok": True, "user": user})


@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response):
    token = request.cookies.get("session_token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    auth.revoke_session(token)
    res = JSONResponse({"ok": True, "message": "Logged out successfully."})
    res.delete_cookie("session_token")
    return res


# The teaching loop -- /lesson, /api/lesson/* -- lives in its own module so
# that edits to this file and edits to the lesson flow do not collide.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lesson_api import router as lesson_router   # noqa: E402

app.include_router(lesson_router)

# Mount static files (CSS, JS, images if any)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
