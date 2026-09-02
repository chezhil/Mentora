"""Multilingual embedding generator using BGE-M3.

WHY THIS FILE FAILS LOUDLY

The brief requires teaching from an English textbook in Hindi, which means a
Hindi question must find the right English paragraph. BGE-M3 is what makes
that work. An earlier version of this file quietly fell back — first to a
different model, then to a hash-of-words vector — and printed nothing.

That hash fallback is keyword matching. A Hindi query and an English chunk
share no words, so cross-lingual retrieval returns nothing useful while the
app carries on looking healthy. It is the exact failure the pair brief warned
about: you would not notice until the demo.

So: BGE-M3 or a crash. If you genuinely need to run without it (no internet
on the demo machine, say), set MENTORA_EMBED_FALLBACK=1 and you get a
multilingual MiniLM plus a banner on every startup so nobody forgets.
"""

import os
import sys
from typing import List

PRIMARY_MODEL = "BAAI/bge-m3"
FALLBACK_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
FALLBACK_ENV = "MENTORA_EMBED_FALLBACK"


class EmbeddingModelUnavailable(RuntimeError):
    """BGE-M3 could not be loaded and no fallback was authorised."""


class MultilingualEmbeddingFunction:
    def __init__(self, model_name: str = PRIMARY_MODEL):
        self.model_name = model_name
        self.active_model: str | None = None   # what actually loaded
        self._model = None

    def _get_model(self):
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise EmbeddingModelUnavailable(
                "sentence-transformers is not installed, so no embeddings are "
                "possible.\n"
                "    Fix:  pip install -r requirements.txt"
            ) from exc

        try:
            self._model = SentenceTransformer(self.model_name)
            self.active_model = self.model_name
            return self._model
        except Exception as primary_exc:
            if os.environ.get(FALLBACK_ENV) != "1":
                raise EmbeddingModelUnavailable(
                    f"Could not load {self.model_name}: {primary_exc}\n"
                    f"    This model is required — it is what lets a Hindi "
                    f"question find an English paragraph.\n"
                    f"    Fix:  check the network and let the ~2GB download "
                    f"finish, then retry.\n"
                    f"    Override (degrades multilingual quality, and says "
                    f"so on every run):  {FALLBACK_ENV}=1"
                ) from primary_exc

            self._model = SentenceTransformer(FALLBACK_MODEL)
            self.active_model = FALLBACK_MODEL
            self._warn_fallback(primary_exc)
            return self._model

    @staticmethod
    def _warn_fallback(exc: Exception) -> None:
        banner = (
            "\n" + "!" * 72 + "\n"
            f"  DEGRADED: {PRIMARY_MODEL} failed to load, using {FALLBACK_MODEL}\n"
            f"  because {FALLBACK_ENV}=1 is set.\n"
            f"  Cross-lingual retrieval will be WORSE than what we demo.\n"
            f"  Reason: {exc}\n"
            + "!" * 72 + "\n"
        )
        print(banner, file=sys.stderr, flush=True)

    def __call__(self, input: List[str]) -> List[List[float]]:
        return self.embed_documents(input)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        model = self._get_model()
        # normalize_embeddings is load-bearing: vector_store turns Chroma's
        # squared-L2 distance back into cosine similarity with 1 - d/2, which
        # is only correct for unit vectors. MIN_SCORE is calibrated against
        # that scale. Do not remove.
        embeddings = model.encode(texts, normalize_embeddings=True,
                                  show_progress_bar=False)
        return embeddings.tolist()

    def embed_query(self, query: str) -> List[float]:
        return self.embed_documents([query])[0]


_GLOBAL_EMBEDDER = None


def get_embedder() -> MultilingualEmbeddingFunction:
    global _GLOBAL_EMBEDDER
    if _GLOBAL_EMBEDDER is None:
        _GLOBAL_EMBEDDER = MultilingualEmbeddingFunction()
    return _GLOBAL_EMBEDDER
