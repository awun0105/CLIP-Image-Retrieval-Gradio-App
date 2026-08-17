"""Embedding retrieval with strict SQLite metadata filtering."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from clip import CLIPSearcher
from clusterer import ImageIndexer
from schemas import KeyframeDetails, SearchFilters, SearchOutcome, SearchResult
from translation import QueryTranslator


def _normalize_query_vector(vector: np.ndarray, expected_dimension: int) -> np.ndarray:
    query = np.asarray(vector, dtype=np.float32).reshape(1, -1)
    if query.shape[1] != expected_dimension:
        raise ValueError(
            f"Query dimension {query.shape[1]} does not match embeddings {expected_dimension}"
        )
    norm = float(np.linalg.norm(query[0]))
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("Query embedding must have finite non-zero magnitude")
    return np.ascontiguousarray(query / norm, dtype=np.float32)


def _validate_iso_date(value: str | None, field: str) -> str | None:
    normalized = str(value).strip() if value else None
    if normalized:
        try:
            date.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{field} must use YYYY-MM-DD format") from exc
    return normalized


class SearchMechanism:
    """Coordinate translation, CLIP, metadata filters, FAISS, and exact cosine."""

    def __init__(
        self,
        clip_searcher: CLIPSearcher,
        translator: QueryTranslator,
        image_indexer: ImageIndexer,
        sqlite_file: str | Path,
        embeddings_file: str | Path,
        data_root: str | Path,
    ) -> None:
        self.clip_searcher = clip_searcher
        self.translator = translator
        self.image_indexer = image_indexer
        self.sqlite_file = Path(sqlite_file)
        self.data_root = Path(data_root)
        if not self.sqlite_file.is_file():
            raise FileNotFoundError(f"Runtime metadata database not found: {self.sqlite_file}")
        self.embeddings = np.load(Path(embeddings_file), mmap_mode="r", allow_pickle=False)
        if self.embeddings.ndim != 2:
            raise ValueError("Runtime embeddings must be a two-dimensional matrix")
        if self.embeddings.shape != (self.image_indexer.count, self.image_indexer.dimension):
            raise ValueError(
                "Embedding matrix and FAISS index disagree: "
                f"{self.embeddings.shape} != "
                f"({self.image_indexer.count}, {self.image_indexer.dimension})"
            )
        self._validate_database_count()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.sqlite_file}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _validate_database_count(self) -> None:
        with self._connect() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM keyframes").fetchone()[0])
        if count != self.embeddings.shape[0]:
            raise ValueError(
                f"SQLite keyframe count {count} does not match embeddings {self.embeddings.shape[0]}"
            )

    def filter_options(self) -> dict[str, list[str]]:
        with self._connect() as connection:
            collections = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT collection_id FROM keyframes ORDER BY collection_id"
                )
            ]
            videos = [
                row[0]
                for row in connection.execute("SELECT video_id FROM videos ORDER BY video_id")
            ]
            objects = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT entity FROM detections ORDER BY entity"
                )
            ]
            authors = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT author FROM videos WHERE author <> '' ORDER BY author"
                )
            ]
        return {
            "collections": collections,
            "videos": videos,
            "objects": objects,
            "authors": authors,
        }

    def search_by_text(
        self,
        query: str,
        top_k: int = 20,
        query_language: str = "auto",
        filters: SearchFilters | None = None,
    ) -> SearchOutcome:
        top_k = int(top_k)
        if top_k < 1 or top_k > 100:
            raise ValueError("top_k must be in [1, 100]")
        prepared = self.translator.prepare(query, query_language)
        query_vector = _normalize_query_vector(
            self.clip_searcher.get_text_features(prepared.clip_query),
            self.embeddings.shape[1],
        )
        filters = filters or SearchFilters()
        if filters.active:
            eligible_ids = self._eligible_vector_ids(filters)
            scores, vector_ids = self._search_filtered(query_vector, eligible_ids, top_k)
        else:
            scores, vector_ids = self.image_indexer.search(query_vector, top_k)
        results = self._results_for_ids(vector_ids, scores)
        return SearchOutcome(tuple(results), prepared)

    def _eligible_vector_ids(self, filters: SearchFilters) -> np.ndarray:
        mode = filters.object_match_mode.strip().lower()
        if mode not in {"any", "all"}:
            raise ValueError("object_match_mode must be 'any' or 'all'")
        minimum_confidence = float(filters.minimum_object_confidence)
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_object_confidence must be in [0, 1]")
        date_from = _validate_iso_date(filters.publish_date_from, "publish_date_from")
        date_to = _validate_iso_date(filters.publish_date_to, "publish_date_to")
        if date_from and date_to and date_from > date_to:
            raise ValueError("publish_date_from cannot be after publish_date_to")

        conditions: list[str] = []
        parameters: list[Any] = []
        if filters.collections:
            placeholders = ",".join("?" for _ in filters.collections)
            conditions.append(f"k.collection_id IN ({placeholders})")
            parameters.extend(filters.collections)
        if filters.video_id:
            conditions.append("k.video_id = ?")
            parameters.append(filters.video_id)
        if filters.author:
            conditions.append("v.author = ?")
            parameters.append(filters.author)
        if date_from:
            conditions.append("v.publish_date_iso >= ?")
            parameters.append(date_from)
        if date_to:
            conditions.append("v.publish_date_iso <= ?")
            parameters.append(date_to)

        entities = tuple(dict.fromkeys(filters.object_entities))
        if entities:
            placeholders = ",".join("?" for _ in entities)
            if mode == "any":
                conditions.append(
                    "EXISTS (SELECT 1 FROM detections d "
                    "WHERE d.keyframe_id = k.keyframe_id "
                    f"AND d.entity IN ({placeholders}) AND d.score >= ?)"
                )
                parameters.extend(entities)
                parameters.append(minimum_confidence)
            else:
                conditions.append(
                    "(SELECT COUNT(DISTINCT d.entity) FROM detections d "
                    "WHERE d.keyframe_id = k.keyframe_id "
                    f"AND d.entity IN ({placeholders}) AND d.score >= ?) = ?"
                )
                parameters.extend(entities)
                parameters.extend([minimum_confidence, len(entities)])

        where = " AND ".join(conditions) if conditions else "1=1"
        query = (
            "SELECT k.vector_id FROM keyframes k "
            "JOIN videos v ON v.video_id = k.video_id "
            f"WHERE {where} ORDER BY k.vector_id"
        )
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return np.fromiter((int(row[0]) for row in rows), dtype=np.int64, count=len(rows))

    def _search_filtered(
        self,
        query: np.ndarray,
        eligible_ids: np.ndarray,
        top_k: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        if eligible_ids.size == 0:
            return np.empty(0, dtype=np.float32), np.empty(0, dtype=np.int64)
        vectors = np.asarray(self.embeddings[eligible_ids], dtype=np.float32)
        scores = vectors @ query[0]
        count = min(top_k, eligible_ids.size)
        if count == eligible_ids.size:
            local_ids = np.argsort(scores)[::-1]
        else:
            candidates = np.argpartition(scores, -count)[-count:]
            local_ids = candidates[np.argsort(scores[candidates])[::-1]]
        return scores[local_ids], eligible_ids[local_ids]

    def _results_for_ids(
        self,
        vector_ids: Iterable[int],
        scores: Iterable[float],
    ) -> list[SearchResult]:
        ordered_ids = [int(value) for value in vector_ids]
        ordered_scores = [float(value) for value in scores]
        if not ordered_ids:
            return []
        placeholders = ",".join("?" for _ in ordered_ids)
        query = f"""
            SELECT k.vector_id, k.keyframe_id, k.video_id, k.collection_id,
                   k.keyframe_no, k.image_relpath, k.pts_time_sec, k.frame_idx,
                   k.fps, k.width, k.height, v.title
            FROM keyframes k
            JOIN videos v ON v.video_id = k.video_id
            WHERE k.vector_id IN ({placeholders})
        """
        with self._connect() as connection:
            by_id = {
                int(row["vector_id"]): dict(row)
                for row in connection.execute(query, ordered_ids).fetchall()
            }
        results = []
        for vector_id, score in zip(ordered_ids, ordered_scores, strict=True):
            row = by_id[vector_id]
            image_relpath = str(row["image_relpath"])
            results.append(
                SearchResult(
                    vector_id=vector_id,
                    keyframe_id=str(row["keyframe_id"]),
                    video_id=str(row["video_id"]),
                    collection_id=str(row["collection_id"]),
                    keyframe_no=int(row["keyframe_no"]),
                    image_path=str(self.data_root / image_relpath),
                    image_relpath=image_relpath,
                    score=score,
                    pts_time_sec=float(row["pts_time_sec"]),
                    frame_idx=int(row["frame_idx"]),
                    fps=float(row["fps"]),
                    width=int(row["width"]),
                    height=int(row["height"]),
                    title=str(row["title"]),
                )
            )
        return results

    def get_keyframe_details(self, keyframe_id: str) -> KeyframeDetails:
        with self._connect() as connection:
            keyframe_row = connection.execute(
                "SELECT * FROM keyframes WHERE keyframe_id = ?",
                (keyframe_id,),
            ).fetchone()
            if keyframe_row is None:
                raise KeyError(f"Unknown keyframe: {keyframe_id}")
            video_row = connection.execute(
                "SELECT * FROM videos WHERE video_id = ?",
                (keyframe_row["video_id"],),
            ).fetchone()
            detection_rows = connection.execute(
                """
                SELECT rank, entity, class_mid, class_label, score,
                       ymin, xmin, ymax, xmax
                FROM detections WHERE keyframe_id = ?
                ORDER BY score DESC, rank ASC
                """,
                (keyframe_id,),
            ).fetchall()
        keyframe = dict(keyframe_row)
        keyframe["image_path"] = str(self.data_root / keyframe["image_relpath"])
        return KeyframeDetails(
            keyframe=keyframe,
            video=dict(video_row) if video_row is not None else {},
            detections=tuple(dict(row) for row in detection_rows),
        )
