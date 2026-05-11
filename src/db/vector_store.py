"""Qdrant-backed vector store wrapper."""

from __future__ import annotations

import logging
import uuid

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    PointStruct,
    SearchParams,
    VectorParams,
)

from config import Settings

logger = logging.getLogger(__name__)

VECTOR_DIM = 512  # CLIP ViT-B/16 latent dim
BATCH_SIZE = 100


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
            hnsw_config=HnswConfigDiff(m=32, ef_construct=200),
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
        """Upsert ``(key, embedding)`` pairs in batches of ``BATCH_SIZE``."""
        captions = captions or {}
        metadata_by_key = metadata_by_key or {}
        points: list[PointStruct] = []
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
            if len(points) >= BATCH_SIZE:
                self.client.upsert(collection_name=self.collection_name, points=points)
                points = []

        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> list[dict]:
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=np.asarray(query_vector).flatten().tolist(),
            limit=top_k,
            with_payload=True,
            search_params=SearchParams(hnsw_ef=128),
        )
        return [
            {
                "image_path": hit.payload["image_path"],
                "caption": hit.payload.get("caption"),
                "score": float(hit.score),
                "filename": hit.payload.get("filename"),
            }
            for hit in response.points
        ]

    def get_collection_info(self) -> dict:
        info = self.client.get_collection(self.collection_name)
        vectors_count = getattr(info, "vectors_count", None)
        if vectors_count is None:
            vectors_count = getattr(info, "indexed_vectors_count", 0) or 0
        points_count = getattr(info, "points_count", 0) or 0
        status = info.status
        return {
            "name": self.collection_name,
            "vectors_count": int(vectors_count),
            "points_count": int(points_count),
            "status": status.value if hasattr(status, "value") else str(status),
        }

    def delete_collection(self) -> None:
        self.client.delete_collection(self.collection_name)
