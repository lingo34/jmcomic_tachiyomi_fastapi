"""Pydantic response models mirroring the Remote API contract.

The shapes here match ``docs/remote-api-openapi.yaml`` and the Kotlin data
classes consumed by the ``remoteapi`` Tachiyomi extension.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class SupportFlags(BaseModel):
    popular: bool = True
    latest: bool = True
    search: bool = True
    manga_details: bool = True
    chapters: bool = True
    pages: bool = True


class DefaultValues(BaseModel):
    page_size: int | None = Field(default=None, ge=1, le=200)


class AuthSpec(BaseModel):
    header: str = "X-Api-Key"
    type: str = "apiKey"
    scheme: str = "plain"


class FilterOption(BaseModel):
    value: str
    label: str


class FilterDefinition(BaseModel):
    key: str
    label: str
    type: str
    options: list[FilterOption] = Field(default_factory=list)
    default: str | None = None
    section: str | None = None


class CapabilitiesResponse(BaseModel):
    name: str
    version: str
    supports: SupportFlags = Field(default_factory=SupportFlags)
    filters: list[FilterDefinition] = Field(default_factory=list)
    auth: AuthSpec = Field(default_factory=AuthSpec)
    defaults: DefaultValues = Field(default_factory=DefaultValues)


class RemoteManga(BaseModel):
    id: str
    title: str
    alt_titles: list[str] = Field(default_factory=list)
    url: HttpUrl | None = None
    thumbnail: HttpUrl | None = None
    description: str | None = None
    author: str | None = None
    artist: str | None = None
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    lang: str | None = None
    nsfw: bool | None = None


class RemoteChapter(BaseModel):
    id: str
    name: str
    url: str | None = None
    number: float | None = None
    volume: str | None = None
    scanlator: str | None = None
    uploaded: int | None = None


class RemotePage(BaseModel):
    index: int | None = None
    image_url: HttpUrl
    page_url: HttpUrl | None = None
    headers: dict[str, str] | None = None


class PagedResult(BaseModel):
    items: list[Any]
    has_next: bool = False
    total: int | None = None


class PagedManga(PagedResult):
    items: list[RemoteManga]


class PagedChapter(PagedResult):
    items: list[RemoteChapter]


class MangaEnvelope(BaseModel):
    manga: RemoteManga
    chapters: list[RemoteChapter] | None = None


class PageListResponse(BaseModel):
    pages: list[RemotePage]


class HealthResponse(BaseModel):
    status: str = "ok"
    name: str
    version: str


class ErrorResponse(BaseModel):
    """Uniform error envelope returned by exception handlers."""

    detail: str
    message: str
