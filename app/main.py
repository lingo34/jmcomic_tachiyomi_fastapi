"""Application factory for the JMComic Remote API server."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.routes import health, manga, meta, reader
from app.security import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "starting %s v%s (auth=%s, docs=%s)",
        settings.app_name,
        settings.app_version,
        settings.auth_enabled,
        settings.docs_enabled,
    )
    yield
    logger.info("shutting down %s", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="Adapts the JMComic mobile API to the Tachiyomi Remote API contract.",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings

    # Middleware (added inner-to-outer; SecurityHeaders ends up outermost).
    if settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET"],
            allow_headers=["*"],
        )
    app.add_middleware(SecurityHeadersMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(manga.router)
    app.include_router(reader.router)

    return app


app = create_app()
