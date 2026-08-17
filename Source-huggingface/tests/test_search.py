import json
from pathlib import Path
from threading import Event

import numpy as np
import pandas as pd
import pytest
from clusterer import ImageIndexer
from PIL import Image

from db import ScanCancelled, SearchMechanism


class FakeClipSearcher:
    def __init__(self, query=None, cancel_event=None):
        self.query = np.asarray(query if query is not None else [[1.0, 0.0]], dtype=np.float32)
        self.cancel_event = cancel_event
        self.batch_calls = 0

    def get_text_features(self, _text):
        return self.query

    def get_image_features(self, _image):
        return self.query

    def get_image_batch_features(self, images):
        self.batch_calls += 1
        if self.cancel_event is not None:
            self.cancel_event.set()
        return np.tile(self.query, (len(images), 1))


def _make_store(tmp_path: Path, *, separator="\t", paths=None, embeddings=None):
    images_path = tmp_path / "images"
    index_path = tmp_path / "embed_data"
    images_path.mkdir()
    index_path.mkdir()
    paths = paths or ["a.jpg", "b.png", "c.webp"]
    for name in ["a.jpg", "b.png", "c.webp"]:
        Image.new("RGB", (4, 4), "red").save(images_path / name)
    dataframe = pd.DataFrame({"image_path": paths})
    dataframe.to_csv(index_path / "df.csv", sep=separator, index=False)
    vectors = np.asarray(
        embeddings if embeddings is not None else [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
        dtype=np.float32,
    )
    np.save(index_path / "df_image_embeds.npy", vectors)
    captions_path = tmp_path / "captions.json"
    captions_path.write_text(json.dumps({"a.jpg": "red item"}), encoding="utf-8")
    store = SearchMechanism(
        FakeClipSearcher(),
        ImageIndexer(index_path),
        str(images_path),
        captions_path,
    )
    return store, images_path, index_path


@pytest.mark.parametrize("separator", ["\t", ","])
def test_exact_search_is_vectorized_and_sorted(tmp_path, separator):
    store, _images, _index = _make_store(tmp_path, separator=separator)
    results = store.query_by_text("red", top_k=2)
    assert [result.filename for result in results] == ["a.jpg", "b.png"]
    assert results[0].score == pytest.approx(1.0)
    assert results[0].caption == "red item"


def test_windows_image_paths_resolve_to_dataset(tmp_path):
    store, images_path, _index = _make_store(
        tmp_path,
        paths=[r"C:\dataset\a.jpg", r"C:\dataset\b.png", r"C:\dataset\c.webp"],
    )
    assert store.df.iloc[1]["image_path"] == str(images_path / "b.png")


def test_row_count_mismatch_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="row count"):
        _make_store(tmp_path, paths=["a.jpg", "b.png"])


def test_faiss_search_uses_cosine_scores(tmp_path):
    store, _images, _index = _make_store(tmp_path)
    results = store.query_by_text(
        "red",
        top_k=2,
        use_cluster_search=True,
        faiss_nprobe=4,
    )
    assert results[0].filename == "a.jpg"
    assert results[0].score == pytest.approx(1.0)


def test_faiss_nprobe_is_clamped_to_ivf_cluster_count(tmp_path):
    rng = np.random.default_rng(0)
    vectors = rng.random((1_000, 4), dtype=np.float32)
    indexer = ImageIndexer(tmp_path)
    indexer.fit(vectors)

    indexer.predict(vectors, vectors[0], 2, nprobe=999)
    assert indexer.index.nprobe == indexer.index.nlist
    indexer.predict(vectors, vectors[0], 2, nprobe=0)
    assert indexer.index.nprobe == 1


def test_cancelled_reindex_keeps_previous_artifacts(tmp_path):
    cancel_event = Event()
    store, images_path, index_path = _make_store(tmp_path)
    store.clip_searcher = FakeClipSearcher(cancel_event=cancel_event)
    old_dataframe = (index_path / "df.csv").read_bytes()
    old_embeddings = (index_path / "df_image_embeds.npy").read_bytes()

    with pytest.raises(ScanCancelled):
        store.scan_directory(images_path, batch_size=1, cancel_event=cancel_event)

    assert (index_path / "df.csv").read_bytes() == old_dataframe
    assert (index_path / "df_image_embeds.npy").read_bytes() == old_embeddings
    assert not list(index_path.glob(".reindex-*"))


def test_successful_reindex_atomically_installs_v2_artifacts(tmp_path):
    store, images_path, index_path = _make_store(tmp_path)
    completed = []
    count = store.scan_directory(
        images_path,
        batch_size=2,
        progress=lambda current, total: completed.append((current, total)),
    )

    assert count == 3
    assert completed == [(2, 3), (3, 3)]
    assert len(pd.read_csv(index_path / "df.csv", sep="\t")) == 3
    assert np.load(index_path / "df_image_embeds.npy").shape == (3, 2)
    assert (index_path / ImageIndexer.INDEX_FILENAME).exists()
    assert (index_path / ImageIndexer.METADATA_FILENAME).exists()
    assert len(store.query_by_text("red", top_k=2, use_cluster_search=True)) == 2


def test_reindex_rejects_paths_outside_configured_dataset(tmp_path):
    store, _images, _index = _make_store(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="restricted"):
        store.scan_directory(other)
