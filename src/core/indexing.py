"""Pipeline that scans local images, uploads them to MinIO, and indexes Qdrant."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image
from tqdm import tqdm

from config import Settings
from core.embedding import EmbeddingService
from core.schemas import IndexingStats

if TYPE_CHECKING:
    from db.object_store import ObjectStore
    from db.vector_store import VectorStore

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
INGEST_BATCH_SIZE = 32
STATE_LOOKUP_BATCH_SIZE = 512


@dataclass
class _PendingImage:
    path: Path
    object_key: str
    metadata: dict
    minio_exists: bool
    is_update: bool


class IndexingService:
    """End-to-end indexing of a local image directory."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: "VectorStore",
        object_store: "ObjectStore",
        settings: Settings,
    ):
        self.embedding = embedding_service
        self.vector_store = vector_store
        self.object_store = object_store
        self.settings = settings

    def index_directory(self, images_dir: Path | None = None) -> IndexingStats:
        """Scan ``images_dir`` and incrementally ingest only new or changed images."""
        images_dir = images_dir or self.settings.legacy_images_path
        if images_dir is None or not Path(images_dir).exists():
            raise FileNotFoundError(f"Images directory not found: {images_dir}")
        images_dir = Path(images_dir)

        captions: dict[str, str] = {}
        if self.settings.captions_path and self.settings.captions_path.exists():
            with open(self.settings.captions_path) as f:
                captions = json.load(f)

        image_files = [p for p in images_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS]

        stats = IndexingStats(scanned_count=len(image_files))
        minio_keys = self._load_minio_keys()
        pending: list[_PendingImage] = []
        with tqdm(total=len(image_files), desc="Encoding & uploading images") as progress:
            for chunk in self._chunks(image_files, STATE_LOOKUP_BATCH_SIZE):
                chunk_items: list[tuple[Path, str, dict]] = []
                for img_path in chunk:
                    try:
                        object_key = f"images/{img_path.name}"
                        chunk_items.append(
                            (img_path, object_key, self._metadata_for_file(img_path, object_key))
                        )
                    except Exception as exc:
                        logger.warning("Failed to inspect %s: %s", img_path, exc)
                        stats.failed_count += 1
                        progress.update(1)

                payloads = self.vector_store.get_payloads(
                    [object_key for _img_path, object_key, _metadata in chunk_items]
                )

                for img_path, object_key, metadata in chunk_items:
                    try:
                        payload = payloads.get(object_key)
                        minio_exists = object_key in minio_keys

                        if payload and payload.get("content_hash") == metadata["content_hash"]:
                            if minio_exists:
                                stats.skipped_count += 1
                                continue
                            self.object_store.upload_file(str(img_path), object_key)
                            minio_keys.add(object_key)
                            stats.uploaded_only_count += 1
                            continue

                        pending.append(
                            _PendingImage(
                                path=img_path,
                                object_key=object_key,
                                metadata=metadata,
                                minio_exists=minio_exists,
                                is_update=payload is not None,
                            )
                        )
                        if len(pending) >= INGEST_BATCH_SIZE:
                            self._flush_pending(pending, captions, stats, minio_keys)
                            pending = []
                    except Exception as exc:
                        logger.warning("Failed to process %s: %s", img_path, exc)
                        stats.failed_count += 1
                    finally:
                        progress.update(1)

        if pending:
            self._flush_pending(pending, captions, stats, minio_keys)

        logger.info(
            "Indexing finished for %s: scanned=%d indexed=%d updated=%d skipped=%d "
            "uploaded_only=%d failed=%d",
            images_dir,
            stats.scanned_count,
            stats.indexed_count,
            stats.updated_count,
            stats.skipped_count,
            stats.uploaded_only_count,
            stats.failed_count,
        )
        return stats

    def _metadata_for_file(self, img_path: Path, object_key: str) -> dict:
        stat = img_path.stat()
        return {
            "content_hash": self._sha256_file(img_path),
            "file_size": stat.st_size,
            "modified_at": stat.st_mtime,
            "source_path": str(img_path),
            "image_path": object_key,
            "filename": img_path.name,
        }

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _load_minio_keys(self) -> set[str]:
        try:
            return set(self.object_store.list_objects(prefix="images/"))
        except Exception as exc:
            logger.warning(
                "Failed to list MinIO objects, falling back to per-object checks: %s", exc
            )
            return set()

    @staticmethod
    def _chunks(items: Sequence[Path], size: int) -> list[Sequence[Path]]:
        return [items[i : i + size] for i in range(0, len(items), size)]

    def _flush_pending(
        self,
        pending: Sequence[_PendingImage],
        captions: dict[str, str],
        stats: IndexingStats,
        minio_keys: set[str],
    ) -> None:
        images = []
        valid: list[_PendingImage] = []
        for item in pending:
            try:
                with Image.open(item.path) as img:
                    images.append(img.convert("RGB").copy())
                valid.append(item)
            except Exception as exc:
                logger.warning("Failed to read %s: %s", item.path, exc)
                stats.failed_count += 1

        if not valid:
            return

        embeddings = self.embedding.get_image_batch_features(images)
        object_keys: list[str] = []
        vectors: list[np.ndarray] = []
        metadata_by_key: dict[str, dict] = {}
        successful_items: list[_PendingImage] = []

        for item, emb in zip(valid, embeddings, strict=False):
            try:
                if item.is_update or not item.minio_exists:
                    self.object_store.upload_file(str(item.path), item.object_key)
                    minio_keys.add(item.object_key)
                object_keys.append(item.object_key)
                vectors.append(np.asarray(emb).flatten())
                metadata_by_key[item.object_key] = item.metadata
                successful_items.append(item)
            except Exception as exc:
                logger.warning("Failed to upload %s: %s", item.path, exc)
                stats.failed_count += 1

        if not object_keys:
            return

        try:
            self.vector_store.upsert_batch(
                object_keys,
                np.array(vectors),
                captions=captions,
                metadata_by_key=metadata_by_key,
            )
        except Exception:
            stats.failed_count += len(object_keys)
            logger.exception("Failed to upsert %d vectors into Qdrant", len(object_keys))
            return

        for item in successful_items:
            if item.is_update:
                stats.updated_count += 1
            else:
                stats.indexed_count += 1
