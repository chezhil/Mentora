"""Retrieval tuning. CHEZHIL OWNS THIS FILE.

The rest of ingest/ is Utkarsh's. This one file is not — retrieve() reads
MIN_SCORE from here, and only Chezhil changes the number.

If retrieval looks wrong, say what you saw. Do not tune this yourself.
"""

# A chunk scoring below this is not returned at all. If that leaves nothing,
# retrieve() returns [] and the teacher gets to say "that isn't in your
# material" — which is stronger proof of grounding than any correct answer.
#
# Tuning notes (Chezhil). Measured 3 Sep against fixtures/sample.pdf with
# 200-word chunks, over 7 on-topic queries (English and Hindi) and 8 off-topic:
#
#     lowest on-topic    0.465   "what is an ampere"
#     highest off-topic  0.408   "explain the French Revolution"
#     separation        +0.057
#
# 0.44 sits near the midpoint, leaving ~0.025 either way. It was 0.45, which
# left only 0.015 above the lowest on-topic query — one unlucky phrasing from
# telling a student their own textbook does not cover the topic.
#
# Two things this number depends on, so re-measure if either changes:
#   - chunk size (see ingest/chunk.py — bigger chunks collapse the separation)
#   - the document itself; this is a 10-page extract, not the real textbook
#
# Cross-lingual queries score systematically lower than the same question in
# English, so the false "not in your material" answer will appear in Hindi
# first.
MIN_SCORE = 0.44
