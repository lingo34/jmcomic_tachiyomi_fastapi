# JMComic Remote API server

FastAPI backend that proxies the JMComic mobile API into the Remote API contract used by the Kotlin `remoteapi` extension. All series, chapters, and page URLs come from the `jmcomic` Python library (API/mobile mode).

## Quick start

```bash
cd server/jmcomic_fastapi
uv sync --group dev
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Using Docker (Python 3.13 + uv):

```bash
docker compose -f docker-compose.yml up --build
```

Open http://127.0.0.1:8000/docs to inspect the live schema. The extension default base URL is `http://10.0.2.2:8000` (Android emulator loopback).

## Configuration

Environment variables:

- `REMOTEAPI_API_KEY` — optional token. If set, every request must include the header defined below.
- `REMOTEAPI_API_HEADER` — header name to read the token from. Defaults to `X-Api-Key`.
- `JMCOMIC_IMPL` — client implementation passed to `JmOption.new_jm_client`, defaults to `api`.
- `JMCOMIC_DOMAIN_LIST` — comma-separated override for jmcomic API domains.
- `JMCOMIC_IMAGE_DOMAIN` — override the CDN domain used to build cover image URLs.
- `JMCOMIC_HTML_DOMAIN` — domain used when returning the manga detail URL (default `18comic.vip`).
- `JMCOMIC_DISABLE_LOG` — disable jmcomic's verbose logging (defaults to `true`).

The `GET /v1/capabilities` response mirrors the auth header so the Kotlin client knows which header to send.

## Contract

The API matches the OpenAPI document at `./docs/remote-api-openapi.yaml` and the Kotlin client in `src/all/remoteapi`. Features can be toggled per capability; unsupported routes return HTTP 501.

## Development

```bash
uv sync --group dev
uv run ruff check .
uv run mypy .
uv run pytest
```
