"""Tests for the Qdrant ``VectorStore`` wrapper using in-memory mode."""

from __future__ import annotations

import numpy as np


def test_collection_auto_created(vector_store):
    info = vector_store.get_collection_info()
    assert info["name"] == vector_store.collection_name
    assert info["points_count"] == 0


def test_upsert_and_search(vector_store):
    keys = [f"images/img_{i}.jpg" for i in range(3)]
    rng = np.random.default_rng(42)
    vectors = rng.random((3, 512)).astype(np.float32)
    captions = {f"img_{i}.jpg": f"caption for {i}" for i in range(3)}

    vector_store.upsert_batch(keys, vectors, captions)

    info = vector_store.get_collection_info()
    assert info["points_count"] == 3

    query = vectors[0]
    results = vector_store.search(query, top_k=2)
    assert len(results) == 2
    assert results[0]["image_path"] == "images/img_0.jpg"
    assert results[0]["caption"] == "caption for 0"
    assert results[0]["filename"] == "img_0.jpg"
    assert results[0]["score"] > results[1]["score"] - 1e-6


def test_search_params_exact(vector_store):
    params = vector_store._search_params("exact")
    assert params.exact is True
    assert params.hnsw_ef is None
    assert params.indexed_only is False


def test_search_params_ann(vector_store):
    params = vector_store._search_params("ann", hnsw_ef=256)
    assert params.exact is False
    assert params.hnsw_ef == 256
    assert params.indexed_only is False


def test_search_params_ann_indexed_only(vector_store):
    params = vector_store._search_params("ann_indexed_only", hnsw_ef=64)
    assert params.exact is False
    assert params.hnsw_ef == 64
    assert params.indexed_only is True


def test_upsert_is_idempotent(vector_store):
    rng = np.random.default_rng(7)
    keys = ["images/a.jpg"]
    vec = rng.random((1, 512)).astype(np.float32)
    vector_store.upsert_batch(keys, vec)
    vector_store.upsert_batch(keys, vec)
    assert vector_store.get_collection_info()["points_count"] == 1


def test_delete_collection(vector_store):
    rng = np.random.default_rng(9)
    vector_store.upsert_batch(["images/x.jpg"], rng.random((1, 512)).astype(np.float32))
    vector_store.delete_collection()
    vector_store._ensure_collection()
    assert vector_store.get_collection_info()["points_count"] == 0
