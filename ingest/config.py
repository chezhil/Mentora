"""Retrieval tuning. CHEZHIL OWNS THIS FILE.

The rest of ingest/ is Utkarsh's. This one file is not — retrieve() reads
MIN_SCORE from here, and only Chezhil changes the number.

If retrieval looks wrong, say what you saw. Do not tune this yourself.
"""

# A chunk scoring below this is not returned at all. If that leaves nothing,
# retrieve() returns [] and the teacher gets to say "that isn't in your
# material" — which is stronger proof of grounding than any correct answer.
#
# Tuning notes (Chezhil): calibrate against fixtures/queries_offtopic.json.
# Too low and off-topic questions get answered from irrelevant chunks.
# Too high and real questions come back empty. 15+ off-topic questions
# should all return [] before this number is considered settled.
MIN_SCORE = 0.45
