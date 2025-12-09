# Remote API contract for Keiyoushi/Tachiyomi extensions

This repository contains a Kotlin extension (`src/all/remoteapi`) that forwards every app action to a JSON API. The goal is to keep the Kotlin side as a thin glue layer while backend authors implement real logic in any language.

## Feature matrix

The extension mirrors the standard Tachiyomi flow:

- Browse/Popular → `GET /v1/manga/popular`
- Latest (optional) → `GET /v1/manga/latest`
- Search + filters → `GET /v1/manga/search`
- Manga details → `GET /v1/manga/{manga_id}`
- Chapter list → `GET /v1/manga/{manga_id}/chapters`
- Page list → `GET /v1/chapters/{chapter_id}/pages`

Before doing anything the client calls `GET /v1/capabilities` to learn which features are supported and which request headers to send for auth. If a feature is unavailable the server should return **501 Not Implemented**; the extension surfaces a readable error instead of crashing.

## Data shapes

All payloads are defined in `docs/remote-api-openapi.yaml`. The important fields:

- `RemoteManga`: `id`, `title`, optional `thumbnail`, `description`, `author`, `artist`, `status`, `tags`, `lang`, `nsfw`.
- `RemoteChapter`: `id`, `name`, optional `number`, `volume`, `scanlator`, `uploaded` (epoch ms).
- `RemotePage`: `index` (0-based), `image_url`, optional `headers` (sent with the image request).
- `PagedResult`: `items`, `has_next`, optional `total`.
- `CapabilitiesResponse`: `supports` (feature flags), `filters` (dynamic filter list), `auth` (header name/type), `defaults.page_size`.

## Filters

Filters are defined by the server and rendered dynamically by the extension. Supported types: `text`, `checkbox`, `select`, and `sort` (uses `sort` + `order` query params). Each filter is sent as `filter.<key>=<value>`.

## Auth

If `auth.header` is present the extension will send the configured API key for every call. The sample backend accepts `X-Api-Key`, but you can change the header name via `capabilities` and set an optional key with the `REMOTEAPI_API_KEY` env var.

## Error handling

- Use **501** when a capability is disabled (e.g., latest not implemented).
- Use **401** for auth failures.
- Use **404** when IDs are missing.
- Include a small JSON body `{ "message": "reason" }` if you want the extension to display the text.

## Sample backend

A reference FastAPI implementation lives at `server/remoteapi_fastapi`. It produces placeholder data with Picsum images and matches the OpenAPI document. Start it with `uv run fastapi dev main.py` and point the extension at `http://10.0.2.2:8000`.

## Adding new fields

The client ignores unknown JSON keys (Kotlinx serialization with `ignoreUnknownKeys`). Additive fields are safe; breaking changes should be reflected by bumping `version` in the capabilities response so clients can react if needed.
