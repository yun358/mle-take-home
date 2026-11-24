"""The real model. Skipped if its files haven't been downloaded yet (running the consumer once downloads them),
so the rest of the tests, and CI, don't need the 128 MB download.
"""

import numpy as np
import pytest

from app.config import MODEL_DIR
from app.embedding import MiniLMEmbedder

MODEL_DOWNLOADED = (MODEL_DIR / "model_quint8_avx2.onnx").exists() and (MODEL_DIR / "tokenizer.json").exists()

pytestmark = pytest.mark.skipif(not MODEL_DOWNLOADED, reason="model not downloaded: run `just consume` once")


@pytest.fixture(scope="module")  # load the model once for this file, not once per test
def model():
    return MiniLMEmbedder()


def test_each_text_becomes_384_numbers_of_length_one(model):
    vectors = model.embed(["Operating cafes and coffee shops", "Cold chain transport"])

    assert len(vectors) == 2
    for vector in vectors:
        assert vector.shape == (384,)
        assert abs(np.linalg.norm(vector) - 1) < 1e-5


def test_same_text_gives_the_same_vector(model):
    first, second = model.embed(["Boutique hotel", "Boutique hotel"])
    assert np.allclose(first, second)


def test_english_and_malay_versions_are_closer_than_unrelated_text(model):
    english, malay, unrelated = model.embed(
        [
            "Operating cafes and coffee shops",
            "Mengusahakan kedai kopi dan kafe",
            "Production of rubber gloves for export",
        ]
    )
    # Vectors have length 1, so the dot product is the cosine similarity.
    assert english @ malay > english @ unrelated + 0.3
