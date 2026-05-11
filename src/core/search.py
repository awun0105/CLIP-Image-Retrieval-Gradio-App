"""Text- and image-based similarity search built on top of CLIP + Qdrant."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PIL import Image

from core.embedding import EmbeddingService
from core.schemas import SearchMode, SearchResult

if TYPE_CHECKING:
    from db.vector_store import VectorStore

logger = logging.getLogger(__name__)


class SearchService:
    """Coordinate embedding generation and vector store retrieval."""

    def __init__(self, embedding_service: EmbeddingService, vector_store: "VectorStore"):
        self.embedding = embedding_service
        self.vector_store = vector_store

    def search_by_text(
        self,
        query: str,
        top_k: int = 5,
        search_mode: SearchMode | str | None = None,
        hnsw_ef: int | None = None,
    ) -> list[SearchResult]:
        if not query or not query.strip():
            raise ValueError("Query text cannot be empty")
        embedding = self.embedding.get_text_features(query)
        results = self.vector_store.search(embedding, top_k, search_mode, hnsw_ef)
        return [SearchResult(**r) for r in results]

    def search_by_image(
        self,
        image: Image.Image,
        top_k: int = 5,
        search_mode: SearchMode | str | None = None,
        hnsw_ef: int | None = None,
    ) -> list[SearchResult]:
        embedding = self.embedding.get_image_features(image)
        results = self.vector_store.search(embedding, top_k, search_mode, hnsw_ef)
        return [SearchResult(**r) for r in results]
