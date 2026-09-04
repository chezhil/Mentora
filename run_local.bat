@echo off
cd /d D:\mentora
set AI_TEACHER_PROVIDER=local
set GEMINI_URL=http://127.0.0.1:8010
set GEMINI_KEY=sk-gemini
set AI_TEACHER_MODEL=gemini-2.5-flash
rem C: is nearly full; keep 2.3GB+ HF model cache on D:
set HF_HOME=D:\hf_cache
python -m uvicorn web.server:app --host 127.0.0.1 --port 8000 --reload
