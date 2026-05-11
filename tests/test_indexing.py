"""Tests for incremental image ingestion."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from core.indexing import IndexingService


class FakeObjectStore:
    def __init__(self):
        self.objects: set[str] = set()
        self.upload_calls: list[str] = []

    def object_exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def upload_file(self, file_path: str, object_key: str) -> None:
        self.objects.add(object_key)
        self.upload_calls.append(object_key)

    def list_objects(self, prefix: str = "") -> list[str]:
        return [key for key in self.objects if key.startswith(prefix)]


class CountingEmbedding:
    def __init__(self):
        self.batch_calls = 0
        self.encoded_images = 0

    def get_image_batch_features(self, images) -> np.ndarray:
        self.batch_calls += 1
        self.encoded_images += len(images)
        return np.vstack(
            [
                np.full(512, fill_value=(self.encoded_images + i) / 1000, dtype=np.float32)
                for i, _image in enumerate(images)
            ]
        )


def _write_image(path: Path, color: str) -> None:
    Image.new("RGB", (8, 8), color=color).save(path)


def test_index_directory_skips_unchanged_images(settings, vector_store, tmp_path):
    _write_image(tmp_path / "a.jpg", "red")
    _write_image(tmp_path / "b.jpg", "blue")
    object_store = FakeObjectStore()
    embedding = CountingEmbedding()
    service = IndexingService(embedding, vector_store, object_store, settings)

    first = service.index_directory(tmp_path)

    assert first.scanned_count == 2
    assert first.indexed_count == 2
    assert first.skipped_count == 0
    assert vector_store.get_collection_info()["points_count"] == 2
    assert len(object_store.upload_calls) == 2
    assert embedding.encoded_images == 2

    second = service.index_directory(tmp_path)

    assert second.scanned_count == 2
    assert second.indexed_count == 0
    assert second.skipped_count == 2
    assert second.failed_count == 0
    assert len(object_store.upload_calls) == 2
    assert embedding.encoded_images == 2


def test_index_directory_repairs_missing_minio_object(settings, vector_store, tmp_path):
    _write_image(tmp_path / "a.jpg", "red")
    object_store = FakeObjectStore()
    embedding = CountingEmbedding()
    service = IndexingService(embedding, vector_store, object_store, settings)
    service.index_directory(tmp_path)
    object_store.objects.remove("images/a.jpg")

    repaired = service.index_directory(tmp_path)

    assert repaired.uploaded_only_count == 1
    assert repaired.indexed_count == 0
    assert repaired.updated_count == 0
    assert repaired.skipped_count == 0
    assert vector_store.get_collection_info()["points_count"] == 1
    assert object_store.upload_calls == ["images/a.jpg", "images/a.jpg"]
    assert embedding.encoded_images == 1


def test_index_directory_updates_changed_image(settings, vector_store, tmp_path):
    image_path = tmp_path / "a.jpg"
    _write_image(image_path, "red")
    object_store = FakeObjectStore()
    embedding = CountingEmbedding()
    service = IndexingService(embedding, vector_store, object_store, settings)
    service.index_directory(tmp_path)
    old_payload = vector_store.get_payload("images/a.jpg")

    _write_image(image_path, "green")
    updated = service.index_directory(tmp_path)
    new_payload = vector_store.get_payload("images/a.jpg")

    assert updated.indexed_count == 0
    assert updated.updated_count == 1
    assert updated.skipped_count == 0
    assert vector_store.get_collection_info()["points_count"] == 1
    assert old_payload["content_hash"] != new_payload["content_hash"]
    assert len(object_store.upload_calls) == 2
    assert embedding.encoded_images == 2
