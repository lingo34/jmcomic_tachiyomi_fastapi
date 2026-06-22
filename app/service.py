"""Service layer adapting the ``jmcomic`` client to Remote API shapes."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable, Sequence
from io import BytesIO
from threading import BoundedSemaphore, Lock
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status
from jmcomic import (
    JmAlbumDetail,
    JmcomicException,
    JmcomicText,
    JmImageDetail,
    JmImageTool,
    JmMagicConstants,
    JmOption,
    JmPhotoDetail,
    JmSearchPage,
    MissingAlbumPhotoException,
    disable_jm_log,
)
from PIL import Image
from pydantic import HttpUrl

from app.config import Settings
from app.schemas import (
    MangaEnvelope,
    PagedChapter,
    PagedManga,
    PageListResponse,
    RemoteChapter,
    RemoteManga,
    RemotePage,
)

logger = logging.getLogger(__name__)

_UPSTREAM_ERROR_DETAIL = "Upstream content service is unavailable"

_CONTENT_TYPE_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_PIL_FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".gif": "GIF",
}
_SORT_TO_ORDER_BY = {
    "updated": JmMagicConstants.ORDER_BY_LATEST,
    "latest": JmMagicConstants.ORDER_BY_LATEST,
    "view": JmMagicConstants.ORDER_BY_VIEW,
    "views": JmMagicConstants.ORDER_BY_VIEW,
    "like": JmMagicConstants.ORDER_BY_LIKE,
    "likes": JmMagicConstants.ORDER_BY_LIKE,
    "pictures": JmMagicConstants.ORDER_BY_PICTURE,
}


def _upstream_error(exc: JmcomicException) -> HTTPException:
    """Log the upstream failure and return a sanitized 502 for the client."""
    # Log only the exception *type* — never its message, which can embed the
    # requested album/photo id or upstream URL (client-derived information).
    logger.warning("jmcomic upstream request failed (%s)", type(exc).__name__)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UPSTREAM_ERROR_DETAIL)


class JmcomicService:
    """Thin wrapper around the jmcomic client exposing Remote API shaped data."""

    def __init__(self, settings: Settings, domain_list: Sequence[str] | None = None):
        self.settings = settings
        self.impl = settings.jmcomic_impl
        self.domain_list = list(domain_list) if domain_list else None
        self._client_lock = Lock()
        # Bound concurrent image decodes so peak memory stays predictable on
        # small (e.g. 256 MB) hosts.
        self._image_semaphore = BoundedSemaphore(settings.max_concurrent_images)
        # Cap PIL's pixel budget to block decompression bombs and bound memory.
        Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
        self._client = self._create_client()

    def _create_client(self) -> Any:
        if self.settings.jmcomic_disable_log:
            disable_jm_log()
        return JmOption.default().new_jm_client(impl=self.impl, domain_list=self.domain_list)

    def _refresh_client(self) -> Any:
        with self._client_lock:
            self._client = self._create_client()
            return self._client

    def _call_with_client_retry(
        self,
        operation: Callable[[Any], Any],
        *,
        missing_detail: str | None = None,
    ) -> Any:
        last_exc: JmcomicException | None = None
        for attempt in range(2):
            client = self._client if attempt == 0 else self._refresh_client()
            try:
                return operation(client)
            except MissingAlbumPhotoException as exc:
                if missing_detail is None:
                    raise
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=missing_detail
                ) from exc
            except JmcomicException as exc:
                last_exc = exc

        if last_exc is None:  # pragma: no cover - defensive guard
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_UPSTREAM_ERROR_DETAIL,
            )
        raise _upstream_error(last_exc) from last_exc

    # --------------------------- list endpoints ---------------------------
    def list_popular(self, page: int, page_size: int) -> PagedManga:
        def fetch(page_index: int) -> JmSearchPage:
            return cast(
                JmSearchPage,
                self._call_with_client_retry(
                    lambda client: client.categories_filter(
                        page=page_index,
                        time=JmMagicConstants.TIME_WEEK,
                        category=JmMagicConstants.CATEGORY_ALL,
                        order_by=JmMagicConstants.ORDER_WEEK_RANKING,
                    ),
                ),
            )

        return self._search_to_paged_manga(fetch, page, page_size)

    def list_latest(self, page: int, page_size: int) -> PagedManga:
        def fetch(page_index: int) -> JmSearchPage:
            return cast(
                JmSearchPage,
                self._call_with_client_retry(
                    lambda client: client.search_site(
                        search_query="",
                        page=page_index,
                        order_by=JmMagicConstants.ORDER_BY_LATEST,
                        time=JmMagicConstants.TIME_TODAY,
                        category=JmMagicConstants.CATEGORY_ALL,
                    ),
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
        sort, order = self._normalize_sort_order(sort, order)
        order_by = self._sort_to_order_by(sort)
        time_code = time or JmMagicConstants.TIME_ALL
        category_code = category or JmMagicConstants.CATEGORY_ALL

        def fetch(page_index: int) -> JmSearchPage:
            if tag and not query:
                return cast(
                    JmSearchPage,
                    self._call_with_client_retry(
                        lambda client: client.search_tag(tag, page=page_index),
                    ),
                )
            return cast(
                JmSearchPage,
                self._call_with_client_retry(
                    lambda client: client.search_site(
                        search_query=query or "",
                        page=page_index,
                        order_by=order_by,
                        time=time_code,
                        category=category_code,
                    ),
                ),
            )

        reverse = order == "asc"
        return self._search_to_paged_manga(fetch, page, page_size, reverse=reverse)

    # --------------------------- details endpoints ---------------------------
    def manga(self, manga_id: str) -> MangaEnvelope:
        album = cast(
            JmAlbumDetail,
            self._call_with_client_retry(
                lambda client: client.get_album_detail(manga_id),
                missing_detail="Manga not found",
            ),
        )
        chapters = [self._photo_to_remote_chapter(photo) for photo in album]
        return MangaEnvelope(manga=self._album_to_remote(album), chapters=chapters)

    def list_chapters(self, manga_id: str, page: int, page_size: int) -> PagedChapter:
        album = cast(
            JmAlbumDetail,
            self._call_with_client_retry(
                lambda client: client.get_album_detail(manga_id),
                missing_detail="Manga not found",
            ),
        )
        all_photos = list(cast(Iterable[JmPhotoDetail], album))
        start = (page - 1) * page_size
        end = start + page_size
        if start >= len(all_photos):
            return PagedChapter(items=[], has_next=False, total=len(all_photos))

        sliced = all_photos[start:end]
        chapters = [self._photo_to_remote_chapter(photo) for photo in sliced]
        return PagedChapter(items=chapters, has_next=end < len(all_photos), total=len(all_photos))

    def list_pages(self, chapter_id: str, request: Request | None = None) -> PageListResponse:
        photo_detail = cast(
            JmPhotoDetail,
            self._call_with_client_retry(
                lambda client: client.get_photo_detail(chapter_id),
                missing_detail="Chapter not found",
            ),
        )
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
            pages.append(RemotePage(index=idx, image_url=image_url, headers=headers))
        return PageListResponse(pages=pages)

    def page_image(self, chapter_id: str, page_index: int) -> tuple[bytes, str]:
        if page_index < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="page_index must be non-negative",
            )

        def fetch_image(client: Any) -> tuple[bytes, str]:
            photo_detail = cast(JmPhotoDetail, client.get_photo_detail(chapter_id))
            images = list(cast(Iterable[JmImageDetail], photo_detail))
            if page_index >= len(images):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

            image = images[page_index]
            resp = client.get_jm_image(image.download_url)
            resp.require_success()

            decode_needed = not client.img_is_not_need_to_decode(image.download_url, resp)
            return self._decode_image_resp(resp, image, decode_image=decode_needed)

        # Hold the decode slot across fetch + decode to bound peak memory.
        with self._image_semaphore:
            return cast(
                tuple[bytes, str],
                self._call_with_client_retry(fetch_image, missing_detail="Chapter not found"),
            )

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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="page and page_size must be positive",
            )

        start = (user_page - 1) * user_page_size
        end = start + user_page_size
        site_size_guess = 80

        try:
            first_page_index = start // site_size_guess + 1
            first_page = fetch_page(first_page_index)
        except JmcomicException as exc:
            raise _upstream_error(exc) from exc

        site_size = first_page.page_size or site_size_guess
        site_page_start = start // site_size + 1
        site_page_end = (max(end - 1, start)) // site_size + 1

        # If our initial guess was off, refetch the starting page.
        if site_page_start != first_page_index:
            try:
                first_page = fetch_page(site_page_start)
            except JmcomicException as exc:
                raise _upstream_error(exc) from exc
            site_size = first_page.page_size or site_size

        total = first_page.total or len(first_page.content)
        entries: list[tuple[str, dict[str, Any]]] = list(first_page.content)

        current = site_page_start
        while current < site_page_end:
            current += 1
            try:
                next_page = fetch_page(current)
            except JmcomicException as exc:
                raise _upstream_error(exc) from exc
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
        return RemoteManga(
            id=str(album_id),
            title=title,
            author=author,
            tags=tags,
            thumbnail=self._cover_url(str(album_id)),
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
        return RemoteChapter(id=str(photo.id), name=name, number=number, uploaded=None)

    def _cover_url(self, album_id: str) -> HttpUrl:
        return cast(
            HttpUrl,
            JmcomicText.get_album_cover_url(
                album_id, image_domain=self.settings.jmcomic_image_domain
            ),
        )

    def _album_url(self, album_id: str) -> HttpUrl:
        return cast(
            HttpUrl,
            JmcomicText.format_url(f"/album/{album_id}", self.settings.jmcomic_html_domain),
        )

    def _sort_to_order_by(self, sort: str | None) -> str:
        return _SORT_TO_ORDER_BY.get((sort or "").lower(), JmMagicConstants.ORDER_BY_LATEST)

    @staticmethod
    def _normalize_sort_order(sort: str | None, order: str | None) -> tuple[str | None, str | None]:
        normalized_sort = (sort or "").strip()
        normalized_order = (order or "").strip().lower() or None

        if ":" in normalized_sort:
            sort_name, sort_order = normalized_sort.split(":", 1)
            normalized_sort = sort_name.strip()
            if normalized_order is None and sort_order.strip():
                normalized_order = sort_order.strip().lower()

        return normalized_sort or None, normalized_order

    def _image_headers(self, download_url: str, album_id: str | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        parsed = urlparse(download_url)
        if parsed.scheme and parsed.netloc:
            headers["Host"] = parsed.netloc
        referer_base = self.settings.jmcomic_image_referer
        if not referer_base:
            if album_id:
                referer_base = str(self._album_url(str(album_id)))
            elif parsed.scheme and parsed.netloc:
                referer_base = f"{parsed.scheme}://{parsed.netloc}/"
        if referer_base:
            headers["Referer"] = referer_base
        if self.settings.jmcomic_ua:
            headers["User-Agent"] = self.settings.jmcomic_ua
        return headers

    # --- image decoding helpers -------------------------------------------
    @staticmethod
    def _content_type_for_suffix(suffix: str | None) -> str:
        if suffix is None:
            return "image/jpeg"
        return _CONTENT_TYPE_BY_SUFFIX.get(suffix.lower(), "image/jpeg")

    @staticmethod
    def _pil_format_for_suffix(suffix: str | None) -> str:
        if suffix is None:
            return "JPEG"
        return _PIL_FORMAT_BY_SUFFIX.get(suffix.lower(), "JPEG")

    def _decode_image_resp(
        self, resp: Any, image: JmImageDetail, *, decode_image: bool
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
            # Log only the exception type — never the message/URL.
            logger.warning("image decode failed (%s)", type(exc).__name__)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to decode image",
            ) from exc

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
