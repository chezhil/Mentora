"""Orchestrator tuning dials. Chezhil owns this file.

Every number here is a judgement call that produces working code when it is
wrong. Change them deliberately, not while debugging something else.
"""

# How many recent turns go to the LLM in full. Everything older is collapsed
# into one summary Turn. Raising this is the fastest way to blow the provider's
# rate limit on a 60-minute lesson.
CONTEXT_FULL_TURNS = 6

# Hard ceiling on the summary that stands in for older turns.
CONTEXT_SUMMARY_MAX_CHARS = 600

# After this many failed attempts on one concept, stop re-explaining and move
# on. Without this the lesson can loop forever on a student who keeps missing.
MAX_REEXPLAIN_ATTEMPTS = 3

# How many chunks to ask retrieve() for.
RETRIEVE_K = 4

# Pair C refuses audio longer than this. We check before calling so the
# orchestrator degrades to text instead of raising in the middle of a lesson.
MAX_AVATAR_SECONDS = 60

# Rough words-per-second for estimating narration length before we send it.
WORDS_PER_SECOND = 2.5
