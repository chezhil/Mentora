"""Multilingual embedding generator using BGE-M3."""
import os
from typing import List
import numpy as np


class MultilingualEmbeddingFunction:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                try:
                    self._model = SentenceTransformer(self.model_name)
                except Exception as e:
                    fallback_model = "paraphrase-multilingual-MiniLM-L12-v2"
                    self._model = SentenceTransformer(fallback_model)
            except Exception:
                self._model = "fallback"
        return self._model

    def __call__(self, input: List[str]) -> List[List[float]]:
        return self.embed_documents(input)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        model = self._get_model()
        if model == "fallback":
            return [self._fallback_embed(t) for t in texts]

        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()

    def embed_query(self, query: str) -> List[float]:
        return self.embed_documents([query])[0]

    def _fallback_embed(self, text: str, dim: int = 384) -> List[float]:
        import hashlib
        vec = np.zeros(dim, dtype=np.float32)
        words = text.lower().split()
        for w in words:
            h = int(hashlib.md5(w.encode('utf-8')).hexdigest(), 16)
            idx = h % dim
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()


_GLOBAL_EMBEDDER = None

def get_embedder() -> MultilingualEmbeddingFunction:
    global _GLOBAL_EMBEDDER
    if _GLOBAL_EMBEDDER is None:
        _GLOBAL_EMBEDDER = MultilingualEmbeddingFunction()
    return _GLOBAL_EMBEDDER
