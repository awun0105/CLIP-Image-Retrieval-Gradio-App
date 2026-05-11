"""End-to-end tests for the FastAPI routes (services replaced via dependency overrides)."""

from __future__ import annotations

import io
from time import sleep

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import (
    get_embedding_service,
    get_image_service,
    get_indexing_service,
    get_object_store,
    get_search_service,
    get_settings,
    get_vector_store,
)
from core.image_service import ImageService
from core.indexing import IndexingService
from core.search import SearchService


def _seed(vector_store):
    rng = np.random.default_rng(123)
    vectors = rng.random((4, 512)).astype(np.float32)
    keys = [f"images/api_{i}.jpg" for i in range(4)]
    vector_store.upsert_batch(keys, vectors, {f"api_{i}.jpg": f"cap {i}" for i in range(4)})


@pytest.fixture()
def client(settings, vector_store, fake_embedding_service, fake_object_store):
    _seed(vector_store)
    search_service = SearchService(fake_embedding_service, vector_store)
    image_service = ImageService(fake_object_store)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_vector_store] = lambda: vector_store
    app.dependency_overrides[get_object_store] = lambda: fake_object_store
    app.dependency_overrides[get_embedding_service] = lambda: fake_embedding_service
    app.dependency_overrides[get_search_service] = lambda: search_service
    app.dependency_overrides[get_image_service] = lambda: image_service

    # Indexing service isn't exercised here; raise if accidentally pulled.
    def _missing_indexing():
        raise AssertionError("indexing service should not be invoked in this test")

    app.dependency_overrides[get_indexing_service] = _missing_indexing

    with TestClient(app) as c:
        yield c


def test_health(client, fake_object_store):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["minio_bucket"] == fake_object_store.bucket
    assert "indexed_vectors_count" in body["qdrant"]
    assert body["qdrant"]["sample_has_vector"] is True


def test_search_text(client):
    r = client.post("/api/v1/search/text", json={"query": "blue shirt", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["query"] == "blue shirt"
    assert len(body["results"]) == 2
    for item in body["results"]:
        assert item["image_url"].startswith("http://minio/images/")


def test_search_text_with_exact_mode(client):
    r = client.post(
        "/api/v1/search/text",
        json={"query": "blue shirt", "top_k": 2, "search_mode": "exact"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_search_text_validation(client):
    r = client.post("/api/v1/search/text", json={"query": "", "top_k": 5})
    assert r.status_code == 422  # Pydantic min_length

    r = client.post("/api/v1/search/text", json={"query": "ok", "top_k": 0})
    assert r.status_code == 422

    r = client.post("/api/v1/search/text", json={"query": "ok", "search_mode": "bad"})
    assert r.status_code == 422

    r = client.post("/api/v1/search/text", json={"query": "ok", "hnsw_ef": 16})
    assert r.status_code == 422


def test_search_image(client):
    img = Image.new("RGB", (8, 8), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    r = client.post(
        "/api/v1/search/image",
        files={"file": ("test.png", buf, "image/png")},
        params={"top_k": 1, "search_mode": "ann", "hnsw_ef": 64},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1


def test_index_job_api(settings, vector_store, fake_embedding_service, fake_object_store, tmp_path):
    img = Image.new("RGB", (8, 8), color="red")
    img.save(tmp_path / "api_index.jpg")
    indexing_service = IndexingService(
        fake_embedding_service,
        vector_store,
        fake_object_store,
        settings,
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_vector_store] = lambda: vector_store
    app.dependency_overrides[get_object_store] = lambda: fake_object_store
    app.dependency_overrides[get_indexing_service] = lambda: indexing_service
    app.dependency_overrides[get_embedding_service] = lambda: fake_embedding_service

    with TestClient(app) as c:
        r = c.post("/api/v1/index/", json={"images_dir": str(tmp_path)})
        assert r.status_code == 202
        started = r.json()
        assert started["status"] == "queued"
        assert started["status_url"].startswith("/api/v1/index/")

        for _ in range(50):
            status = c.get(started["status_url"])
            assert status.status_code == 200
            body = status.json()
            if body["status"] == "completed":
                break
            sleep(0.02)

        assert body["status"] == "completed"
        assert body["indexed_count"] == 1
        assert body["scanned_count"] == 1
