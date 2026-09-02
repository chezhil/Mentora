"""CLI runner for retrieve: python -m ingest.retrieve fixtures/query_en.json"""
import sys
import json
from pathlib import Path
from ingest.pipeline import retrieve
from ingest.config import MIN_SCORE

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m ingest.retrieve <fixture_json_path>")
        sys.exit(1)

    fixture_path = Path(sys.argv[1])
    if not fixture_path.exists():
        print(f"Fixture not found: {fixture_path}")
        sys.exit(1)

    with open(fixture_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    target_doc_id = data.get("doc_id")
    target_query = data.get("query")
    top_k = data.get("k", 4)

    results = retrieve(doc_id=target_doc_id, query=target_query, k=top_k)
    if not results:
        print("[] (No relevant content found in document above threshold)")
    else:
        print(f"Retrieved {len(results)} relevant chunk(s) (MIN_SCORE >= {MIN_SCORE}):")
        for idx, c in enumerate(results, start=1):
            clean_text = c.text.strip().replace("\ufeff", "")
            preview = clean_text[:180] + ("..." if len(clean_text) > 180 else "")
            print(f"\n--- Chunk {idx} | Score: {c.score:.3f} | Page: {c.page} | Section: {c.section} ---")
            print(f"Text: {preview}")
