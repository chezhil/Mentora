from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

# Load .env BEFORE orchestrator, which imports llm, which reads the provider
# and the API key at import time. Without this the server always fell back to
# the default provider with no key, and every /api call returned a 500 reading
# "No Groq API key found" even with a perfectly good GROQ_API_KEY sitting in
# .env. app.py has always done this; server.py was missing it.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import llm
import orchestrator as orch
from shared.models import LearnerProfile, StudentResponse
from pathlib import Path

app = FastAPI(title="Mentora API")

frontend_dir = Path(__file__).parent / "frontend"

session_store = {}

@app.get("/")
async def serve_index():
    return FileResponse(frontend_dir / "index.html")

@app.get("/{filename}")
async def serve_file(filename: str):
    # Resolve and confine to frontend/. Without this the route served
    # anything the path resolved to, and being a bare catch-all it also
    # shadows every GET route declared after it.
    try:
        target = (frontend_dir / filename).resolve()
    except (OSError, ValueError):
        return HTMLResponse("Not Found", status_code=404)
    if not target.is_relative_to(frontend_dir.resolve()) or not target.is_file():
        return HTMLResponse("Not Found", status_code=404)
    return FileResponse(target)

@app.post("/api/start")
async def start_lesson(request: Request):
    data = await request.json()
    topic = data.get("topic", "Electricity")
    api_key = data.get("api_key")
    
    if api_key:
        # Setting os.environ here did nothing — llm read the key at import and
        # cached the client holding it, so the key pasted into the web form
        # was never used.
        llm.configure(api_key=api_key)
    
    # Initialize session
    profile = LearnerProfile(
        level="beginner",
        language="en",
        time_minutes=15,
        goal=topic
    )
    session = orch.start_session(topic=topic, profile=profile)
    session_store["current"] = session
    
    # Start the lesson
    segment = orch.step(session)
    media = orch.media_for(session, segment)

    return JSONResponse({
        "status": "started",
        "topic": topic,
        "segment_text": segment.script,
        # Rendered and then discarded: the variable was assigned and never
        # read, so the page had no video, audio or diagram to show even
        # though all three had just been built.
        "media": {
            "video_mp4": media.video_mp4,
            "audio_wav": media.audio_wav,
            "visual_png": media.visual_png,
            "notes": media.notes,
        },
    })

@app.post("/api/ask")
async def ask_question(request: Request):
    data = await request.json()
    question = data.get("question", "")
    session = session_store.get("current")
    
    if not session:
        return JSONResponse({"error": "No active session"}, status_code=400)
        
    reply = orch.ask(session, question)
    return JSONResponse({
        "reply": reply
    })

@app.post("/api/answer")
async def answer_question(request: Request):
    data = await request.json()
    question_id = data.get("question_id")
    answer = data.get("answer")
    session = session_store.get("current")
    
    if not session:
        return JSONResponse({"error": "No active session"}, status_code=400)
        
    response = StudentResponse(question_id=question_id, answer=answer)
    evaluation = orch.answer(session, response)
    
    return JSONResponse({
        "correct": evaluation.correct,
        "feedback": evaluation.feedback,
        "action": evaluation.action
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
