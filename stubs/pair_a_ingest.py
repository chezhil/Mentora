"""STUB for Utkarsh's half of Pair A — ingest/.

Lets Chezhil build the orchestrator and the app before ingestion exists.
Utkarsh: your real ingest/ replaces this automatically (see wiring.py) the
moment `from ingest.pipeline import ingest, retrieve` works.

The fake document is about electricity, so the brief's own Ohm's Law example
runs end to end.
"""

import hashlib

from ingest.config import MIN_SCORE
from shared.models import SourceChunk

# A fake "textbook". Page numbers are the point — citations depend on them.
_FAKE_DOC = [
    (47, "Voltage is the electrical pressure that pushes charge around a "
         "circuit. It is measured in volts."),
    (47, "Current is the rate at which charge flows past a point in the "
         "circuit, measured in amperes."),
    (48, "Resistance opposes the flow of current. For a fixed voltage, "
         "increasing resistance decreases the current."),
    (49, "Ohm's Law states that V = I x R. Rearranged, I = V / R, so current "
         "is inversely proportional to resistance at constant voltage."),
]

_KEYWORDS = {
    "voltage", "volt", "current", "ampere", "amp", "resistance", "resistor",
    "ohm", "circuit", "charge", "electricity", "electrical",
    # a couple of Hindi terms so the cross-lingual path is exercised
    "vidyut", "dhara", "pratirodh",
}


def ingest(path: str) -> str:
    """Real version parses the file. Stub just mints a stable doc_id."""
    return "stubdoc-" + hashlib.sha1(str(path).encode()).hexdigest()[:8]


def retrieve(doc_id: str, query: str, k: int = 4) -> list[SourceChunk]:
    """Fake scoring by keyword overlap.

    The behaviour that matters is the LAST line: below MIN_SCORE, return []
    rather than the least-bad chunks.
    """
    q = query.lower()
    hits = [w for w in _KEYWORDS if w in q]
    if not hits:
        return []

    scored = []
    for page, text in _FAKE_DOC:
        overlap = sum(1 for w in hits if w in text.lower())
        score = min(0.95, 0.35 + 0.2 * overlap)
        scored.append(SourceChunk(text=text, page=page, section="Chapter 4",
                                  score=score))

    scored.sort(key=lambda c: c.score, reverse=True)
    kept = [c for c in scored if c.score >= MIN_SCORE]
    return kept[:k]
