"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.schemas import SearchMode


class TextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=100)
    search_mode: SearchMode = SearchMode.ANN
    hnsw_ef: int | None = Field(None, ge=32, le=512)


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


class IndexStartResponse(BaseModel):
    job_id: str
    status: str
    status_url: str
    message: str


class IndexJobResponse(BaseModel):
    job_id: str
    status: str
    images_dir: str | None = None
    indexed_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    uploaded_only_count: int = 0
    failed_count: int = 0
    scanned_count: int = 0
    collection_info: dict | None = None
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    qdrant: dict | None = None
    minio_bucket: str | None = None
