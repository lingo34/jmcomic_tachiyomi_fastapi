"""Reader endpoints: chapter page list and decoded page images."""

from __future__ import annotations

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response

from app.capabilities import ensure
from app.dependencies import ApiKeyGuard, ServiceDep
from app.schemas import PageListResponse

router = APIRouter(prefix="/v1/chapters", tags=["reader"], dependencies=[ApiKeyGuard])

# Decoded page images are content-addressed and effectively immutable.
_IMAGE_CACHE_CONTROL = "public, max-age=86400, immutable"


@router.get(
    "/{chapter_id}/pages",
    response_model=PageListResponse,
    summary="List pages for a chapter",
)
async def pages(chapter_id: str, request: Request, service: ServiceDep) -> PageListResponse:
    ensure("pages")
    return service.list_pages(chapter_id, request)


@router.get(
    "/{chapter_id}/pages/{page_index}/image",
    summary="Decoded page image bytes",
    responses={200: {"content": {"image/*": {}}}},
)
async def page_image(
    chapter_id: str,
    service: ServiceDep,
    page_index: int = Path(..., ge=0),
) -> Response:
    ensure("pages")
    content, media_type = service.page_image(chapter_id, page_index)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": _IMAGE_CACHE_CONTROL},
    )
