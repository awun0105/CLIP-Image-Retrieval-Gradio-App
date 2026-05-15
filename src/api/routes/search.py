"""Search endpoints — text and image queries."""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_image_service, get_search_service, get_settings
from api.schemas import (
    SearchResponse,
    SearchResultItem,
    TextSearchRequest,
)
from api.security import read_upload_bytes, require_api_key
from config import Settings
from core.image_service import ImageService
from core.metrics import SEARCH_LATENCY
from core.schemas import SearchMode, SearchResult
from core.search import SearchService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/search", tags=["search"], dependencies=[Depends(require_api_key)])


def _decode_image(data: bytes, max_image_pixels: int) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        if max_image_pixels > 0 and image.width * image.height > max_image_pixels:
            raise HTTPException(
                status_code=413,
                detail=f"Decoded image exceeds MAX_IMAGE_PIXELS={max_image_pixels}",
            )
        return image.convert("RGB")


def _to_response(
    results: list[SearchResult],
    image_service: ImageService,
    query: str | None,
) -> SearchResponse:
    def _item_for_result(r: SearchResult) -> SearchResultItem:
        try:
            url = image_service.get_image_url(r.image_path)
        except Exception as exc:
            logger.warning("Failed to presign %s: %s", r.image_path, exc)
            url = None
        return SearchResultItem(
            image_path=r.image_path,
            image_url=url,
            score=r.score,
            caption=r.caption,
            filename=r.filename,
        )

    if not results:
        return SearchResponse(results=[], total=0, query=query)

    with ThreadPoolExecutor(max_workers=min(8, len(results))) as executor:
        items = list(executor.map(_item_for_result, results))
    return SearchResponse(results=items, total=len(items), query=query)


@router.post("/text", response_model=SearchResponse)
def search_by_text(
    request: TextSearchRequest,
    search_service: Annotated[SearchService, Depends(get_search_service)],
    image_service: Annotated[ImageService, Depends(get_image_service)],
) -> SearchResponse:
    start = perf_counter()
    try:
        results = search_service.search_by_text(
            request.query,
            request.top_k,
            request.search_mode,
            request.hnsw_ef,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        SEARCH_LATENCY.labels("text", request.search_mode.value).observe(perf_counter() - start)
    return _to_response(results, image_service, request.query)


@router.post("/image", response_model=SearchResponse)
async def search_by_image(
    file: Annotated[UploadFile, File(...)],
    settings: Annotated[Settings, Depends(get_settings)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    image_service: Annotated[ImageService, Depends(get_image_service)],
    top_k: int = 5,
    search_mode: SearchMode = SearchMode.ANN,
    hnsw_ef: Annotated[int | None, Query(ge=32, le=512)] = None,
) -> SearchResponse:
    if top_k < 1 or top_k > 100:
        raise HTTPException(status_code=400, detail="top_k must be in [1, 100]")
    data = await read_upload_bytes(file, settings)
    try:
        start = perf_counter()
        image = await run_in_threadpool(_decode_image, data, settings.max_image_pixels)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}") from exc
    results = await run_in_threadpool(
        search_service.search_by_image,
        image,
        top_k,
        search_mode,
        hnsw_ef,
    )
    SEARCH_LATENCY.labels("image", search_mode.value).observe(perf_counter() - start)
    return await run_in_threadpool(_to_response, results, image_service, None)
