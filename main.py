"""FastAPI server that adapts the JMComic mobile API to the Remote API contract.

The Kotlin Remote API extension talks to this server. We reuse the same response
models as the sample server, but the data comes from the `jmcomic` library in
API (mobile) mode.
"""
from __future__ import annotations

import os
from functools import lru_cache
from io import BytesIO
import math
from typing import Any, Callable, Iterable, Sequence, cast
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, HttpUrl

from jmcomic import (
    JmAlbumDetail,
    JmImageDetail,
    JmImageTool,
    JmMagicConstants,
    JmOption,
    JmPhotoDetail,
    JmSearchPage,
    JmcomicException,
    JmcomicText,
    MissingAlbumPhotoException,
    disable_jm_log,
)
from PIL import Image

app = FastAPI(title="JMComic Remote API", version="0.1.0")

# ---------------------------------------------------------------------------
# Models (mirror the Kotlin data classes)
# ---------------------------------------------------------------------------


class SupportFlags(BaseModel):
    popular: bool = True
    latest: bool = True
    search: bool = True
    manga_details: bool = True
    chapters: bool = True
    pages: bool = True


class DefaultValues(BaseModel):
    page_size: int | None = Field(None, ge=1, le=200)


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
    supports: SupportFlags = Field(default_factory=lambda: SupportFlags())
    filters: list[FilterDefinition] = Field(default_factory=list)
    auth: AuthSpec = Field(default_factory=lambda: AuthSpec())
    defaults: DefaultValues = Field(default_factory=lambda: DefaultValues(page_size=None))


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


# ---------------------------------------------------------------------------
# Capability configuration
# ---------------------------------------------------------------------------


SUPPORT_FLAGS = SupportFlags()
DEFAULT_PAGE_SIZE = int(os.getenv("JMCOMIC_DEFAULT_PAGE_SIZE", "40"))
DEFAULTS = DefaultValues(page_size=DEFAULT_PAGE_SIZE)

CATEGORY_FILTER = FilterDefinition(
    key="category",
    label="Category",
    type="select",
    options=[
        FilterOption(value=JmMagicConstants.CATEGORY_ALL, label="All"),
        FilterOption(value=JmMagicConstants.CATEGORY_DOUJIN, label="Doujin"),
        FilterOption(value=JmMagicConstants.CATEGORY_HANMAN, label="Hanman"),
        FilterOption(value=JmMagicConstants.CATEGORY_MEIMAN, label="Meiman"),
        FilterOption(value=JmMagicConstants.CATEGORY_SHORT, label="Short"),
        FilterOption(value=JmMagicConstants.CATEGORY_SINGLE, label="Single"),
    ],
    default=JmMagicConstants.CATEGORY_ALL,
)

TIME_FILTER = FilterDefinition(
    key="time",
    label="Time",
    type="select",
    options=[
        FilterOption(value=JmMagicConstants.TIME_TODAY, label="Today"),
        FilterOption(value=JmMagicConstants.TIME_WEEK, label="Week"),
        FilterOption(value=JmMagicConstants.TIME_MONTH, label="Month"),
        FilterOption(value=JmMagicConstants.TIME_ALL, label="All"),
    ],
    default=JmMagicConstants.TIME_ALL,
)

SORT_FILTER = FilterDefinition(
    key="sort",
    label="Sort",
    type="sort",
    options=[
        FilterOption(value="updated", label="Updated"),
        FilterOption(value="view", label="Views"),
        FilterOption(value="like", label="Likes"),
        FilterOption(value="pictures", label="Pictures"),
    ],
    default="updated:desc",
)

TAG_FILTER = FilterDefinition(
    key="tag",
    label="Tag",
    type="text",
    default=None,
)

FILTERS: list[FilterDefinition] = [CATEGORY_FILTER, TIME_FILTER, SORT_FILTER, TAG_FILTER]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _auth_spec() -> AuthSpec:
    return AuthSpec(header=os.environ.get("REMOTEAPI_API_HEADER", "X-Api-Key"))


def _api_key() -> str | None:
    return os.environ.get("REMOTEAPI_API_KEY")


def require_api_key(request: Request) -> None:
    key = _api_key()
    if key is None:
        return
    header = _auth_spec().header
    provided = request.headers.get(header)
    if provided != key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def ensure(feature: str) -> None:
    flag_value = getattr(SUPPORT_FLAGS, feature, None)
    if not isinstance(flag_value, bool):
        raise HTTPException(status_code=500, detail=f"Support flag '{feature}' is invalid")
    if not flag_value:
        raise HTTPException(status_code=501, detail=f"Feature '{feature}' is disabled by server")


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


def _logs_disabled() -> bool:
    return os.getenv("JMCOMIC_DISABLE_LOG", "true").lower() not in {"false", "0"}


class JmcomicService:
    """Thin wrapper around jmcomic client to expose Remote API shaped data."""

    def __init__(self, impl: str = "api", domain_list: Sequence[str] | None = None):
        self.impl = impl
        self.domain_list = [d for d in domain_list] if domain_list else None
        if _logs_disabled():
            disable_jm_log()
        self._client = JmOption.default().new_jm_client(impl=self.impl, domain_list=self.domain_list)

    # --------------------------- list endpoints ---------------------------
    def list_popular(self, page: int, page_size: int) -> PagedManga:
        def fetch(page_index: int) -> JmSearchPage:
            return cast(
                JmSearchPage,
                self._client.categories_filter(
                    page=page_index,
                    time=JmMagicConstants.TIME_WEEK,
                    category=JmMagicConstants.CATEGORY_ALL,
                    order_by=JmMagicConstants.ORDER_WEEK_RANKING,
                ),
            )

        return self._search_to_paged_manga(fetch, page, page_size)

    def list_latest(self, page: int, page_size: int) -> PagedManga:
        def fetch(page_index: int) -> JmSearchPage:
            return cast(
                JmSearchPage,
                self._client.search_site(
                    search_query="",
                    page=page_index,
                    order_by=JmMagicConstants.ORDER_BY_LATEST,
                    time=JmMagicConstants.TIME_TODAY,
                    category=JmMagicConstants.CATEGORY_ALL,
                ),
            )

        return self._search_to_paged_manga(fetch, page, page_size)

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
    ) -> PagedManga:
        order_by = self._sort_to_order_by(sort)
        time_code = time or JmMagicConstants.TIME_ALL
        category_code = category or JmMagicConstants.CATEGORY_ALL

        def fetch(page_index: int) -> JmSearchPage:
            try:
                if tag and not query:
                    return cast(JmSearchPage, self._client.search_tag(tag, page=page_index))
                return cast(
                    JmSearchPage,
                    self._client.search_site(
                        search_query=query or "",
                        page=page_index,
                        order_by=order_by,
                        time=time_code,
                        category=category_code,
                    ),
                )
            except JmcomicException as exc:  # allow HTTPException wrapping below
                raise exc

        reverse = order == "asc"
        return self._search_to_paged_manga(fetch, page, page_size, reverse=reverse)

    # --------------------------- details endpoints ---------------------------
    def manga(self, manga_id: str) -> MangaEnvelope:
        try:
            album = cast(JmAlbumDetail, self._client.get_album_detail(manga_id))
        except MissingAlbumPhotoException as exc:
            raise HTTPException(status_code=404, detail="Manga not found") from exc
        except JmcomicException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        chapters = [self._photo_to_remote_chapter(photo) for photo in album]
        return MangaEnvelope(manga=self._album_to_remote(album), chapters=chapters)

    def list_chapters(self, manga_id: str, page: int, page_size: int) -> PagedChapter:
        try:
            album = cast(JmAlbumDetail, self._client.get_album_detail(manga_id))
        except MissingAlbumPhotoException as exc:
            raise HTTPException(status_code=404, detail="Manga not found") from exc
        except JmcomicException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        all_photos = list(cast(Iterable[JmPhotoDetail], album))
        start = (page - 1) * page_size
        end = start + page_size
        if start >= len(all_photos):
            return PagedChapter(items=[], has_next=False, total=len(all_photos))

        sliced = all_photos[start:end]
        chapters = [self._photo_to_remote_chapter(photo) for photo in sliced]
        return PagedChapter(items=chapters, has_next=end < len(all_photos), total=len(all_photos))

    def list_pages(self, chapter_id: str, request: Request | None = None) -> PageListResponse:
        try:
            photo_detail = cast(JmPhotoDetail, self._client.get_photo_detail(chapter_id))
        except MissingAlbumPhotoException as exc:
            raise HTTPException(status_code=404, detail="Chapter not found") from exc
        except JmcomicException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        pages: list[RemotePage] = []
        album_id = getattr(photo_detail, "album_id", getattr(photo_detail, "aid", None))
        base_url = str(request.base_url).rstrip("/") if request is not None else None

        def image_url_for(idx: int, image: JmImageDetail) -> HttpUrl:
            if base_url:
                return cast(HttpUrl, f"{base_url}/v1/chapters/{chapter_id}/pages/{idx}/image")
            return cast(HttpUrl, image.download_url)

        for idx, image in enumerate(cast(Iterable[JmImageDetail], photo_detail)):
            image_url = image_url_for(idx, image)
            headers = None if base_url else self._image_headers(image.download_url, album_id)
            pages.append(
                RemotePage(
                    index=idx,
                    image_url=image_url,
                    headers=headers,
                )
            )
        return PageListResponse(pages=pages)

    def page_image(self, chapter_id: str, page_index: int) -> tuple[bytes, str]:
        if page_index < 0:
            raise HTTPException(status_code=400, detail="page_index must be non-negative")

        try:
            photo_detail = cast(JmPhotoDetail, self._client.get_photo_detail(chapter_id))
        except MissingAlbumPhotoException as exc:
            raise HTTPException(status_code=404, detail="Chapter not found") from exc
        except JmcomicException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        images = list(cast(Iterable[JmImageDetail], photo_detail))
        if page_index >= len(images):
            raise HTTPException(status_code=404, detail="Page not found")

        image = images[page_index]
        try:
            resp = self._client.get_jm_image(image.download_url)
            resp.require_success()
        except JmcomicException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        decode_needed = not self._client.img_is_not_need_to_decode(image.download_url, resp)
        content, media_type = self._decode_image_resp(resp, image, decode_image=decode_needed)
        return content, media_type

    # --------------------------- internal helpers ---------------------------
    def _search_to_paged_manga(
        self,
        fetch_page: Callable[[int], JmSearchPage],
        user_page: int,
        user_page_size: int,
        *,
        reverse: bool = False,
    ) -> PagedManga:
        if user_page < 1 or user_page_size < 1:
            raise HTTPException(status_code=400, detail="page and page_size must be positive")

        start = (user_page - 1) * user_page_size
        end = start + user_page_size
        site_size_guess = 80

        try:
            first_page_index = start // site_size_guess + 1
            first_page = fetch_page(first_page_index)
        except JmcomicException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        site_size = first_page.page_size or site_size_guess
        site_page_start = start // site_size + 1
        site_page_end = (max(end - 1, start)) // site_size + 1

        # If our initial guess was off, refetch starting page
        if site_page_start != first_page_index:
            try:
                first_page = fetch_page(site_page_start)
            except JmcomicException as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            site_size = first_page.page_size or site_size

        total = first_page.total or len(first_page.content)
        entries: list[tuple[str, dict[str, Any]]] = list(first_page.content)

        current = site_page_start
        while current < site_page_end:
            current += 1
            try:
                next_page = fetch_page(current)
            except JmcomicException as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            total = next_page.total or total
            entries.extend(next_page.content)

        slice_start = start - (site_page_start - 1) * site_size
        sliced_entries = entries[slice_start : slice_start + user_page_size]
        mangas = [self._entry_to_remote_manga(entry) for entry in sliced_entries]
        if reverse:
            mangas.reverse()
        has_next = end < (total or len(entries))
        return PagedManga(items=mangas, has_next=has_next, total=total)

    def _entry_to_remote_manga(self, entry: tuple[str, dict[str, Any]] | Any) -> RemoteManga:
        album_id, payload = entry if isinstance(entry, tuple) else (str(entry), {})
        info: dict[str, Any] = payload or {}
        title = info.get("name") or info.get("title") or str(album_id)
        author = info.get("author")
        tags = [str(tag) for tag in info.get("tags", [])]
        thumbnail = self._cover_url(str(album_id))
        return RemoteManga(
            id=str(album_id),
            title=title,
            author=author,
            tags=tags,
            thumbnail=thumbnail,
            url=self._album_url(str(album_id)),
            lang="zh",
            nsfw=True,
        )

    def _album_to_remote(self, album: JmAlbumDetail) -> RemoteManga:
        alt_titles: list[str] = []
        if getattr(album, "oname", None) and album.oname != album.title:
            alt_titles.append(album.oname)
        return RemoteManga(
            id=str(album.id),
            title=album.title,
            alt_titles=alt_titles,
            description=getattr(album, "description", None) or None,
            author=getattr(album, "author", None),
            tags=[str(tag) for tag in getattr(album, "tags", [])],
            thumbnail=self._cover_url(str(album.id)),
            url=self._album_url(str(album.id)),
            lang="zh",
            nsfw=True,
        )

    def _photo_to_remote_chapter(self, photo: JmPhotoDetail) -> RemoteChapter:
        name = getattr(photo, "indextitle", None) or photo.title
        number = float(photo.album_index) if getattr(photo, "album_index", None) else None
        return RemoteChapter(
            id=str(photo.id),
            name=name,
            number=number,
            uploaded=None,
        )

    def _cover_url(self, album_id: str) -> HttpUrl:
        url = JmcomicText.get_album_cover_url(
            album_id,
            image_domain=os.getenv("JMCOMIC_IMAGE_DOMAIN"),
        )
        return cast(HttpUrl, url)

    def _album_url(self, album_id: str) -> HttpUrl:
        domain = os.getenv("JMCOMIC_HTML_DOMAIN", "18comic.vip")
        url = JmcomicText.format_url(f"/album/{album_id}", domain)
        return cast(HttpUrl, url)

    def _sort_to_order_by(self, sort: str | None) -> str:
        mapping = {
            "updated": JmMagicConstants.ORDER_BY_LATEST,
            "latest": JmMagicConstants.ORDER_BY_LATEST,
            "view": JmMagicConstants.ORDER_BY_VIEW,
            "views": JmMagicConstants.ORDER_BY_VIEW,
            "like": JmMagicConstants.ORDER_BY_LIKE,
            "likes": JmMagicConstants.ORDER_BY_LIKE,
            "pictures": JmMagicConstants.ORDER_BY_PICTURE,
        }
        return mapping.get((sort or "").lower(), JmMagicConstants.ORDER_BY_LATEST)

    def _image_headers(self, download_url: str, album_id: str | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        parsed = urlparse(download_url)
        if parsed.scheme and parsed.netloc:
            headers["Host"] = parsed.netloc
        referer_base = os.getenv("JMCOMIC_IMAGE_REFERER")
        if not referer_base:
            if album_id:
                referer_base = str(self._album_url(str(album_id)))
            elif parsed.scheme and parsed.netloc:
                referer_base = f"{parsed.scheme}://{parsed.netloc}/"
        if referer_base:
            headers["Referer"] = referer_base
        ua = os.getenv("JMCOMIC_UA")
        if ua:
            headers["User-Agent"] = ua
        return headers

    # --- image decoding helpers -------------------------------------------------

    @staticmethod
    def _content_type_for_suffix(suffix: str | None) -> str:
        mapping = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        if suffix is None:
            return "image/jpeg"
        return mapping.get(suffix.lower(), "image/jpeg")

    @staticmethod
    def _pil_format_for_suffix(suffix: str | None) -> str:
        mapping = {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".webp": "WEBP",
            ".gif": "GIF",
        }
        if suffix is None:
            return "JPEG"
        return mapping.get(suffix.lower(), "JPEG")

    def _decode_image_resp(
        self,
        resp: Any,
        image: JmImageDetail,
        *,
        decode_image: bool,
    ) -> tuple[bytes, str]:
        suffix = getattr(image, "img_file_suffix", None)
        content_type = self._content_type_for_suffix(suffix)

        if not decode_image:
            return resp.content, content_type

        try:
            num = JmImageTool.get_num_by_url(image.scramble_id, image.download_url)
            img_src = JmImageTool.open_image(resp.content)
            decoded = self._decode_segments(img_src, num)
            buffer = BytesIO()
            save_format = img_src.format or self._pil_format_for_suffix(suffix)
            decoded.save(buffer, format=save_format)
            return buffer.getvalue(), content_type
        except Exception as exc:  # pragma: no cover - defensive guard
            raise HTTPException(status_code=502, detail=f"Failed to decode image: {exc}") from exc

    @staticmethod
    def _decode_segments(img_src: Image.Image, num: int) -> Image.Image:
        if num == 0:
            return img_src

        w, h = img_src.size
        img_decode = Image.new("RGB", (w, h))
        over = h % num
        for i in range(num):
            move = math.floor(h / num)
            y_src = h - (move * (i + 1)) - over
            y_dst = move * i
            if i == 0:
                move += over
            else:
                y_dst += over
            img_decode.paste(
                img_src.crop((0, y_src, w, y_src + move)),
                (0, y_dst, w, y_dst + move),
            )
        return img_decode


def _parse_domain_list() -> list[str] | None:
    raw = os.getenv("JMCOMIC_DOMAIN_LIST")
    if not raw:
        return None
    domains = [part.strip() for part in raw.split(",") if part.strip()]
    return domains or None


@lru_cache(maxsize=1)
def _service() -> JmcomicService:
    impl = os.getenv("JMCOMIC_IMPL", "api")
    return JmcomicService(impl=impl, domain_list=_parse_domain_list())


def get_service() -> JmcomicService:
    return _service()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/v1/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(
        name="JMComic Remote API",
        version="0.1.0",
        supports=SUPPORT_FLAGS,
        auth=_auth_spec(),
        defaults=DEFAULTS,
        filters=FILTERS,
    )


@app.get("/v1/manga/popular", response_model=PagedManga)
async def popular_manga(
    _request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
    _api_key_check: None = Depends(require_api_key),
    service: JmcomicService = Depends(get_service),
) -> PagedManga:
    ensure("popular")
    return service.list_popular(page, page_size)


@app.get("/v1/manga/latest", response_model=PagedManga)
async def latest_manga(
    _request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
    _api_key_check: None = Depends(require_api_key),
    service: JmcomicService = Depends(get_service),
) -> PagedManga:
    ensure("latest")
    return service.list_latest(page, page_size)


@app.get("/v1/manga/search", response_model=PagedManga)
async def search_manga(
    _request: Request,
    query: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
    filter_category: str | None = Query(None, alias="filter.category"),
    filter_time: str | None = Query(None, alias="filter.time"),
    filter_tag: str | None = Query(None, alias="filter.tag"),
    sort: str | None = None,
    order: str | None = None,
    _api_key_check: None = Depends(require_api_key),
    service: JmcomicService = Depends(get_service),
) -> PagedManga:
    ensure("search")
    return service.search(query, page, page_size, filter_category, filter_time, sort, order, filter_tag)


@app.get("/v1/manga/{manga_id}", response_model=MangaEnvelope)
async def manga_details(
    manga_id: str,
    _request: Request,
    _api_key_check: None = Depends(require_api_key),
    service: JmcomicService = Depends(get_service),
) -> MangaEnvelope:
    ensure("manga_details")
    return service.manga(manga_id)


@app.get("/v1/manga/{manga_id}/chapters", response_model=PagedChapter)
async def chapters(
    manga_id: str,
    _request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
    _api_key_check: None = Depends(require_api_key),
    service: JmcomicService = Depends(get_service),
) -> PagedChapter:
    ensure("chapters")
    return service.list_chapters(manga_id, page, page_size)


@app.get("/v1/chapters/{chapter_id}/pages", response_model=PageListResponse)
async def pages(
    chapter_id: str,
    request: Request,
    _api_key_check: None = Depends(require_api_key),
    service: JmcomicService = Depends(get_service),
) -> PageListResponse:
    ensure("pages")
    return service.list_pages(chapter_id, request)


@app.get("/v1/chapters/{chapter_id}/pages/{page_index}/image")
async def page_image(
    chapter_id: str,
    page_index: int = Path(..., ge=0),
    _api_key_check: None = Depends(require_api_key),
    service: JmcomicService = Depends(get_service),
):
    ensure("pages")
    content, media_type = service.page_image(chapter_id, page_index)
    return Response(content=content, media_type=media_type)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", reload=True)
