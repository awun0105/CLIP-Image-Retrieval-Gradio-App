"""Search endpoints — text and image queries."""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_image_service, get_search_service
from api.schemas import (
    SearchResponse,
    SearchResultItem,
    TextSearchRequest,
)
from core.image_service import ImageService
from core.schemas import SearchResult
from core.search import SearchService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/search", tags=["search"])


def _decode_image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


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
    try:
        results = search_service.search_by_text(request.query, request.top_k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(results, image_service, request.query)


@router.post("/image", response_model=SearchResponse)
async def search_by_image(
    file: Annotated[UploadFile, File(...)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    image_service: Annotated[ImageService, Depends(get_image_service)],
    top_k: int = 5,
) -> SearchResponse:
    if top_k < 1 or top_k > 100:
        raise HTTPException(status_code=400, detail="top_k must be in [1, 100]")
    data = await file.read()
    try:
        image = await run_in_threadpool(_decode_image, data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}") from exc
    results = await run_in_threadpool(search_service.search_by_image, image, top_k)
    return await run_in_threadpool(_to_response, results, image_service, None)
