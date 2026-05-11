"""Apply configured Qdrant HNSW/optimizer thresholds to an existing collection."""

from __future__ import annotations

import logging

from config import Settings
from db.vector_store import VectorStore


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    settings = Settings()
    vector_store = VectorStore(settings)
    before = vector_store.get_collection_info()
    vector_store.update_indexing_config()
    after = vector_store.get_collection_info()

    print(
        "Updated Qdrant index config for "
        f"{settings.qdrant_collection}: "
        f"indexing_threshold={settings.qdrant_indexing_threshold}, "
        f"full_scan_threshold={settings.qdrant_full_scan_threshold}"
    )
    print(f"Before: {before}")
    print(f"After: {after}")


if __name__ == "__main__":
    main()
