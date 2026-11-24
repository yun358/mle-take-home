"""Turning text into vectors.

Everything that needs embeddings depends on the small `Embedder` interface, so tests can use a fast fake
and the real model can be swapped without touching the rest of the code.
"""

import hashlib
from typing import Protocol

import numpy as np

from app.config import EMBEDDING_DIMENSIONS


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        """Return one unit-length vector per text."""
        ...


class FakeEmbedder:
    """Deterministic stand-in for tests: the same text always gives the same vector.

    The vectors carry no meaning, so it's only for testing storage and plumbing, never quality.
    """

    model_name = "fake-hash-v1"

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        vector = np.random.default_rng(seed).standard_normal(EMBEDDING_DIMENSIONS)
        return (vector / np.linalg.norm(vector)).astype(np.float32)
