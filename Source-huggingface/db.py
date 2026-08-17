"""Local DeepFashion artifact store and similarity search."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from threading import Event, Lock, RLock

import numpy as np
import pandas as pd
from clip import CLIPSearcher
from clusterer import ImageIndexer
from PIL import Image
from schemas import SearchResult

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class ScanCancelled(RuntimeError):
    """Raised when a reindex request is cancelled between inference batches."""


def _as_matrix(vectors) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    elif matrix.ndim > 2:
        matrix = matrix.reshape(matrix.shape[0], -1)
    if matrix.ndim != 2:
        raise ValueError("Embeddings must be a two-dimensional matrix")
    if matrix.shape[1] == 0:
        raise ValueError("Embeddings must have at least one dimension")
    if not np.isfinite(matrix).all():
        raise ValueError("Embeddings contain NaN or infinite values")
    return np.ascontiguousarray(matrix)


def _normalize(vectors) -> np.ndarray:
    matrix = _as_matrix(vectors).copy()
    norms = np.linalg.norm(matrix, axis=1)
    nonzero = norms > 0
    matrix[nonzero] /= norms[nonzero, None]
    return np.ascontiguousarray(matrix, dtype=np.float32)


def _read_dataframe(path: Path) -> pd.DataFrame:
    errors: list[str] = []
    for separator in ("\t", ","):
        try:
            dataframe = pd.read_csv(path, sep=separator)
        except Exception as exc:
            errors.append(str(exc))
            continue
        if "image_path" in dataframe.columns:
            return dataframe
    detail = "; ".join(errors) if errors else "image_path column not found"
    raise ValueError(f"Could not read {path}: {detail}")


class SearchMechanism:
    """Coordinate CLIP queries with local NumPy and FAISS indexes."""

    def __init__(
        self,
        clip_searcher: CLIPSearcher,
        image_indexer: ImageIndexer,
        default_images_path: str,
        captions_path: str | Path | None = None,
    ) -> None:
        self.clip_searcher = clip_searcher
        self.image_indexer = image_indexer
        self.index_path = Path(self.image_indexer.index_path)
        self.default_images_path = Path(default_images_path)
        self.captions_path = Path(captions_path) if captions_path else None
        self._data_lock = RLock()
        self._scan_lock = Lock()
        self.df = pd.DataFrame()
        self.df_image_embeds = np.empty((0, 0), dtype=np.float32)
        self._normalized_embeds = np.empty((0, 0), dtype=np.float32)
        self._fingerprint: str | None = None
        self._captions = self._load_captions()
        self.load_db()

    def _load_captions(self) -> dict[str, str]:
        if self.captions_path is None or not self.captions_path.exists():
            return {}
        with self.captions_path.open("r", encoding="utf-8") as handle:
            captions = json.load(handle)
        if not isinstance(captions, dict):
            raise ValueError("captions.json must contain an object keyed by filename")
        return {str(key): str(value) for key, value in captions.items()}

    def _resolve_image_path(self, raw_path: object) -> str:
        value = str(raw_path)
        original = Path(value)
        if original.exists():
            return str(original)
        filename = PureWindowsPath(value).name if "\\" in value else original.name
        return str(self.default_images_path / filename)

    def _load_candidates(self) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, str]:
        dataframe_path = self.index_path / "df.csv"
        embeddings_path = self.index_path / "df_image_embeds.npy"
        if not dataframe_path.exists() or not embeddings_path.exists():
            raise FileNotFoundError(
                f"Missing local index artifacts: {dataframe_path} and {embeddings_path}"
            )

        dataframe = _read_dataframe(dataframe_path).copy()
        dataframe["image_path"] = dataframe["image_path"].map(self._resolve_image_path)
        embeddings = _as_matrix(np.load(embeddings_path, allow_pickle=False))
        if len(dataframe) != embeddings.shape[0]:
            raise ValueError(
                "df.csv row count does not match df_image_embeds.npy: "
                f"{len(dataframe)} != {embeddings.shape[0]}"
            )
        if embeddings.shape[0] == 0:
            raise ValueError("The local index contains no image embeddings")
        fingerprint = ImageIndexer.artifact_fingerprint(embeddings_path)
        return dataframe, embeddings, _normalize(embeddings), fingerprint

    def load_db(self) -> None:
        self.index_path.mkdir(parents=True, exist_ok=True)
        dataframe, embeddings, normalized, fingerprint = self._load_candidates()
        with self._data_lock:
            self.df = dataframe
            self.df_image_embeds = embeddings
            self._normalized_embeds = normalized
            self._fingerprint = fingerprint

    def _snapshot(self) -> tuple[pd.DataFrame, np.ndarray, str | None]:
        with self._data_lock:
            return self.df, self._normalized_embeds, self._fingerprint

    def _result(self, row: pd.Series, score: float) -> SearchResult:
        image_path = str(row["image_path"])
        filename = Path(image_path).name
        return SearchResult(
            image_path=image_path,
            score=float(score),
            caption=self._captions.get(filename),
            filename=filename,
        )

    def query_by_embeds(
        self,
        embeds: np.ndarray,
        top_k: int = 5,
        use_cluster_search: bool = False,
        faiss_nprobe: int | None = None,
    ) -> list[SearchResult]:
        dataframe, image_embeds, fingerprint = self._snapshot()
        if dataframe.empty or image_embeds.size == 0:
            return []
        query = _normalize(embeds)
        if query.shape != (1, image_embeds.shape[1]):
            raise ValueError("Query embedding shape does not match the local index")
        if not np.any(query):
            raise ValueError("Query embedding has zero magnitude")
        top_k = max(1, min(int(top_k), len(dataframe)))

        if use_cluster_search:
            scores, ids, _ = self.image_indexer.predict(
                image_embeds,
                query,
                top_k,
                fingerprint=fingerprint,
                nprobe=faiss_nprobe,
            )
            return [
                self._result(dataframe.iloc[int(idx)], score)
                for score, idx in zip(scores, ids, strict=True)
            ]

        scores = image_embeds @ query[0]
        candidate_ids = np.argpartition(scores, -top_k)[-top_k:]
        ordered_ids = candidate_ids[np.argsort(scores[candidate_ids])[::-1]]
        return [self._result(dataframe.iloc[int(idx)], scores[idx]) for idx in ordered_ids]

    def query_by_text(
        self,
        text: str,
        top_k: int = 5,
        use_cluster_search: bool = False,
        faiss_nprobe: int | None = None,
    ) -> list[SearchResult]:
        if not text or not text.strip():
            raise ValueError("Query text cannot be empty")
        return self.query_by_embeds(
            self.clip_searcher.get_text_features(text),
            top_k,
            use_cluster_search,
            faiss_nprobe,
        )

    def query_by_image(
        self,
        image,
        top_k: int = 5,
        use_cluster_search: bool = False,
        faiss_nprobe: int | None = None,
    ) -> list[SearchResult]:
        if image is None:
            raise ValueError("Query image cannot be empty")
        if isinstance(image, (str, Path)):
            with Image.open(image) as opened:
                image = opened.convert("RGB").copy()
        elif isinstance(image, Image.Image):
            image = image.convert("RGB")
        return self.query_by_embeds(
            self.clip_searcher.get_image_features(image),
            top_k,
            use_cluster_search,
            faiss_nprobe,
        )

    def _commit_reindex(self, staging_path: Path) -> None:
        filenames = [
            "df.csv",
            "df_image_embeds.npy",
            ImageIndexer.INDEX_FILENAME,
            ImageIndexer.METADATA_FILENAME,
        ]
        backup_path = Path(tempfile.mkdtemp(prefix=".index-backup-", dir=self.index_path))
        installed: list[Path] = []
        backed_up: list[tuple[Path, Path]] = []
        try:
            for filename in filenames:
                target = self.index_path / filename
                staged = staging_path / filename
                if target.exists():
                    backup = backup_path / filename
                    os.replace(target, backup)
                    backed_up.append((target, backup))
                os.replace(staged, target)
                installed.append(target)
            self.image_indexer.reset()
            self.load_db()
        except Exception:
            for target in installed:
                target.unlink(missing_ok=True)
            for target, backup in backed_up:
                if backup.exists():
                    os.replace(backup, target)
            self.image_indexer.reset()
            raise
        finally:
            shutil.rmtree(backup_path, ignore_errors=True)

    def scan_directory(
        self,
        path: Path,
        *,
        batch_size: int = 16,
        cancel_event: Event | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> int:
        requested_path = path.resolve()
        allowed_path = self.default_images_path.resolve()
        if requested_path != allowed_path:
            raise ValueError(f"Reindex is restricted to {allowed_path}")
        if not requested_path.is_dir():
            raise FileNotFoundError(f"Image directory does not exist: {requested_path}")
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if not self._scan_lock.acquire(blocking=False):
            raise RuntimeError("A reindex operation is already running")

        staging_path = Path(tempfile.mkdtemp(prefix=".reindex-", dir=self.index_path))
        try:
            image_files = sorted(
                path for path in requested_path.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS
            )
            if not image_files:
                raise ValueError(f"No supported images found in {requested_path}")

            indexed_paths: list[str] = []
            embedding_batches: list[np.ndarray] = []
            total = len(image_files)
            for start in range(0, total, batch_size):
                if cancel_event is not None and cancel_event.is_set():
                    raise ScanCancelled("Reindex cancelled")
                batch_paths = image_files[start : start + batch_size]
                images: list[Image.Image] = []
                valid_paths: list[Path] = []
                for image_path in batch_paths:
                    try:
                        with Image.open(image_path) as opened:
                            images.append(opened.convert("RGB").copy())
                        valid_paths.append(image_path)
                    except Exception as exc:
                        logger.warning("Skipping unreadable image %s: %s", image_path, exc)
                if images:
                    embeddings = self.clip_searcher.get_image_batch_features(images)
                    if embeddings.shape[0] != len(valid_paths):
                        raise ValueError("CLIP batch output count does not match input image count")
                    embedding_batches.append(_as_matrix(embeddings))
                    indexed_paths.extend(str(item) for item in valid_paths)
                if progress is not None:
                    progress(min(start + len(batch_paths), total), total)

            if cancel_event is not None and cancel_event.is_set():
                raise ScanCancelled("Reindex cancelled")
            if not embedding_batches:
                raise ValueError("No readable images could be indexed")

            embeddings = np.vstack(embedding_batches).astype(np.float32, copy=False)
            dataframe = pd.DataFrame({"image_path": indexed_paths})
            dataframe.to_csv(staging_path / "df.csv", sep="\t", index=False)
            embeddings_path = staging_path / "df_image_embeds.npy"
            np.save(embeddings_path, embeddings)
            staged_indexer = ImageIndexer(staging_path)
            staged_indexer.fit(
                embeddings,
                fingerprint=ImageIndexer.artifact_fingerprint(embeddings_path),
            )

            if cancel_event is not None and cancel_event.is_set():
                raise ScanCancelled("Reindex cancelled")
            self._commit_reindex(staging_path)
            return len(indexed_paths)
        finally:
            shutil.rmtree(staging_path, ignore_errors=True)
            self._scan_lock.release()
