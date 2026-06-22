"""Capability discovery endpoint (unauthenticated)."""

from __future__ import annotations

from fastapi import APIRouter

from app.capabilities import build_capabilities
from app.dependencies import SettingsDep
from app.schemas import CapabilitiesResponse

router = APIRouter(prefix="/v1", tags=["meta"])


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    summary="Describe server capabilities and filters",
)
async def capabilities(settings: SettingsDep) -> CapabilitiesResponse:
    return build_capabilities(settings)
