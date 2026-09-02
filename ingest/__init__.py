"""Ingest package.

The convenience re-exports below are LAZY on purpose. Importing them eagerly
made `from ingest.config import MIN_SCORE` pull in pipeline -> vector_store ->
chromadb -> torch, so anyone without the full 2GB stack (Pairs B and C) could
not even start app.py — wiring.py died at import instead of falling back to
stubs.

PEP 562 module __getattr__ keeps `from ingest import retrieve` working while
leaving `ingest.config` importable on its own.
"""

import importlib

_LAZY = {
    "ingest": "ingest.pipeline",
    "retrieve": "ingest.pipeline",
    "load_pdf": "ingest.load",
    "load_docx": "ingest.load",
    "load_pptx": "ingest.load",
    "load_txt": "ingest.load",
    "chunk": "ingest.chunk",
}

__all__ = list(_LAZY)


def __getattr__(name: str):
    if name in _LAZY:
        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module 'ingest' has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
