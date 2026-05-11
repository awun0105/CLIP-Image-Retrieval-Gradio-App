"""Indexing endpoint — trigger end-to-end ingestion of a local directory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_indexing_service, get_vector_store
from api.schemas import IndexRequest, IndexResponse
from core.indexing import IndexingService
from db.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/index", tags=["index"])


@router.post("/", response_model=IndexResponse)
def index_directory(
    request: IndexRequest,
    indexing_service: Annotated[IndexingService, Depends(get_indexing_service)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
) -> IndexResponse:
    images_dir = Path(request.images_dir) if request.images_dir else None
    try:
        stats = indexing_service.index_directory(images_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IndexResponse(
        indexed_count=stats.indexed_count,
        updated_count=stats.updated_count,
        skipped_count=stats.skipped_count,
        uploaded_only_count=stats.uploaded_only_count,
        failed_count=stats.failed_count,
        scanned_count=stats.scanned_count,
        collection_info=vector_store.get_collection_info(),
    )
