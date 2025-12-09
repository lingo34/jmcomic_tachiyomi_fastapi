from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


class FakeService:
    def __init__(self) -> None:
        self.manga_item = main.RemoteManga(
            id="demo",
            title="Demo Manga",
            url="https://example.test/album/demo",
            thumbnail="https://example.test/media/demo.jpg",
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
                main.RemotePage(index=0, image_url="https://example.test/p0.jpg"),
                main.RemotePage(index=1, image_url="https://example.test/p1.jpg"),
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

    def list_pages(self, chapter_id: str, _request=None) -> main.PageListResponse:
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
