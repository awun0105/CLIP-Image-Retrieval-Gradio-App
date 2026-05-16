"""Indexing job backends for memory and Redis/RQ execution."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from redis import Redis
from rq import Queue

from config import Settings
from core.indexing import IndexingJob, IndexingJobAlreadyRunning, IndexingService
from core.metrics import INDEXING_JOBS
from core.schemas import IndexingStats

logger = logging.getLogger(__name__)

_JOB_KEY_PREFIX = "indexing-job:"
_ACTIVE_JOB_KEY = "indexing-active-job"


class IndexingJobBackend:
    """Facade used by API routes to start and inspect indexing jobs."""

    def __init__(self, indexing_service: IndexingService, settings: Settings):
        self.indexing_service = indexing_service
        self.settings = settings
        self._redis: Redis | None = None
        self._queue: Queue | None = None

    def start_indexing_job(self, images_dir: Path | None = None) -> IndexingJob:
        if self.settings.indexing_job_backend == "memory":
            return self.indexing_service.start_indexing_job(images_dir)
        if self.settings.indexing_job_backend == "redis":
            return self._start_redis_job(images_dir)
        raise ValueError(f"Unsupported INDEXING_JOB_BACKEND={self.settings.indexing_job_backend}")

    def get_indexing_job(self, job_id: str) -> IndexingJob | None:
        if self.settings.indexing_job_backend == "memory":
            return self.indexing_service.get_indexing_job(job_id)
        if self.settings.indexing_job_backend == "redis":
            return self._get_redis_job(job_id)
        raise ValueError(f"Unsupported INDEXING_JOB_BACKEND={self.settings.indexing_job_backend}")

    @property
    def redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self.settings.redis_url)
        return self._redis

    @property
    def queue(self) -> Queue:
        if self._queue is None:
            self._queue = Queue(self.settings.indexing_queue_name, connection=self.redis)
        return self._queue

    def _start_redis_job(self, images_dir: Path | None = None) -> IndexingJob:
        images_dir = self.indexing_service._resolve_images_dir(images_dir)
        active_job_id = self.redis.get(_ACTIVE_JOB_KEY)
        if active_job_id:
            active_job = self._get_redis_job(_redis_text(active_job_id))
            if active_job is not None and active_job.status in {"queued", "running"}:
                raise IndexingJobAlreadyRunning("An indexing job is already queued or running")
            self.redis.delete(_ACTIVE_JOB_KEY)

        job_id = str(uuid4())
        job = IndexingJob(
            job_id=job_id,
            status="queued",
            images_dir=str(images_dir),
            created_at=IndexingService._now(),
        )
        _write_job(self.redis, job)
        self.redis.set(_ACTIVE_JOB_KEY, job_id)
        self.queue.enqueue(
            run_indexing_job,
            job_id,
            str(images_dir),
            job_id=job_id,
            job_timeout=self.settings.indexing_job_timeout_seconds,
            result_ttl=self.settings.indexing_job_result_ttl_seconds,
            failure_ttl=self.settings.indexing_job_failure_ttl_seconds,
        )
        return _snapshot_job(job)

    def _get_redis_job(self, job_id: str) -> IndexingJob | None:
        data = self.redis.get(_job_key(job_id))
        if data is None:
            return None
        return _job_from_dict(json.loads(data))


def run_indexing_job(job_id: str, images_dir: str) -> None:
    """RQ entrypoint that executes one indexing job in a worker process."""
    from api.dependencies import get_indexing_service, get_settings

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    indexing_service = get_indexing_service()

    _update_job(redis, job_id, status="running", started_at=IndexingService._now())
    try:
        stats = indexing_service.index_directory(
            Path(images_dir),
            on_progress=lambda current: _update_job(redis, job_id, stats=current),
        )
    except Exception as exc:
        logger.exception("Indexing job %s failed", job_id)
        INDEXING_JOBS.labels("failed").inc()
        _update_job(
            redis,
            job_id,
            status="failed",
            error=str(exc),
            finished_at=IndexingService._now(),
        )
        redis.delete(_ACTIVE_JOB_KEY)
        raise

    INDEXING_JOBS.labels("completed").inc()
    _update_job(
        redis,
        job_id,
        status="completed",
        stats=stats,
        finished_at=IndexingService._now(),
    )
    redis.delete(_ACTIVE_JOB_KEY)


def _job_key(job_id: str) -> str:
    return f"{_JOB_KEY_PREFIX}{job_id}"


def _snapshot_job(job: IndexingJob) -> IndexingJob:
    return replace(job, stats=replace(job.stats))


def _job_from_dict(data: dict[str, Any]) -> IndexingJob:
    stats_data = data.get("stats") or {}
    return IndexingJob(
        job_id=data["job_id"],
        status=data["status"],
        images_dir=data.get("images_dir"),
        stats=IndexingStats(**stats_data),
        error=data.get("error"),
        created_at=data.get("created_at"),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
    )


def _redis_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _write_job(redis: Redis, job: IndexingJob) -> None:
    payload = asdict(job)
    redis.set(_job_key(job.job_id), json.dumps(payload))


def _update_job(
    redis: Redis,
    job_id: str,
    *,
    status: str | None = None,
    stats: IndexingStats | None = None,
    error: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> None:
    data = redis.get(_job_key(job_id))
    if data is None:
        raise KeyError(f"Indexing job not found: {job_id}")
    job = _job_from_dict(json.loads(data))
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
    _write_job(redis, job)
