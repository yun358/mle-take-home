"""Turning text into vectors.

Every embedder is a class with a `model_name` and an `embed(texts)` method that returns one unit-length vector
per text. The consumer uses the real model (MiniLMEmbedder); tests use FakeEmbedder, which is fast and needs
no download.
"""

import hashlib
import urllib.request
from pathlib import Path

import numpy as np
import onnxruntime
from tokenizers import Tokenizer

from app.config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, MODEL_DIR

# The model, pinned to an exact revision of the official Hugging Face repo so it can't change under us.
MODEL_REPO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
MODEL_FILE = "onnx/model_quint8_avx2.onnx"  # the official quantised (8-bit) version: 118 MB instead of 470 MB
TOKENIZER_FILE = "tokenizer.json"
MAX_TOKENS = 128  # the model was trained on texts up to 128 tokens; longer ones are cut


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


class MiniLMEmbedder:
    """paraphrase-multilingual-MiniLM-L12-v2, run on the CPU with onnxruntime.

    Three steps per text:
    1. The tokenizer splits the text into tokens (word pieces) and turns them into numbers.
    2. The model turns each token into a 384-number vector, taking the rest of the sentence into account.
    3. Mean pooling: average the token vectors into one vector for the whole text, then scale it to length 1.
    """

    model_name = f"paraphrase-multilingual-MiniLM-L12-v2-quint8@{MODEL_REVISION[:7]}"

    def __init__(self, model_dir: Path = MODEL_DIR):
        self.tokenizer = Tokenizer.from_file(str(download(TOKENIZER_FILE, model_dir)))
        self.tokenizer.enable_padding()  # pad shorter texts in a batch so they all have the same length
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self.session = onnxruntime.InferenceSession(str(download(MODEL_FILE, model_dir)))

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        """Return one unit-length vector per text."""
        encodings = self.tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)  # 1 = real token, 0 = padding
        model_inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": np.zeros_like(input_ids),  # the model expects it; all zeros for single sentences
        }
        token_vectors = self.session.run(None, model_inputs)[0]  # shape: (texts, tokens, 384)

        # Mean pooling over the real tokens only: padding tokens are multiplied by 0.
        mask = attention_mask[:, :, np.newaxis]
        vectors = (token_vectors * mask).sum(axis=1) / mask.sum(axis=1)
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        return [vector.astype(np.float32) for vector in vectors]


def download(path_in_repo: str, model_dir: Path) -> Path:
    """Download one file from the pinned model repo, unless it's already there. Returns the local path."""
    target = model_dir / Path(path_in_repo).name
    if target.exists():
        return target

    url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{path_in_repo}"
    print(f"downloading {url} (first run only)", flush=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")  # download under another name, so a cut-off download isn't used
    urllib.request.urlretrieve(url, partial)
    partial.rename(target)
    return target


def make_embedder() -> FakeEmbedder | MiniLMEmbedder:
    """The embedder chosen by the EMBEDDING_MODEL setting."""
    if EMBEDDING_MODEL == "fake":
        return FakeEmbedder()
    return MiniLMEmbedder()
