"""Prometheus metrics used by API, search, embedding, and indexing."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

HTTP_REQUESTS = Counter(
    "clip_http_requests_total",
    "Total HTTP requests.",
    ["method", "route", "status"],
)
HTTP_REQUEST_LATENCY = Histogram(
    "clip_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "route"],
)
SEARCH_LATENCY = Histogram(
    "clip_search_duration_seconds",
    "Search latency in seconds.",
    ["kind", "mode"],
)
EMBEDDING_LATENCY = Histogram(
    "clip_embedding_duration_seconds",
    "CLIP embedding latency in seconds.",
    ["kind", "priority"],
)
INDEXING_JOBS = Counter(
    "clip_indexing_jobs_total",
    "Indexing jobs by terminal status.",
    ["status"],
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
