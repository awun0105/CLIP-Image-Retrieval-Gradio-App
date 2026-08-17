import sqlite3
from pathlib import Path

import faiss
import numpy as np
import pytest
from clusterer import ImageIndexer
from schemas import PreparedQuery, SearchFilters

from db import SearchMechanism


class FakeClipSearcher:
    def __init__(self, query=(1.0, 0.0)):
        self.query = np.asarray([query], dtype=np.float32)

    def get_text_features(self, _text):
        return self.query


class FakeTranslator:
    def prepare(self, query, requested_language):
        normalized = " ".join(query.split())
        if not normalized:
            raise ValueError("Query text cannot be empty")
        return PreparedQuery(normalized, normalized, requested_language, "english")


def _make_store(tmp_path: Path) -> SearchMechanism:
    data_root = tmp_path / "release"
    image_paths = [
        "keyframes/C01/V01/001.jpg",
        "keyframes/C01/V01/002.jpg",
        "keyframes/C02/V02/001.jpg",
    ]
    for relative_path in image_paths:
        path = data_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")

    embeddings = np.asarray([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]], dtype=np.float32)
    embeddings_file = tmp_path / "embeddings.npy"
    np.save(embeddings_file, embeddings.astype(np.float16))
    index = faiss.IndexFlatIP(2)
    index.add(embeddings)
    index_file = tmp_path / "keyframes.faiss"
    faiss.write_index(index, str(index_file))

    sqlite_file = tmp_path / "runtime.sqlite"
    connection = sqlite3.connect(sqlite_file)
    connection.executescript(
        """
        CREATE TABLE videos (
            video_id TEXT PRIMARY KEY, collection_id TEXT, title TEXT, author TEXT,
            channel_id TEXT, channel_url TEXT, description TEXT, keywords_json TEXT,
            duration_sec INTEGER, publish_date_raw TEXT, publish_date_iso TEXT,
            thumbnail_url TEXT, watch_url TEXT
        );
        CREATE TABLE keyframes (
            vector_id INTEGER PRIMARY KEY, keyframe_id TEXT UNIQUE, video_id TEXT,
            collection_id TEXT, keyframe_no INTEGER, frame_idx INTEGER,
            pts_time_sec REAL, fps REAL, width INTEGER, height INTEGER,
            image_relpath TEXT
        );
        CREATE TABLE detections (
            keyframe_id TEXT, rank INTEGER, entity TEXT, class_mid TEXT,
            class_label INTEGER, score REAL, ymin REAL, xmin REAL, ymax REAL, xmax REAL
        );
        """
    )
    connection.executemany(
        "INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "V01",
                "C01",
                "First video",
                "Alice",
                "channel-1",
                "",
                "description",
                "[]",
                60,
                "01/01/2024",
                "2024-01-01",
                "",
                "https://example.com/watch?v=1",
            ),
            (
                "V02",
                "C02",
                "Second video",
                "Bob",
                "channel-2",
                "",
                "",
                "[]",
                90,
                "01/02/2024",
                "2024-02-01",
                "",
                "https://example.com/watch?v=2",
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO keyframes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (0, "V01_001", "V01", "C01", 1, 30, 1.0, 30.0, 640, 360, image_paths[0]),
            (1, "V01_002", "V01", "C01", 2, 60, 2.0, 30.0, 640, 360, image_paths[1]),
            (2, "V02_001", "V02", "C02", 1, 90, 3.0, 30.0, 1280, 720, image_paths[2]),
        ],
    )
    connection.executemany(
        "INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("V01_001", 1, "Person", "/m/person", 1, 0.9, 0.1, 0.1, 0.9, 0.9),
            ("V01_002", 1, "Car", "/m/car", 2, 0.8, 0.2, 0.2, 0.8, 0.8),
            ("V01_002", 2, "Person", "/m/person", 1, 0.7, 0.1, 0.1, 0.9, 0.9),
            ("V02_001", 1, "Car", "/m/car", 2, 0.4, 0.2, 0.2, 0.8, 0.8),
        ],
    )
    connection.commit()
    connection.close()

    return SearchMechanism(
        FakeClipSearcher(),
        FakeTranslator(),
        ImageIndexer(index_file),
        sqlite_file,
        embeddings_file,
        data_root,
    )


def test_unfiltered_search_uses_faiss_cosine_order(tmp_path):
    store = _make_store(tmp_path)
    outcome = store.search_by_text("red car", top_k=3)
    assert [result.keyframe_id for result in outcome.results] == [
        "V01_001",
        "V01_002",
        "V02_001",
    ]
    assert outcome.results[0].score == pytest.approx(1.0)
    assert outcome.results[1].score == pytest.approx(0.8)


def test_object_filter_selects_candidates_before_exact_cosine(tmp_path):
    store = _make_store(tmp_path)
    filters = SearchFilters(object_entities=("Car",), minimum_object_confidence=0.5)
    outcome = store.search_by_text("red car", top_k=3, filters=filters)
    assert [result.keyframe_id for result in outcome.results] == ["V01_002"]
    assert outcome.results[0].score == pytest.approx(0.8, abs=0.001)


def test_all_object_filter_and_metadata_filters_are_strict(tmp_path):
    store = _make_store(tmp_path)
    filters = SearchFilters(
        collections=("C01",),
        object_entities=("Car", "Person"),
        object_match_mode="all",
        minimum_object_confidence=0.5,
        author="Alice",
        publish_date_from="2024-01-01",
        publish_date_to="2024-01-31",
    )
    outcome = store.search_by_text("query", top_k=100, filters=filters)
    assert [result.keyframe_id for result in outcome.results] == ["V01_002"]


def test_filter_options_and_keyframe_details(tmp_path):
    store = _make_store(tmp_path)
    assert store.filter_options() == {
        "collections": ["C01", "C02"],
        "videos": ["V01", "V02"],
        "objects": ["Car", "Person"],
        "authors": ["Alice", "Bob"],
    }
    details = store.get_keyframe_details("V01_002")
    assert details.keyframe["fps"] == 30.0
    assert details.keyframe["frame_idx"] == 60
    assert details.video["title"] == "First video"
    assert [row["entity"] for row in details.detections] == ["Car", "Person"]


@pytest.mark.parametrize("top_k", [0, 101])
def test_top_k_is_limited_to_public_contract(tmp_path, top_k):
    store = _make_store(tmp_path)
    with pytest.raises(ValueError, match="top_k"):
        store.search_by_text("query", top_k=top_k)


def test_invalid_date_filter_is_rejected(tmp_path):
    store = _make_store(tmp_path)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        store.search_by_text(
            "query",
            filters=SearchFilters(publish_date_from="01/01/2024"),
        )
