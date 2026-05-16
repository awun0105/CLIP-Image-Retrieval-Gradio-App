"""API security dependencies and upload validation helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Security, UploadFile, status
from fastapi.security import APIKeyHeader

from api.dependencies import get_settings
from config import Settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    provided_api_key: Annotated[str | None, Security(api_key_header)],
) -> None:
    """Require a configured API key when API key auth is enabled."""
    if not settings.enable_api_key_auth:
        return
    if not settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key auth is enabled but API_KEY is not configured",
        )
    if provided_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def allowed_image_content_types(settings: Settings) -> set[str]:
    return {
        item.strip().lower()
        for item in settings.allowed_image_content_types.split(",")
        if item.strip()
    }


async def read_upload_bytes(file: UploadFile, settings: Settings) -> bytes:
    """Read an upload with optional byte and content-type guardrails."""
    allowed_types = allowed_image_content_types(settings)
    content_type = (file.content_type or "").lower()
    if allowed_types and content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image content type: {file.content_type}",
        )

    max_bytes = settings.max_upload_bytes
    if max_bytes == 0:
        return await file.read()

    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Uploaded image exceeds MAX_UPLOAD_BYTES={max_bytes}",
            )
        chunks.append(chunk)
    return b"".join(chunks)
