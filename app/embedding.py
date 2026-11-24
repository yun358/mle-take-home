"""Turning text into vectors.

Every embedder is a class with a `model_name` and an `embed(texts)` method that returns one vector per text.
Tests use the fast fake below; the real model will be another class with the same two things, so the rest
of the code doesn't change.
"""

import hashlib

import numpy as np

from app.config import EMBEDDING_DIMENSIONS


class FakeEmbedder:
    """Deterministic stand-in for tests: the same text always gives the same vector.

    The vectors carry no meaning, so it's only for testing storage and plumbing, never quality.
    """

    model_name = "fake-hash-v1"

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        """Return one unit-length vector per text."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        vector = np.random.default_rng(seed).standard_normal(EMBEDDING_DIMENSIONS)
        return (vector / np.linalg.norm(vector)).astype(np.float32)
