"""DI container — singletons for service instances cached via ``lru_cache``."""

from __future__ import annotations

from functools import lru_cache

from config import Settings
from core.embedding import EmbeddingService
from core.image_service import ImageService
from core.indexing import IndexingService
from core.indexing_jobs import IndexingJobBackend
from core.search import SearchService
from db.object_store import ObjectStore
from db.vector_store import VectorStore


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(get_settings())


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    return VectorStore(get_settings())


@lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    return ObjectStore(get_settings())


@lru_cache(maxsize=1)
def get_search_service() -> SearchService:
    return SearchService(get_embedding_service(), get_vector_store())


@lru_cache(maxsize=1)
def get_indexing_service() -> IndexingService:
    return IndexingService(
        get_embedding_service(),
        get_vector_store(),
        get_object_store(),
        get_settings(),
    )


@lru_cache(maxsize=1)
def get_indexing_job_backend() -> IndexingJobBackend:
    return IndexingJobBackend(get_indexing_service(), get_settings())


@lru_cache(maxsize=1)
def get_image_service() -> ImageService:
    return ImageService(get_object_store())
