"""
U3: Ingest & Retrieve pipeline implementation.
Exposes ingest(path: str) -> str and retrieve(doc_id: str, query: str, k: int) -> list[SourceChunk].
"""
import sys
import os
import uuid
import json
from pathlib import Path
from typing import List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from shared.models import SourceChunk
from ingest.load import load_document
from ingest.chunk import chunk
from ingest.vector_store import store_chunks, query_chunks
from ingest.config import MIN_SCORE


def ingest(path: str) -> str:
    """Ingests file preserving page numbers and returns doc_id."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Cannot ingest: {path} not found")

    stem_clean = "".join(c for c in file_path.stem if c.isalnum() or c in ("_", "-")).lower()
    doc_id = f"{stem_clean}_{uuid.uuid4().hex[:8]}"

    pages = load_document(str(file_path))
    if not pages:
        raise ValueError(f"No content in {path}")

    source_chunks = chunk(pages)
    if not source_chunks:
        raise ValueError(f"Chunking produced 0 chunks for {path}")

    chunk_dicts = [
        {"text": c.text, "page": c.page, "section": c.section}
        for c in source_chunks
    ]
    store_chunks(doc_id=doc_id, chunks=chunk_dicts)
    return doc_id


def retrieve(doc_id: str, query: str, k: int = 4) -> List[SourceChunk]:
    """Retrieves up to k relevant chunks, dropping anything below MIN_SCORE."""
    if not doc_id or not query or not query.strip():
        return []

    raw_matches = query_chunks(doc_id=doc_id, query=query, top_k=k)
    if not raw_matches:
        return []

    source_chunks: List[SourceChunk] = []
    for match in raw_matches:
        score = match.get("score", 0.0)
        if score < MIN_SCORE:
            continue
        source_chunks.append(
            SourceChunk(
                text=match["text"],
                page=match.get("page"),
                section=match.get("section"),
                score=score
            )
        )

    source_chunks.sort(key=lambda c: c.score, reverse=True)
    return source_chunks
