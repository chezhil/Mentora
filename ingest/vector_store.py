"""Vector store management with local ChromaDB."""
from pathlib import Path
from typing import List, Dict, Any
import chromadb
from ingest.embeddings import get_embedder

CHROMA_PERSIST_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma"


def get_chroma_client():
    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))


def store_chunks(doc_id: str, chunks: List[Dict[str, Any]]):
    client = get_chroma_client()
    embedder = get_embedder()

    safe_col_name = f"doc_{doc_id}".replace("-", "_").replace(".", "_")[:63]
    collection = client.get_or_create_collection(name=safe_col_name)

    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
    documents = [c["text"] for c in chunks]
    # Chroma metadata cannot hold None, which is why page used to be coerced
    # to 1 — but load.py returns None for DOCX and TXT, which genuinely have no
    # pages, so every citation from those claimed "page 1". Omit the key
    # instead; query_chunks reads it back as None.
    metadatas = []
    for c in chunks:
        meta = {"section": str(c.get("section") or ""), "doc_id": doc_id}
        if c.get("page") is not None:
            meta["page"] = int(c["page"])
        metadatas.append(meta)
    embeddings = embedder.embed_documents(documents)

    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings
    )


def query_chunks(doc_id: str, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    client = get_chroma_client()
    embedder = get_embedder()

    safe_col_name = f"doc_{doc_id}".replace("-", "_").replace(".", "_")[:63]
    try:
        collection = client.get_collection(name=safe_col_name)
    except Exception:
        return []

    query_embedding = embedder.embed_query(query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    if not results or not results["documents"] or not results["documents"][0]:
        return []

    matched_chunks = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    # strict: Chroma returns the three lists in lockstep. If it ever did
    # not, zip would silently drop the tail and we would cite the wrong
    # page for a chunk.
    for doc_text, meta, dist in zip(docs, metas, distances, strict=True):
        score = max(0.0, min(1.0, 1.0 - (dist / 2.0)))
        matched_chunks.append({
            "text": doc_text,
            "page": meta.get("page"),
            "section": meta.get("section") or None,
            "score": round(float(score), 4)
        })

    return matched_chunks
