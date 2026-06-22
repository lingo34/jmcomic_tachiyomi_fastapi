# JMComic Remote API server

FastAPI backend that adapts the JMComic mobile API to the [Remote API contract](docs/remote-api.md)
used by the Kotlin `remoteapi` Tachiyomi/Mihon extension. All series, chapters, and
page data come from the [`jmcomic`](https://pypi.org/project/jmcomic/) Python library
(API / mobile mode).

## Architecture

```
app/
├── main.py            # application factory + lifespan + middleware wiring
├── __main__.py        # `python -m app` entrypoint (uvicorn runner)
├── config.py          # typed settings (pydantic-settings, env-driven)
├── schemas.py         # Pydantic response models (Remote API contract)
├── capabilities.py    # capability document + feature gating
├── dependencies.py    # DI: settings, service singleton, API-key auth
├── service.py         # JmcomicService — talks to jmcomic, decodes images
├── security.py        # security-headers middleware
├── errors.py          # sanitized exception handlers
├── logging_config.py  # logging setup
└── routes/
    ├── health.py      # GET /health (liveness, unauthenticated)
    ├── meta.py        # GET /v1/capabilities (unauthenticated)
    ├── manga.py       # popular / latest / search / details / chapters
    └── reader.py      # page list + decoded page image
```

## Quick start

```bash
uv sync --group dev
uv run python -m app          # honours APP_* env vars (reload, host, port…)
# or, classic uvicorn invocation:
uv run uvicorn app.main:app --reload
```

With Docker:

```bash
docker compose up --build
```

When docs are enabled (`APP_DOCS_ENABLED=true`, the default outside compose), open
<http://127.0.0.1:8000/docs> for the live schema. The extension default base URL is
`http://10.0.2.2:8000` (Android emulator loopback).

## Endpoints

| Method & path                                   | Auth | Purpose                       |
| ----------------------------------------------- | ---- | ----------------------------- |
| `GET /health`                                   | no   | Liveness probe                |
| `GET /v1/capabilities`                          | no   | Feature flags, filters, auth  |
| `GET /v1/manga/popular`                         | yes* | Popular / browse list         |
| `GET /v1/manga/latest`                          | yes* | Latest list                   |
| `GET /v1/manga/search`                          | yes* | Search with filters           |
| `GET /v1/manga/{manga_id}`                      | yes* | Manga details + chapters      |
| `GET /v1/manga/{manga_id}/chapters`             | yes* | Paginated chapter list        |
| `GET /v1/chapters/{chapter_id}/pages`           | yes* | Page list                     |
| `GET /v1/chapters/{chapter_id}/pages/{i}/image` | yes* | Decoded page image bytes      |

\* Authentication is enforced only when `REMOTEAPI_API_KEY` is set.

## Configuration

All settings are read from the environment (see [`.env.example`](.env.example)).

| Variable                  | Default       | Description                                                  |
| ------------------------- | ------------- | ------------------------------------------------------------ |
| `REMOTEAPI_API_KEY`       | _(unset)_     | API key. When set, all data routes require it.               |
| `REMOTEAPI_API_HEADER`    | `X-Api-Key`   | Header carrying the API key.                                 |
| `JMCOMIC_IMPL`            | `api`         | jmcomic client implementation.                              |
| `JMCOMIC_DOMAIN_LIST`     | _(unset)_     | Comma-separated jmcomic API domain overrides.               |
| `JMCOMIC_IMAGE_DOMAIN`    | _(unset)_     | CDN domain for cover image URLs.                            |
| `JMCOMIC_HTML_DOMAIN`     | `18comic.vip` | Domain used for manga detail URLs.                          |
| `JMCOMIC_DISABLE_LOG`     | `true`        | Disable jmcomic's verbose logging.                         |
| `JMCOMIC_IMAGE_REFERER`   | _(unset)_     | Override `Referer` for direct-CDN image headers.            |
| `JMCOMIC_UA`              | _(unset)_     | Override `User-Agent` for direct-CDN image headers.        |
| `JMCOMIC_DEFAULT_PAGE_SIZE` | `40`        | Default page size when clients omit `page_size`.            |
| `APP_DOCS_ENABLED`        | `true`        | Serve `/docs`, `/redoc`, `/openapi.json`.                  |
| `APP_ALLOWED_HOSTS`       | `*`           | Comma-separated Host allow-list (`*` disables checking).    |
| `APP_CORS_ALLOW_ORIGINS`  | _(unset)_     | Comma-separated CORS origins (empty disables CORS).        |
| `APP_PROXY_HEADERS`       | `true`        | Honour `X-Forwarded-*` from trusted proxies.               |
| `APP_FORWARDED_ALLOW_IPS` | `127.0.0.1`   | Proxy IPs allowed to set forwarded headers.                |
| `APP_HOST` / `APP_PORT`   | `0.0.0.0` / `8000` | Bind address / port.                                  |
| `APP_LOG_LEVEL`           | `INFO`        | Log level.                                                  |
| `APP_RELOAD`              | `false`       | Auto-reload (development only).                             |
| `APP_MAX_IMAGE_PIXELS`    | `20000000`    | Max decoded image size; bounds memory / blocks bombs.      |
| `APP_MAX_CONCURRENT_IMAGES` | `2`         | Max simultaneous image decodes.                            |

## Security

- **Auth** — optional API key, compared in constant time (`secrets.compare_digest`).
- **No information leakage** — upstream jmcomic errors are logged server-side and
  returned to clients as a generic `502`; unhandled errors return a generic `500`.
- **No client logging, by design** — there is no access-log toggle anywhere.
  The uvicorn access logger is hard-disabled in code; the runner forces
  `access_log=False`; HTTP-client loggers are silenced; and error logs record
  only exception *types* and stack frames — never exception messages, request
  paths, query strings, upstream URLs, or client IPs. The compose log driver is
  bounded and ephemeral (use `driver: none` for zero on-disk logs).
- **Hardening headers** on every response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a strict
  `Content-Security-Policy` for the API surface, and the `Server` header stripped.
- **Host / CORS / proxy** controls are configurable and locked down by default.
- **Docs** can be disabled in production (`APP_DOCS_ENABLED=false`; the compose
  file defaults it off).
- **Container** runs as a non-root user, read-only root filesystem, all Linux
  capabilities dropped, `no-new-privileges`, a hard `mem_limit`, and no swap.
  The only writable path is a small in-RAM `tmpfs` that is wiped on restart, so
  the container persists nothing. If the upstream client ever needs to persist
  state, relax `read_only` in `docker-compose.yml`.
- **Supply chain** — pinned `uv` and base image, lockfile-driven installs,
  Dependabot updates, CodeQL scanning, and provenance + SBOM attestations on
  published images.

## Running on a small (256 MB) host

The default compose file targets a 256 MB container:

- **Hard memory ceiling** — `mem_limit: 256m` with swap disabled (`memswap_limit`
  equal to the limit) so the app is killed predictably rather than thrashing.
- **Bounded image memory** — the dominant cost is image decoding. Peak usage is
  roughly `pixels × 3 bytes` per in-memory copy, times a few copies. With
  `APP_MAX_IMAGE_PIXELS=20000000` (~20 MP) and `APP_MAX_CONCURRENT_IMAGES=2`,
  decode memory stays in the low-hundreds of MB worst case; lower these if you
  see OOM kills, raise them on bigger hosts.
- **Single worker** — `python -m app` runs one uvicorn worker; don't add workers
  on a memory-constrained host (each is a full interpreter).

**Do I need a ramdisk?** No. The container already runs effectively "in RAM":
the root filesystem is mounted read-only (no writes ever hit disk) and the only
writable path is a small `tmpfs` (RAM) that is wiped on restart. The read-only
image layers are served from the kernel page cache on demand. Copying the whole
image onto a `tmpfs` would be counter-productive at 256 MB — the Python runtime
plus dependencies are larger than the RAM budget, so the filesystem itself would
exhaust memory and leave nothing for the app. Keep the read-only-root + `tmpfs`
layout and rely on the page cache.

## Development

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run ty check       # Astral's type checker
uv run pytest
```

## Contract

The API matches [`docs/remote-api-openapi.yaml`](docs/remote-api-openapi.yaml) and the
Kotlin client in `src/all/remoteapi`. Capabilities can be toggled per feature;
disabled routes return HTTP 501. Error bodies include both `detail` and `message`.
