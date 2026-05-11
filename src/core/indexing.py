"""Pipeline that scans local images, uploads them to MinIO, and indexes Qdrant."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

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
STATE_LOOKUP_BATCH_SIZE = 512


@dataclass
class _PendingImage:
    path: Path
    object_key: str
    metadata: dict
    is_update: bool


@dataclass
class IndexingJob:
    job_id: str
    status: str
    images_dir: str | None = None
    stats: IndexingStats = field(default_factory=IndexingStats)
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class IndexingJobAlreadyRunning(RuntimeError):
    """Raised when a second indexing job is submitted while one is active."""


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
        self._job_lock = Lock()
        self._jobs: dict[str, IndexingJob] = {}
        self._job_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="indexing-job")

    def start_indexing_job(self, images_dir: Path | None = None) -> IndexingJob:
        """Submit an indexing job to the in-process single-worker queue."""
        images_dir = self._resolve_images_dir(images_dir)
        with self._job_lock:
            if self._active_job_id() is not None:
                raise IndexingJobAlreadyRunning("An indexing job is already queued or running")
            job_id = str(uuid4())
            job = IndexingJob(
                job_id=job_id,
                status="queued",
                images_dir=str(images_dir),
                created_at=self._now(),
            )
            self._jobs[job_id] = job
            self._job_executor.submit(self._run_indexing_job, job_id, images_dir)
            return self._snapshot_job(job)

    def get_indexing_job(self, job_id: str) -> IndexingJob | None:
        with self._job_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return self._snapshot_job(job)

    def _run_indexing_job(self, job_id: str, images_dir: Path) -> None:
        self._update_job(job_id, status="running", started_at=self._now())
        try:
            stats = self.index_directory(
                images_dir,
                on_progress=lambda current: self._update_job(job_id, stats=current),
            )
        except Exception as exc:
            logger.exception("Indexing job %s failed", job_id)
            self._update_job(job_id, status="failed", error=str(exc), finished_at=self._now())
            return
        self._update_job(job_id, status="completed", stats=stats, finished_at=self._now())

    def _update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stats: IndexingStats | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        with self._job_lock:
            job = self._jobs[job_id]
            if status is not None:
                job.status = status
            if stats is not None:
                job.stats = replace(stats)
            if error is not None:
                job.error = error
            if started_at is not None:
                job.started_at = started_at
            if finished_at is not None:
                job.finished_at = finished_at

    def _active_job_id(self) -> str | None:
        for job_id, job in self._jobs.items():
            if job.status in {"queued", "running"}:
                return job_id
        return None

    @staticmethod
    def _snapshot_job(job: IndexingJob) -> IndexingJob:
        return replace(job, stats=replace(job.stats))

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _resolve_images_dir(self, images_dir: Path | None = None) -> Path:
        images_dir = images_dir or self.settings.legacy_images_path
        if images_dir is None or not Path(images_dir).exists():
            raise FileNotFoundError(f"Images directory not found: {images_dir}")
        return Path(images_dir)

    def index_directory(
        self,
        images_dir: Path | None = None,
        on_progress: Callable[[IndexingStats], None] | None = None,
    ) -> IndexingStats:
        """Scan ``images_dir`` and incrementally ingest only new or changed images."""
        images_dir = self._resolve_images_dir(images_dir)

        captions: dict[str, str] = {}
        if self.settings.captions_path and self.settings.captions_path.exists():
            with open(self.settings.captions_path) as f:
                captions = json.load(f)

        stats = IndexingStats()
        pending: list[_PendingImage] = []
        with tqdm(desc="Encoding & uploading images", unit="image") as progress:
            for chunk in self._chunks(self._iter_image_files(images_dir), STATE_LOOKUP_BATCH_SIZE):
                chunk_items: list[tuple[Path, str, dict]] = []
                for img_path in chunk:
                    stats.scanned_count += 1
                    try:
                        object_key = f"images/{img_path.name}"
                        chunk_items.append(
                            (
                                img_path,
                                object_key,
                                self._metadata_for_file(
                                    img_path,
                                    object_key,
                                    include_hash=False,
                                ),
                            )
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

                        if (
                            self.settings.index_fast_metadata_skip
                            and payload
                            and self._fast_metadata_matches(payload, metadata)
                        ):
                            if not self._needs_object_repair(object_key):
                                stats.skipped_count += 1
                                continue
                            self.object_store.upload_file(str(img_path), object_key)
                            stats.uploaded_only_count += 1
                            continue

                        metadata = {
                            **metadata,
                            "content_hash": self._sha256_file(img_path),
                        }
                        if payload and payload.get("content_hash") == metadata["content_hash"]:
                            if not self._needs_object_repair(object_key):
                                stats.skipped_count += 1
                                continue
                            self.object_store.upload_file(str(img_path), object_key)
                            stats.uploaded_only_count += 1
                            continue

                        pending.append(
                            _PendingImage(
                                path=img_path,
                                object_key=object_key,
                                metadata=metadata,
                                is_update=payload is not None,
                            )
                        )
                        if len(pending) >= self.settings.ingest_batch_size:
                            self._flush_pending(pending, captions, stats)
                            pending = []
                            self._notify_progress(on_progress, stats)
                    except Exception as exc:
                        logger.warning("Failed to process %s: %s", img_path, exc)
                        stats.failed_count += 1
                    finally:
                        progress.update(1)
                self._notify_progress(on_progress, stats)

        if pending:
            self._flush_pending(pending, captions, stats)
            self._notify_progress(on_progress, stats)

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

    @staticmethod
    def _notify_progress(
        on_progress: Callable[[IndexingStats], None] | None,
        stats: IndexingStats,
    ) -> None:
        if on_progress is not None:
            on_progress(replace(stats))

    def _metadata_for_file(
        self,
        img_path: Path,
        object_key: str,
        *,
        include_hash: bool = True,
    ) -> dict:
        stat = img_path.stat()
        metadata = {
            "file_size": stat.st_size,
            "modified_at": stat.st_mtime,
            "source_path": str(img_path),
            "image_path": object_key,
            "filename": img_path.name,
        }
        if include_hash:
            metadata["content_hash"] = self._sha256_file(img_path)
        return metadata

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _fast_metadata_matches(payload: dict, metadata: dict) -> bool:
        return (
            payload.get("file_size") == metadata["file_size"]
            and payload.get("modified_at") == metadata["modified_at"]
        )

    def _needs_object_repair(self, object_key: str) -> bool:
        return self.settings.index_repair_missing_objects and not self.object_store.object_exists(
            object_key
        )

    @staticmethod
    def _iter_image_files(images_dir: Path) -> Iterator[Path]:
        for path in images_dir.iterdir():
            if path.suffix.lower() in _IMAGE_EXTS:
                yield path

    @staticmethod
    def _chunks(items: Iterable[Path], size: int) -> Iterator[list[Path]]:
        chunk: list[Path] = []
        for item in items:
            chunk.append(item)
            if len(chunk) >= size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    def _flush_pending(
        self,
        pending: Sequence[_PendingImage],
        captions: dict[str, str],
        stats: IndexingStats,
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
        successful: list[tuple[int, _PendingImage, np.ndarray]] = []
        workers = max(1, min(self.settings.minio_upload_workers, len(valid)))

        def _upload(index: int, item: _PendingImage, emb: np.ndarray) -> tuple[int, _PendingImage, np.ndarray]:
            self.object_store.upload_file(str(item.path), item.object_key)
            return index, item, emb

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_upload, index, item, emb)
                for index, (item, emb) in enumerate(zip(valid, embeddings, strict=False))
            ]
            for future in as_completed(futures):
                try:
                    successful.append(future.result())
                except Exception as exc:
                    logger.warning("Failed to upload indexed image: %s", exc)
                    stats.failed_count += 1

        successful.sort(key=lambda result: result[0])
        object_keys = [item.object_key for _index, item, _emb in successful]
        vectors = [np.asarray(emb).flatten() for _index, _item, emb in successful]
        metadata_by_key = {item.object_key: item.metadata for _index, item, _emb in successful}
        successful_items = [item for _index, item, _emb in successful]

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
