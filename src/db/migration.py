"""Migration utilities — bring legacy v1 data (df.csv + .npy) into Qdrant + MinIO."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from config import Settings
from core.indexing import IndexingService
from db.object_store import ObjectStore
from db.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MigrationService:
    """Glue the legacy file-based artefacts into the new Qdrant + MinIO stores."""

    def __init__(
        self,
        settings: Settings,
        vector_store: VectorStore,
        object_store: ObjectStore,
        indexing_service: IndexingService | None = None,
    ):
        self.settings = settings
        self.vector_store = vector_store
        self.object_store = object_store
        self.indexing_service = indexing_service

    def _load_captions(self) -> dict[str, str]:
        if self.settings.captions_path and Path(self.settings.captions_path).exists():
            with open(self.settings.captions_path) as f:
                return json.load(f)
        return {}

    def upload_images(self) -> int:
        """Upload every image under ``legacy_images_path`` into MinIO."""
        images_dir = self.settings.legacy_images_path
        if not images_dir or not Path(images_dir).exists():
            raise FileNotFoundError(f"Images directory not found: {images_dir}")
        images_dir = Path(images_dir)
        uploaded = 0
        for img_path in images_dir.iterdir():
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            object_key = f"images/{img_path.name}"
            if self.object_store.object_exists(object_key):
                continue
            self.object_store.upload_file(str(img_path), object_key)
            uploaded += 1
        logger.info("Uploaded %d images to MinIO bucket %s", uploaded, self.object_store.bucket)
        return uploaded

    def migrate_embeddings_only(self) -> int:
        """Upsert pre-computed embeddings into Qdrant without re-encoding."""
        index_path = self.settings.legacy_index_path
        if not index_path:
            raise FileNotFoundError("legacy_index_path is not configured")
        index_path = Path(index_path)
        df_path = index_path / "df.csv"
        embeds_path = index_path / "df_image_embeds.npy"
        if not df_path.exists() or not embeds_path.exists():
            raise FileNotFoundError(
                f"Legacy artefacts not found at {index_path} (need df.csv + df_image_embeds.npy)"
            )

        df = pd.read_csv(df_path, sep="\t")
        embeds = np.load(embeds_path)
        if len(df) != len(embeds):
            raise ValueError(
                f"df.csv ({len(df)} rows) and df_image_embeds.npy ({len(embeds)}) length mismatch"
            )

        captions = self._load_captions()
        keys = [f"images/{Path(p).name}" for p in df["image_path"]]
        self.vector_store.upsert_batch(keys, embeds, captions)
        logger.info(
            "Upserted %d embeddings into Qdrant collection %s",
            len(keys),
            self.vector_store.collection_name,
        )
        return len(keys)

    def migrate_all(self) -> dict:
        """Upload images to MinIO then upsert pre-computed embeddings."""
        uploaded = self.upload_images()
        upserted = self.migrate_embeddings_only()
        return {"uploaded": uploaded, "upserted": upserted}
