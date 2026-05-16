"""FastAPI application factory."""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, index, metrics, search
from core.logging import request_id_var
from core.metrics import HTTP_REQUEST_LATENCY, HTTP_REQUESTS

try:
    __version__ = version("clip-image-retrieval")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="CLIP Image Retrieval",
        version=__version__,
        description="Multimodal image retrieval service backed by CLIP, Qdrant and MinIO.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(search.router)
    app.include_router(index.router)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        token = request_id_var.set(request_id)
        start = perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        route = getattr(request.scope.get("route"), "path", request.url.path)
        status = str(response.status_code)
        duration = perf_counter() - start
        HTTP_REQUESTS.labels(request.method, route, status).inc()
        HTTP_REQUEST_LATENCY.labels(request.method, route).observe(duration)
        return response

    return app
