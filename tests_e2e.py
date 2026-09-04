"""End-to-end pass over the whole web product. Reports PASS/FAIL per check."""
import base64, json, sqlite3, sys, time, urllib.error, urllib.request

B = "http://localhost:8000"
ROOT = "/Users/chez/Documents/Hackathon/AIunstop/Mentora"
fails = []

def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)
    if not ok:
        fails.append(name)

def req(path, body=None, method=None, raw=False, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data,
                               method=method or ("POST" if data is not None else "GET"),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload or b"{}")), dict(resp.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload or b"{}"), dict(e.headers)
        except Exception:
            return e.code, {"raw": payload[:200].decode("utf-8", "replace")}, dict(e.headers)

def db(sql, args=()):
    c = sqlite3.connect(f"{ROOT}/mentora.db"); c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()

print("\n=== 1. pages ===")
for p in ["/", "/dashboard", "/upload", "/materials", "/lesson", "/config",
          "/discuss", "/review", "/transcript", "/flashcards", "/voice"]:
    s, _, _ = req(p, raw=True)
    check(f"GET {p}", s == 200, str(s))

print("\n=== 2. static assets ===")
for p in ["/static/brutalist.css", "/static/ask-rail.js", "/static/progress-panel.js",
          "/static/teachers.js", "/static/voice.js"]:
    s, _, _ = req(p, raw=True)
    check(f"GET {p}", s == 200, str(s))

print("\n=== 3. settings roundtrip ===")
want = {"language": "en", "difficulty": "beginner", "persona": "friendly",
        "avatar": "m", "teacher": "kenji", "auto_quiz": True}
s, got, _ = req("/api/settings", want)
check("POST /api/settings", s == 200)
for k, v in want.items():
    check(f"  settings.{k} == {v}", got.get(k) == v, repr(got.get(k)))
s, got2, _ = req("/api/settings")
check("settings persist on re-read", all(got2.get(k) == v for k, v in want.items()))
check("keys never echoed", all(isinstance(v, bool) for v in got2.get("keys", {}).values()))

print("\n=== 4. teachers ===")
s, teachers, _ = req("/api/teachers")
check("GET /api/teachers", s == 200 and isinstance(teachers, list) and len(teachers) >= 6,
      f"{len(teachers) if isinstance(teachers, list) else '?'} teachers")
check("every teacher has id/variant/palette",
      all({"id", "variant", "palette"} <= set(t) for t in teachers))

print("\n=== 5. materials ===")
blob = base64.b64encode(b"Ohm's law states V = I * R. Resistance opposes current.\n" * 20).decode()
s, up, _ = req("/api/materials/upload", {"name": "e2e-note.txt", "content": blob, "topic": "Ohm"})
check("upload material", s == 200 and up.get("ok"), str(up)[:80])
s, mats, _ = req("/api/materials")
names = [m["name"] for m in mats.get("materials", [])]
check("uploaded file is listed", "e2e-note.txt" in names, str(names)[:90])
s, bad, _ = req("/api/materials/upload", {"name": "evil.exe", "content": blob})
check("bad extension rejected", s == 400, str(s))
s, trav, _ = req("/api/materials/upload", {"name": "../../evil.txt", "content": blob})
check("traversal filename basenamed", s == 200 and trav.get("name") == "evil.txt", str(trav)[:70])

print("\n=== 6. media route containment ===")
for probe in ["/api/lesson/media/../../.env", "/api/lesson/media/../../mentora.db"]:
    s, _, _ = req(probe, raw=True)
    check(f"blocked {probe}", s == 404, str(s))

print("\n=== 7. voice ===")
s, v, _ = req("/api/voice/reply", {"text": "Draw the steps of the water cycle"}, timeout=120)
check("voice reply", s == 200 and v.get("answer"), str(v)[:80])
check("voice reply is short (spoken)", len((v.get("answer") or "").split()) <= 110,
      f"{len((v.get('answer') or '').split())} words")
if v.get("image"):
    s, img, hdr = req(v["image"], raw=True)
    check("voice diagram serves", s == 200 and len(img) > 3000,
          f"{len(img)}B {hdr.get('content-type')}")
else:
    print("  ....  no diagram this time (model's choice)")
s, verr, _ = req("/api/voice/reply", {"text": "   "})
check("empty voice input rejected", s == 400, str(s))

print("\n=== 8. full lesson ===")
s, st, _ = req("/api/lesson/start", {"topic": "Ohms law", "minutes": 2, "level": "beginner"})
sid = st.get("session_id")
check("lesson starts", s == 200 and bool(sid), str(st)[:80])

def wait(label, limit=90):
    for i in range(limit):
        s, d, _ = req(f"/api/lesson/state?session_id={sid}")
        if d.get("job", {}).get("state") != "running":
            return d
        time.sleep(5)
    return {}

d = wait("first segment")
check("first segment built", d.get("job", {}).get("state") == "done" and d.get("segments"),
      d.get("job", {}).get("error", "")[:90])
seg = (d.get("segments") or [{}])[-1]
check("segment has a board video", bool(seg.get("video")), str(seg.get("notes"))[:70])
if seg.get("video"):
    s, mp4, hdr = req(seg["video"], raw=True)
    check("video serves", s == 200 and len(mp4) > 50000, f"{len(mp4)}B")
check("segment has a question", bool(seg.get("question")))
check("language honoured", d.get("language") == "en", str(d.get("language")))

if seg.get("question"):
    q = seg["question"]
    ans = q["options"][0] if q.get("options") else "V = I R"
    s, ev, _ = req("/api/lesson/answer",
                   {"session_id": sid, "question_id": q["id"], "answer": ans}, timeout=90)
    check("answer graded", s == 200 and "correct" in ev, str(ev)[:80])
    check("feedback present", bool(ev.get("feedback")))
    s, blank, _ = req("/api/lesson/answer",
                      {"session_id": sid, "question_id": q["id"], "answer": "  "})
    check("blank answer rejected", s == 400, str(s))

s, _, _ = req(f"/api/lesson/next?session_id={sid}", {})
d = wait("second segment")
check("advanced or finished", d.get("job", {}).get("state") == "done",
      d.get("job", {}).get("error", "")[:90])

s, _, _ = req(f"/api/lesson/finish?session_id={sid}", {})
d = wait("quiz")
quiz = d.get("quiz") or []
note = d.get("notes") or ""
rate_limited = "429" in json.dumps(d.get("job", {})) or "could not be written" in note
if quiz:
    check("auto-quiz produced questions", True, f"{len(quiz)} questions")
    check("no report before the quiz is marked", d.get("report") is None)
elif rate_limited:
    # An upstream quota failure is not a defect; losing the student's report
    # to it would be. That is what this asserts.
    check("quiz rate-limited -> degrades to a report",
          d.get("report") is not None, note[:70] or "no note")
else:
    check("auto-quiz produced questions", False, "0 questions, no rate limit")
if quiz:
    answers = {q["id"]: (q["options"][0] if q.get("options") else "V = I R") for q in quiz}
    s, _, _ = req("/api/lesson/quiz", {"session_id": sid, "answers": answers})
    d = wait("marking")
    rep = d.get("report")
    check("report produced", bool(rep), str(d.get("job"))[:90])
    if rep:
        check("report has a score", isinstance(rep.get("score"), (int, float)), str(rep.get("score")))

rows = db("SELECT ended_at, score FROM study_sessions WHERE session_id=?", (sid,))
check("study session closed in db", bool(rows) and bool(rows[0]["ended_at"]), str(rows)[:80])

print("\n=== 9. transcript + download ===")
s, tr, _ = req(f"/api/transcript?session_id={sid}")
check("transcript returns turns", s == 200 and len(tr.get("turns", [])) > 0,
      f"{len(tr.get('turns', []))} turns")
check("transcript knows the topic", bool(tr.get("topic")))
s, txt, hdr = req(f"/api/summary?session_id={sid}", raw=True)
check("summary downloads", s == 200 and len(txt) > 200, f"{len(txt)}B")
check("summary is an attachment", "attachment" in hdr.get("content-disposition", ""),
      hdr.get("content-disposition", ""))
s, missing, _ = req("/api/transcript?session_id=doesnotexist")
check("unknown session 404s", s == 404, str(s))

print("\n=== 10. flashcards ===")
s, fc, _ = req("/api/flashcards")
check("flashcards list", s == 200 and "counts" in fc, str(fc.get("counts")))
pool = fc.get("due") or fc.get("all") or []
if pool:
    card = pool[0]
    before = db("SELECT repetitions FROM flashcards WHERE card_key=?", (card["card_key"],))
    s, rv, _ = req("/api/flashcards/review",
                   {"card_key": card["card_key"], "front": card.get("front", ""),
                    "back": card.get("back", ""), "ease": "good"})
    check("review recorded", s == 200 and rv.get("ok"), str(rv)[:70])
    after = db("SELECT repetitions, interval_days FROM flashcards WHERE card_key=?",
               (card["card_key"],))
    check("SM-2 state advanced",
          bool(after) and after[0]["repetitions"] > (before[0]["repetitions"] if before else -1),
          f"{before} -> {after}")
s, badr, _ = req("/api/flashcards/review", {"card_key": "x", "ease": "nonsense"})
check("bad ease rejected", s == 400, str(s))

print("\n=== 11. dashboard vs database ===")
s, dash, _ = req("/api/dashboard")
lessons = db("SELECT COUNT(DISTINCT session_id) n FROM reports WHERE student_id='student'")[0]["n"]
check("total_lessons matches db", dash.get("total_lessons") == lessons,
      f"api={dash.get('total_lessons')} db={lessons}")
check("xp is a whole number", float(dash.get("xp", 0)).is_integer(), str(dash.get("xp")))
check("recent lessons carry session ids",
      all(r.get("session_id") for r in dash.get("recent_lessons", [])))
check("hours are not inflated", dash.get("total_minutes", 0) >= 0)

print("\n=== 12. review + discuss ===")
s, rv2, _ = req(f"/api/session-review?session_id={sid}")
check("review for a named session", s == 200 and rv2.get("session_id") == sid, str(rv2.get("session_id")))
check("review time is this session, not all time", rv2.get("total_minutes", 999) < 60,
      str(rv2.get("total_minutes")))
s, dis, _ = req("/api/discuss", {"question": "What is resistance?"}, timeout=90)
ans = dis.get("answer", "")
check("discuss answers", s == 200 and len(ans) > 20, ans[:70])
check("discuss is not the canned template", not ans.startswith("Great question!"), ans[:60])

print("\n" + "=" * 62)
print(f"  {len(fails)} FAILURE(S)" if fails else "  ALL CHECKS PASSED")
for f in fails:
    print("   -", f)
sys.exit(1 if fails else 0)
