"""Liveness / health check endpoint (unauthenticated)."""

from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SettingsDep
from app.schemas import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(settings: SettingsDep) -> HealthResponse:
    """Return a cheap, dependency-free liveness signal for orchestrators."""
    return HealthResponse(status="ok", name=settings.app_name, version=settings.app_version)
