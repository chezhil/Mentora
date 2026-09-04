import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import llm
import orchestrator as orch
from shared.models import LearnerProfile, StudentResponse
from utils_gesture import parse_gestures

app = FastAPI(title="Mentora API")

frontend_dir = Path(__file__).parent / "frontend"

session_store = {}

@app.get("/")
async def serve_index():
    return FileResponse(frontend_dir / "index.html")

@app.get("/{filename}")
async def serve_file(filename: str):
    try:
        target = (frontend_dir / filename).resolve()
    except (OSError, ValueError):
        return HTMLResponse("Not Found", status_code=404)
    if not target.is_relative_to(frontend_dir.resolve()) or not target.is_file():
        return HTMLResponse("Not Found", status_code=404)
    return FileResponse(target)

@app.get("/api/media")
async def get_media(path: str):
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse("Not Found", status_code=404)

@app.post("/api/start")
async def start_lesson(request: Request):
    data = await request.json()
    topic = data.get("topic", "Electricity")
    api_key = data.get("api_key")
    
    if api_key:
        llm.configure(api_key=api_key)
    
    profile = LearnerProfile(
        level="beginner",
        language="en",
        time_minutes=15,
        goal=topic
    )
    session = orch.start_session(topic=topic, profile=profile)
    session_store["current"] = session
    
    segment = orch.step(session)
    media = orch.media_for(session, segment)
    
    clean_text, gestures = parse_gestures(segment.script)

    return JSONResponse({
        "status": "started",
        "topic": topic,
        "segment_text": clean_text,
        "gestures": gestures,
        "audio_url": f"/api/media?path={media.audio_wav}" if media and media.audio_wav else None,
        "visual_url": f"/api/media?path={media.visual_png}" if media and media.visual_png else None,
        "media": {
            "video_mp4": media.video_mp4,
            "audio_wav": media.audio_wav,
            "visual_png": media.visual_png,
            "notes": media.notes,
        },
    })

import wiring

@app.post("/api/ask")
async def ask_question(request: Request):
    data = await request.json()
    question = data.get("question", "")
    session = session_store.get("current")
    
    if not session:
        return JSONResponse({"error": "No active session"}, status_code=400)
        
    reply = orch.ask(session, question)
    
    clean_text, gestures = parse_gestures(reply)
    
    audio_wav = None
    try:
        audio_wav = wiring.speak(clean_text, session.profile.language)
    except Exception as exc:
        print(f"TTS generation failed: {exc}")
    
    return JSONResponse({
        "reply": clean_text,
        "gestures": gestures,
        "audio_url": f"/api/media?path={audio_wav}" if audio_wav else None
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
