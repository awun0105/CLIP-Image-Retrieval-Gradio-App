"""Qdrant-backed vector store wrapper."""

from __future__ import annotations

import logging
import uuid

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    PointStruct,
    SearchParams,
    VectorParams,
)

from config import Settings
from core.schemas import SearchMode

logger = logging.getLogger(__name__)

VECTOR_DIM = 512  # CLIP ViT-B/16 latent dim


class VectorStore:
    """Thin wrapper around ``qdrant_client`` exposing collection + search primitives."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.collection_name = settings.qdrant_collection
        self.client = self._init_client()
        self._ensure_collection()

    def _init_client(self) -> QdrantClient:
        mode = self.settings.qdrant_mode
        if mode == "memory":
            return QdrantClient(":memory:")
        if mode == "local":
            return QdrantClient(path=self.settings.qdrant_path)
        if mode == "remote":
            return QdrantClient(url=self.settings.qdrant_url, api_key=self.settings.qdrant_api_key)
        raise ValueError(f"Unknown qdrant_mode: {mode!r}. Expected memory|local|remote.")

    def _ensure_collection(self) -> None:
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection_name in existing:
            return
        logger.info("Creating Qdrant collection %s", self.collection_name)
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            hnsw_config=HnswConfigDiff(
                m=32,
                ef_construct=200,
                full_scan_threshold=self.settings.qdrant_full_scan_threshold,
            ),
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=self.settings.qdrant_indexing_threshold,
            ),
        )

    @staticmethod
    def point_id_for_key(object_key: str) -> str:
        """Return the stable Qdrant point id for a MinIO object key."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, object_key))

    def get_payload(self, object_key: str) -> dict | None:
        """Return a point payload by object key, or ``None`` when missing."""
        return self.get_payloads([object_key]).get(object_key)

    def get_payloads(self, object_keys: list[str]) -> dict[str, dict]:
        """Return payloads for multiple object keys in one Qdrant request."""
        if not object_keys:
            return {}
        ids_by_key = {key: self.point_id_for_key(key) for key in object_keys}
        key_by_id = {point_id: key for key, point_id in ids_by_key.items()}
        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=list(ids_by_key.values()),
            with_payload=True,
            with_vectors=False,
        )
        payloads: dict[str, dict] = {}
        for record in records:
            key = key_by_id.get(str(record.id))
            if key:
                payloads[key] = dict(record.payload or {})
        return payloads

    def upsert_batch(
        self,
        object_keys: list[str],
        embeddings: np.ndarray,
        captions: dict[str, str] | None = None,
        metadata_by_key: dict[str, dict] | None = None,
    ) -> None:
        """Upsert ``(key, embedding)`` pairs in configured Qdrant write batches."""
        captions = captions or {}
        metadata_by_key = metadata_by_key or {}
        points: list[PointStruct] = []
        batch_size = max(1, self.settings.qdrant_upsert_batch_size)
        for key, emb in zip(object_keys, embeddings, strict=False):
            filename = key.split("/")[-1]
            caption = captions.get(filename)
            payload = {
                "image_path": key,
                "caption": caption,
                "filename": filename,
            }
            payload.update(metadata_by_key.get(key, {}))
            points.append(
                PointStruct(
                    id=self.point_id_for_key(key),
                    vector=np.asarray(emb).flatten().tolist(),
                    payload=payload,
                )
            )
            if len(points) >= batch_size:
                self.client.upsert(collection_name=self.collection_name, points=points)
                points = []

        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)

    def _search_params(
        self,
        search_mode: SearchMode | str | None = None,
        hnsw_ef: int | None = None,
    ) -> SearchParams:
        mode = SearchMode(search_mode or self.settings.search_mode_default)
        if mode == SearchMode.EXACT:
            return SearchParams(exact=True)

        ef = hnsw_ef or self.settings.qdrant_hnsw_ef
        return SearchParams(
            exact=False,
            hnsw_ef=ef,
            indexed_only=mode == SearchMode.ANN_INDEXED_ONLY,
        )

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        search_mode: SearchMode | str | None = None,
        hnsw_ef: int | None = None,
    ) -> list[dict]:
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=np.asarray(query_vector).flatten().tolist(),
            limit=top_k,
            with_payload=True,
            search_params=self._search_params(search_mode, hnsw_ef),
        )
        results: list[dict] = []
        for hit in response.points:
            payload = hit.payload or {}
            results.append(
                {
                    "image_path": payload["image_path"],
                    "caption": payload.get("caption"),
                    "score": float(hit.score),
                    "filename": payload.get("filename"),
                }
            )
        return results

    def get_collection_info(self) -> dict:
        info = self.client.get_collection(self.collection_name)
        indexed_vectors_count = getattr(info, "indexed_vectors_count", None)
        if indexed_vectors_count is None:
            indexed_vectors_count = getattr(info, "vectors_count", 0) or 0
        points_count = getattr(info, "points_count", 0) or 0
        status = info.status
        config = getattr(info, "config", None)
        params = getattr(config, "params", None)
        vectors = getattr(params, "vectors", None)
        return {
            "name": self.collection_name,
            "indexed_vectors_count": int(indexed_vectors_count),
            "points_count": int(points_count),
            "status": status.value if hasattr(status, "value") else str(status),
            "vector_size": self._vector_size(vectors),
            "distance": self._distance(vectors),
            "segments_count": getattr(info, "segments_count", None),
            "hnsw_config": self._model_dict(getattr(config, "hnsw_config", None)),
            "optimizer_config": self._model_dict(getattr(config, "optimizer_config", None)),
            "sample_has_vector": self._sample_has_vector(),
        }

    def delete_collection(self) -> None:
        self.client.delete_collection(self.collection_name)

    def update_indexing_config(self) -> None:
        """Apply configured HNSW/optimizer thresholds to an existing collection."""
        self.client.update_collection(
            collection_name=self.collection_name,
            hnsw_config=HnswConfigDiff(
                full_scan_threshold=self.settings.qdrant_full_scan_threshold,
            ),
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=self.settings.qdrant_indexing_threshold,
            ),
        )

    @staticmethod
    def _model_dict(value) -> dict | None:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        return None

    @staticmethod
    def _vector_size(vectors) -> int | None:
        if isinstance(vectors, dict):
            vectors = next(iter(vectors.values()), None)
        return getattr(vectors, "size", None)

    @staticmethod
    def _distance(vectors) -> str | None:
        if isinstance(vectors, dict):
            vectors = next(iter(vectors.values()), None)
        distance = getattr(vectors, "distance", None)
        if distance is None:
            return None
        return distance.value if hasattr(distance, "value") else str(distance)

    def _sample_has_vector(self) -> bool | None:
        try:
            records, _ = self.client.scroll(
                collection_name=self.collection_name,
                limit=1,
                with_payload=False,
                with_vectors=True,
            )
        except Exception as exc:
            logger.warning("Qdrant sample vector probe failed: %s", exc)
            return None
        if not records:
            return False
        vector = getattr(records[0], "vector", None)
        if isinstance(vector, dict):
            return any(value is not None for value in vector.values())
        return vector is not None
