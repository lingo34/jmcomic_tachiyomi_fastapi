"""Manga catalog endpoints: popular, latest, search, details, chapters."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.capabilities import ensure
from app.dependencies import ApiKeyGuard, ServiceDep, SettingsDep
from app.schemas import MangaEnvelope, PagedChapter, PagedManga

router = APIRouter(prefix="/v1/manga", tags=["manga"], dependencies=[ApiKeyGuard])

PageQuery = Query(default=1, ge=1, description="1-based page number")
PageSizeQuery = Query(default=None, ge=1, le=200, description="Items per page")


@router.get("/popular", response_model=PagedManga, summary="Popular / browse list")
async def popular_manga(
    service: ServiceDep,
    settings: SettingsDep,
    page: int = PageQuery,
    page_size: int | None = PageSizeQuery,
) -> PagedManga:
    ensure("popular")
    return service.list_popular(page, page_size or settings.default_page_size)


@router.get("/latest", response_model=PagedManga, summary="Latest list")
async def latest_manga(
    service: ServiceDep,
    settings: SettingsDep,
    page: int = PageQuery,
    page_size: int | None = PageSizeQuery,
) -> PagedManga:
    ensure("latest")
    return service.list_latest(page, page_size or settings.default_page_size)


@router.get("/search", response_model=PagedManga, summary="Search with filters")
async def search_manga(
    service: ServiceDep,
    settings: SettingsDep,
    query: str | None = Query(default=None, description="Free-text query"),
    page: int = PageQuery,
    page_size: int | None = PageSizeQuery,
    filter_category: str | None = Query(default=None, alias="filter.category"),
    filter_time: str | None = Query(default=None, alias="filter.time"),
    filter_tag: str | None = Query(default=None, alias="filter.tag"),
    sort: str | None = Query(default=None),
    order: str | None = Query(default=None),
) -> PagedManga:
    ensure("search")
    return service.search(
        query,
        page,
        page_size or settings.default_page_size,
        filter_category,
        filter_time,
        sort,
        order,
        filter_tag,
    )


@router.get("/{manga_id}", response_model=MangaEnvelope, summary="Manga details")
async def manga_details(manga_id: str, service: ServiceDep) -> MangaEnvelope:
    ensure("manga_details")
    return service.manga(manga_id)


@router.get(
    "/{manga_id}/chapters",
    response_model=PagedChapter,
    summary="Chapter list",
)
async def chapters(
    manga_id: str,
    service: ServiceDep,
    settings: SettingsDep,
    page: int = PageQuery,
    page_size: int | None = PageSizeQuery,
) -> PagedChapter:
    ensure("chapters")
    return service.list_chapters(manga_id, page, page_size or settings.default_page_size)
