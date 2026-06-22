"""Centralized exception handling.

Responses carry both ``detail`` (FastAPI convention) and ``message`` (what the
Kotlin Remote API client renders). Unexpected errors are logged server-side and
returned as a generic 500 so internal details never reach the client.
"""

from __future__ import annotations

import logging
import traceback
from typing import cast

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(StarletteHTTPException, exc)
    detail = http_exc.detail if isinstance(http_exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=http_exc.status_code,
        content={"detail": http_exc.detail, "message": detail},
        headers=getattr(http_exc, "headers", None),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the exception type and stack *frames* (file/line/function) for
    # diagnostics, but never the exception message/args, request path, query, or
    # IP — any of which could carry client-derived data.
    frames = "".join(traceback.format_tb(exc.__traceback__))
    logger.error("unhandled %s\n%s", type(exc).__name__, frames)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "message": "Internal server error"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
