from __future__ import annotations

from collections.abc import Iterator
from threading import Lock
from typing import cast

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jmcomic import JmcomicException
from pydantic import HttpUrl

import main


class FakeSearchPage:
    def __init__(
        self,
        content: list[tuple[str, dict[str, object]]],
        *,
        page_size: int = 80,
        total: int | None = None,
    ) -> None:
        self.content = content
        self.page_size = page_size
        self.total = len(content) if total is None else total


class SearchClient:
    def __init__(
        self,
        *,
        result: FakeSearchPage | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    def search_site(
        self,
        *,
        search_query: str,
        page: int,
        order_by: str,
        time: str,
        category: str,
    ) -> FakeSearchPage:
        self.calls.append(
            {
                "search_query": search_query,
                "page": page,
                "order_by": order_by,
                "time": time,
                "category": category,
            }
        )
        if self.exc is not None:
            raise self.exc
        assert self.result is not None
        return self.result


class RefreshingService(main.JmcomicService):
    def __init__(self, clients: list[SearchClient]) -> None:
        self.impl = "api"
        self.domain_list = None
        self._client_lock = Lock()
        self._clients = clients
        self._client_index = 0
        self._client = self._clients[0]

    def _create_client(self) -> SearchClient:
        if self._client_index + 1 < len(self._clients):
            self._client_index += 1
        return self._clients[self._client_index]


class FakeService:
    def __init__(self) -> None:
        self.manga_item = main.RemoteManga(
            id="demo",
            title="Demo Manga",
            url=cast(HttpUrl, "https://example.test/album/demo"),
            thumbnail=cast(HttpUrl, "https://example.test/media/demo.jpg"),
            author="Tester",
            tags=["demo"],
            nsfw=True,
            lang="zh",
        )
        self.chapters_list = [
            main.RemoteChapter(id="c1", name="Chapter 1", number=1.0),
            main.RemoteChapter(id="c2", name="Chapter 2", number=2.0),
        ]
        self.pages = main.PageListResponse(
            pages=[
                main.RemotePage(index=0, image_url=cast(HttpUrl, "https://example.test/p0.jpg")),
                main.RemotePage(index=1, image_url=cast(HttpUrl, "https://example.test/p1.jpg")),
            ]
        )

    # list endpoints
    def list_popular(self, page: int, page_size: int) -> main.PagedManga:
        return main.PagedManga(items=[self.manga_item], has_next=False, total=1)

    def list_latest(self, page: int, page_size: int) -> main.PagedManga:
        return main.PagedManga(items=[self.manga_item], has_next=False, total=1)

    def search(
        self,
        query: str | None,
        page: int,
        page_size: int,
        category: str | None,
        time: str | None,
        sort: str | None,
        order: str | None,
        tag: str | None,
    ) -> main.PagedManga:
        return main.PagedManga(items=[self.manga_item], has_next=False, total=1)

    # detail endpoints
    def manga(self, manga_id: str) -> main.MangaEnvelope:
        if manga_id != self.manga_item.id:
            raise HTTPException(status_code=404, detail="Manga not found")
        return main.MangaEnvelope(manga=self.manga_item, chapters=self.chapters_list)

    def list_chapters(self, manga_id: str, page: int, page_size: int) -> main.PagedChapter:
        if manga_id != self.manga_item.id:
            raise HTTPException(status_code=404, detail="Manga not found")
        return main.PagedChapter(
            items=self.chapters_list[:page_size],
            has_next=False,
            total=len(self.chapters_list),
        )

    def list_pages(self, chapter_id: str, _request: object | None = None) -> main.PageListResponse:
        if chapter_id not in {ch.id for ch in self.chapters_list}:
            raise HTTPException(status_code=404, detail="Chapter not found")
        return self.pages

    def page_image(self, chapter_id: str, page_index: int) -> tuple[bytes, str]:
        if chapter_id not in {ch.id for ch in self.chapters_list}:
            raise HTTPException(status_code=404, detail="Chapter not found")
        if page_index < 0 or page_index >= len(self.pages.pages):
            raise HTTPException(status_code=404, detail="Page not found")
        dummy_bytes = b"image-bytes"
        return dummy_bytes, "image/jpeg"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    fake = FakeService()
    main.app.dependency_overrides[main.require_api_key] = lambda: None
    main.app.dependency_overrides[main.get_service] = lambda: fake
    test_client = TestClient(main.app)
    try:
        yield test_client
    finally:
        main.app.dependency_overrides.clear()
        test_client.close()


def test_capabilities_lists_filters_and_defaults(client: TestClient) -> None:
    response = client.get("/v1/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["supports"]["popular"] is True
    assert payload["defaults"]["page_size"] == 40
    filter_keys = {f["key"] for f in payload["filters"]}
    assert {"category", "time", "sort", "tag"}.issubset(filter_keys)


def test_popular_uses_fake_service(client: TestClient) -> None:
    response = client.get("/v1/manga/popular", params={"page": 1, "page_size": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["id"] == "demo"
    assert payload["has_next"] is False


def test_manga_details_includes_chapters(client: TestClient) -> None:
    response = client.get("/v1/manga/demo")

    assert response.status_code == 200
    body = response.json()
    assert body["manga"]["title"] == "Demo Manga"
    assert len(body["chapters"]) == 2


def test_pages_endpoint_returns_images(client: TestClient) -> None:
    response = client.get("/v1/chapters/c1/pages")

    assert response.status_code == 200
    pages = response.json()["pages"]
    assert len(pages) == 2
    assert all(page["image_url"].startswith("https://example.test/") for page in pages)


def test_unknown_manga_returns_404(client: TestClient) -> None:
    response = client.get("/v1/manga/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Manga not found"


def test_search_refreshes_client_after_jmcomic_error() -> None:
    stale_client = SearchClient(exc=cast(Exception, JmcomicException("stale domain", {})))
    refreshed_client = SearchClient(
        result=FakeSearchPage(
            [
                ("1", {"name": "First"}),
                ("2", {"name": "Second"}),
            ],
            total=2,
        )
    )
    service = RefreshingService([stale_client, refreshed_client])

    result = service.search(
        query="demo",
        page=1,
        page_size=2,
        category=None,
        time=None,
        sort="view:asc",
        order=None,
        tag=None,
    )

    assert [manga.id for manga in result.items] == ["2", "1"]
    assert len(stale_client.calls) == 1
    assert len(refreshed_client.calls) == 1
    assert refreshed_client.calls[0]["order_by"] == service._sort_to_order_by("view")


def test_search_returns_502_after_retry_exhausted() -> None:
    first_client = SearchClient(exc=cast(Exception, JmcomicException("first failure", {})))
    second_client = SearchClient(exc=cast(Exception, JmcomicException("second failure", {})))
    service = RefreshingService([first_client, second_client])

    with pytest.raises(HTTPException) as exc_info:
        service.search(
            query="demo",
            page=1,
            page_size=5,
            category=None,
            time=None,
            sort=None,
            order=None,
            tag=None,
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "second failure"
