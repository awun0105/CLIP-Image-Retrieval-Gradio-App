"""Shared pytest fixtures."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from config import Settings
from db.vector_store import VectorStore


@pytest.fixture()
def settings(tmp_path) -> Settings:
    """Settings tuned for tests: in-memory Qdrant, isolated collection name per test."""
    import uuid

    return Settings(
        qdrant_mode="memory",
        qdrant_collection=f"test_{uuid.uuid4().hex[:8]}",
        minio_bucket="test-bucket",
        legacy_images_path=tmp_path / "images",
        legacy_index_path=tmp_path / "embed",
        captions_path=tmp_path / "captions.json",
    )


@pytest.fixture()
def vector_store(settings) -> VectorStore:
    return VectorStore(settings)


@pytest.fixture()
def fake_embedding_service():
    """Deterministic 512-d embedding mock (same vector for same input)."""

    class FakeEmbedding:
        def __init__(self):
            self.is_loaded = True

        def _vec(self, seed: str) -> np.ndarray:
            rng = np.random.default_rng(abs(hash(seed)) % (2**32))
            v = rng.random(512).astype(np.float32)
            return v.reshape(1, -1)

        def get_text_features(self, text: str) -> np.ndarray:
            return self._vec(f"text:{text}")

        def get_image_features(self, image) -> np.ndarray:
            return self._vec(f"image:{id(image)}")

        def get_image_batch_features(self, images) -> np.ndarray:
            return np.vstack([self.get_image_features(image).flatten() for image in images])

    return FakeEmbedding()


@pytest.fixture()
def fake_object_store():
    store = MagicMock()
    store.bucket = "test-bucket"
    store.get_presigned_url.side_effect = lambda key, expires=3600: f"http://minio/{key}"
    store.object_exists.return_value = False
    store.list_objects.return_value = []
    return store
