# Mentora AI Teacher — Setup & Deployment Guide

## APIs and Third-Party Services
The Mentora AI Teacher solution utilizes the following third-party libraries, embedding models, and services:

1. **Google GenAI SDK (`google-genai`)**:
   - Used for LLM generation, lesson structuring, misconception diagnosis, and multi-turn student adaptation using Gemini Flash.
2. **BAAI BGE-M3 (`BAAI/bge-m3`)**:
   - 1024-dimensional dense multilingual embedding model used for cross-lingual vector retrieval. Maps non-English student queries (Hindi, Hinglish, Tamil, Kannada) into the same semantic vector space as English textbook material.
3. **ChromaDB (`chromadb`)**:
   - Embedded local vector database used for storing chunk embeddings, document metadata, page numbers, and section markers without requiring an external database server.
4. **PyMuPDF (`fitz` / `pymupdf`)**:
   - High-performance PDF parser used for page-by-page text extraction, preserving exact physical page indices.
5. **Document Parsers (`python-docx`, `python-pptx`)**:
   - Extractor libraries for Word documents and PowerPoint slide presentations.
6. **SQLite3 (`sqlite3`)**:
   - Zero-dependency built-in relational database (`mentora.db`) for conversation turns, evaluation records, and cross-session student learner profiles.
7. **Pillow & Matplotlib (`PIL`, `matplotlib`)**:
   - Code-driven graphic rendering engines for mathematical equations, diagrams, and concept maps (no generative AI hallucinations).
8. **imageio-ffmpeg**:
   - Embedded FFmpeg binary distribution for cross-platform audio/video muxing and stitching without requiring system-level FFmpeg installs on macOS, Windows, or Linux.
9. **Streamlit (`streamlit`)**:
   - Reactive interactive web interface featuring the Live Teacher Adaptation Panel.

---

## Setup Instructions

### Prerequisites
- Python 3.11 (Recommended to manage with `uv`)
- Git

### 1. Clone the Repository
```bash
git clone https://github.com/chezhil/Mentora.git
cd Mentora
```

### 2. Set Up Virtual Environment with Python 3.11
Using `uv` (Fastest, zero-admin setup):
```bash
# Install uv if not already installed:
# Windows (PowerShell):
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS / Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and activate:
uv venv --python 3.11 .venv

# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
uv pip install -r requirements.txt
```

### 4. Verify Standalone Module Fixtures
Run all standalone validation tests:
```bash
# 1. Test Document Loading (PyMuPDF with page tracking)
python -m ingest.load fixtures/sample.pdf

# 2. Test Semantic Chunking (500-800 words with sentence preservation)
python -m ingest.chunk fixtures/sample.pdf

# 3. Test Multilingual Ingestion & Retrieval (BGE-M3 + ChromaDB)
python -m ingest.retrieve fixtures/query_en.json
python -m ingest.retrieve fixtures/query_hi.json
python -m ingest.retrieve fixtures/query_offtopic.json

# 4. Test SQLite Persistence & Cross-Session Memory
python -m history.selftest

# 5. Run Master End-to-End Smoke Test
python smoke_test.py
```

---

## Deployment Instructions

### Local Development / Evaluation Server
To run the full interactive web application:
```bash
streamlit run app.py
```
Access the application in your browser at `http://localhost:8501`.
