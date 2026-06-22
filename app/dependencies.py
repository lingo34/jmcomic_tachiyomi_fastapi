"""FastAPI dependencies: settings, service provider, and authentication."""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.service import JmcomicService

SettingsDep = Annotated[Settings, Depends(get_settings)]


@lru_cache(maxsize=1)
def _build_service() -> JmcomicService:
    settings = get_settings()
    return JmcomicService(settings, domain_list=settings.domain_list or None)


def get_service() -> JmcomicService:
    """Return the process-wide jmcomic service singleton."""
    return _build_service()


def require_api_key(request: Request, settings: SettingsDep) -> None:
    """Enforce the configured API key using a constant-time comparison."""
    if not settings.auth_enabled:
        return
    provided = request.headers.get(settings.api_header) or ""
    expected = settings.api_key or ""
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": settings.api_header},
        )


ServiceDep = Annotated[JmcomicService, Depends(get_service)]
ApiKeyGuard = Depends(require_api_key)
