"""Indexing endpoint — trigger end-to-end ingestion of a local directory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_indexing_service, get_vector_store
from api.schemas import IndexJobResponse, IndexRequest, IndexStartResponse
from api.security import require_api_key
from core.indexing import IndexingJob, IndexingJobAlreadyRunning, IndexingService
from db.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/index", tags=["index"], dependencies=[Depends(require_api_key)])


def _job_response(job: IndexingJob, vector_store: VectorStore) -> IndexJobResponse:
    stats = job.stats
    collection_info = None
    if job.status in {"completed", "failed"}:
        try:
            collection_info = vector_store.get_collection_info()
        except Exception as exc:
            logger.warning("Failed to read collection info for job %s: %s", job.job_id, exc)
    return IndexJobResponse(
        job_id=job.job_id,
        status=job.status,
        images_dir=job.images_dir,
        indexed_count=stats.indexed_count,
        updated_count=stats.updated_count,
        skipped_count=stats.skipped_count,
        uploaded_only_count=stats.uploaded_only_count,
        failed_count=stats.failed_count,
        scanned_count=stats.scanned_count,
        collection_info=collection_info,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/", response_model=IndexStartResponse, status_code=202)
def index_directory(
    request: IndexRequest,
    indexing_service: Annotated[IndexingService, Depends(get_indexing_service)],
) -> IndexStartResponse:
    images_dir = Path(request.images_dir) if request.images_dir else None
    try:
        job = indexing_service.start_indexing_job(images_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IndexingJobAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IndexStartResponse(
        job_id=job.job_id,
        status=job.status,
        status_url=f"/api/v1/index/{job.job_id}",
        message="Indexing job accepted",
    )


@router.get("/{job_id}", response_model=IndexJobResponse)
def get_indexing_job(
    job_id: str,
    indexing_service: Annotated[IndexingService, Depends(get_indexing_service)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
) -> IndexJobResponse:
    job = indexing_service.get_indexing_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Indexing job not found")
    return _job_response(job, vector_store)
