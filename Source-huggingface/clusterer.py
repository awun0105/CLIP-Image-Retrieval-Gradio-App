"""Versioned FAISS index for cosine-similarity search."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

import faiss
import numpy as np


def _as_matrix(vectors) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    elif matrix.ndim > 2:
        matrix = matrix.reshape(matrix.shape[0], -1)
    if matrix.ndim != 2:
        raise ValueError("Embeddings must be a two-dimensional matrix")
    if not np.isfinite(matrix).all():
        raise ValueError("Embeddings contain NaN or infinite values")
    return np.ascontiguousarray(matrix)


def _normalize(vectors) -> np.ndarray:
    matrix = _as_matrix(vectors).copy()
    norms = np.linalg.norm(matrix, axis=1)
    nonzero = norms > 0
    matrix[nonzero] /= norms[nonzero, None]
    return np.ascontiguousarray(matrix, dtype=np.float32)


class ImageIndexer:
    INDEX_VERSION = 2
    INDEX_FILENAME = "faiss_v2.index"
    METADATA_FILENAME = "faiss_v2.meta.json"

    def __init__(self, index_path: str | Path):
        self.index = None
        self.index_path = Path(index_path)
        self._lock = RLock()

    @property
    def index_file(self) -> Path:
        return self.index_path / self.INDEX_FILENAME

    @property
    def metadata_file(self) -> Path:
        return self.index_path / self.METADATA_FILENAME

    @staticmethod
    def artifact_fingerprint(embeddings_path: str | Path) -> str:
        stat = Path(embeddings_path).stat()
        return f"{stat.st_size}:{stat.st_mtime_ns}"

    def reset(self) -> None:
        with self._lock:
            self.index = None

    def _metadata(self) -> dict | None:
        try:
            with self.metadata_file.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else None
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _is_compatible(self, vectors: np.ndarray, fingerprint: str | None) -> bool:
        metadata = self._metadata()
        if not metadata or not self.index_file.exists():
            return False
        return (
            metadata.get("version") == self.INDEX_VERSION
            and metadata.get("vector_count") == vectors.shape[0]
            and metadata.get("dimension") == vectors.shape[1]
            and metadata.get("fingerprint") == fingerprint
        )

    def fit(
        self,
        image_embeds,
        *,
        fingerprint: str | None = None,
        num_clusters: int | None = None,
    ):
        vectors = _normalize(image_embeds)
        count, dimensions = vectors.shape
        if count == 0:
            raise ValueError("Cannot build a FAISS index without embeddings")

        self.index_path.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if count < 1_000:
                index = faiss.IndexFlatIP(dimensions)
                index_type = "flat_ip"
                nlist = 1
            else:
                suggested = max(1, count // 39)
                nlist = num_clusters or min(round(np.sqrt(count)), suggested)
                nlist = max(1, min(int(nlist), count))
                quantizer = faiss.IndexFlatIP(dimensions)
                index = faiss.IndexIVFFlat(
                    quantizer,
                    dimensions,
                    nlist,
                    faiss.METRIC_INNER_PRODUCT,
                )
                index.train(vectors)
                index.nprobe = min(8, nlist)
                index_type = "ivf_flat_ip"

            index.add(vectors)
            index_tmp = self.index_file.with_suffix(".index.tmp")
            metadata_tmp = self.metadata_file.with_suffix(".json.tmp")
            faiss.write_index(index, str(index_tmp))
            metadata = {
                "version": self.INDEX_VERSION,
                "vector_count": count,
                "dimension": dimensions,
                "fingerprint": fingerprint,
                "index_type": index_type,
                "nlist": nlist,
            }
            with metadata_tmp.open("w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2)
            os.replace(index_tmp, self.index_file)
            os.replace(metadata_tmp, self.metadata_file)
            self.index = index
            return index

    def _ensure_index(self, image_embeds, fingerprint: str | None):
        vectors = _as_matrix(image_embeds)
        with self._lock:
            if self.index is not None and self._is_compatible(vectors, fingerprint):
                return vectors
            if self._is_compatible(vectors, fingerprint):
                try:
                    self.index = faiss.read_index(str(self.index_file))
                    return vectors
                except (RuntimeError, OSError):
                    self.index = None
            self.fit(vectors, fingerprint=fingerprint)
            return vectors

    def predict(
        self,
        image_embeds,
        embed,
        k: int,
        *,
        fingerprint: str | None = None,
        nprobe: int | None = None,
    ):
        vectors = self._ensure_index(image_embeds, fingerprint)
        query = _normalize(embed)
        if query.shape[0] != 1 or query.shape[1] != vectors.shape[1]:
            raise ValueError("Query embedding shape does not match the image embeddings")
        k = max(1, min(int(k), vectors.shape[0]))
        with self._lock:
            assert self.index is not None
            if hasattr(self.index, "nprobe"):
                requested_nprobe = 8 if nprobe is None else int(nprobe)
                nlist = int(getattr(self.index, "nlist", requested_nprobe))
                self.index.nprobe = max(1, min(requested_nprobe, nlist))
            distances, ids = self.index.search(query, k)
        valid = (ids[0] >= 0) & (ids[0] < vectors.shape[0])
        valid_ids = ids[0][valid]
        return distances[0][valid], valid_ids, vectors[valid_ids]
