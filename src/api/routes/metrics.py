"""Prometheus metrics endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import Response

from api.dependencies import get_settings
from config import Settings
from core.metrics import metrics_response

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    if not settings.enable_metrics:
        raise HTTPException(status_code=404, detail="Metrics are disabled")
    return metrics_response()
