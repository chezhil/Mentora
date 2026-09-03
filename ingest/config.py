"""Retrieval tuning. CHEZHIL OWNS THIS FILE.

The rest of ingest/ is Utkarsh's. This one file is not — retrieve() reads
MIN_SCORE from here, and only Chezhil changes the number.

If retrieval looks wrong, say what you saw. Do not tune this yourself.
"""

# A chunk scoring below this is not returned at all. If that leaves nothing,
# retrieve() returns [] and the teacher gets to say "that isn't in your
# material" — which is stronger proof of grounding than any correct answer.
#
# Tuning notes (Chezhil). Calibrated across TWO documents, because one was
# not enough — a threshold fitted to the electricity extract alone let an
# electricity question through against the biology one.
#
#   fixtures/sample.pdf (electricity, 10pp)
#       lowest on-topic    0.465  "what is an ampere"
#       highest off-topic  0.408  "explain the French Revolution"
#
#   fixtures/biology_photosynthesis.pdf (10pp)
#       lowest on-topic    0.469  "what does RuBisCO do"
#       highest off-topic  0.448  "how does resistance affect current"
#
# Any value in (0.448, 0.465] satisfies both. 0.455 is the midpoint of that
# window. It was 0.44, which kept the electricity question above.
#
# THE WINDOW IS ONLY 0.017 WIDE. A single global threshold is marginal, and it
# will not hold for every document. The near miss is instructive: "how does
# resistance affect current" is not absurd against a text about rates and
# limiting factors, it is genuinely adjacent. If this keeps biting, the fix is
# a relative rule — keep chunks within a margin of the top hit, and require
# the top hit to clear a floor — rather than a tighter constant.
#
# Re-measure whenever chunk size changes (see ingest/chunk.py) or against the
# real textbook. Cross-lingual queries score lower than the same question in
# English, so a false "not in your material" shows up in Hindi first.
MIN_SCORE = 0.455
