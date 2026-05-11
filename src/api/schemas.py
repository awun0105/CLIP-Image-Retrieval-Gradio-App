"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=100)


class SearchResultItem(BaseModel):
    image_path: str
    image_url: str | None = None
    score: float
    caption: str | None = None
    filename: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    query: str | None = None


class IndexRequest(BaseModel):
    images_dir: str | None = None


class IndexResponse(BaseModel):
    indexed_count: int
    updated_count: int = 0
    skipped_count: int = 0
    uploaded_only_count: int = 0
    failed_count: int = 0
    scanned_count: int = 0
    collection_info: dict


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    qdrant: dict | None = None
    minio_bucket: str | None = None
