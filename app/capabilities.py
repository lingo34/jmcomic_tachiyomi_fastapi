"""Static capability description and feature gating."""

from __future__ import annotations

from fastapi import HTTPException, status
from jmcomic import JmMagicConstants

from app.config import Settings
from app.schemas import (
    AuthSpec,
    CapabilitiesResponse,
    DefaultValues,
    FilterDefinition,
    FilterOption,
    SupportFlags,
)

SUPPORT_FLAGS = SupportFlags()

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

TAG_FILTER = FilterDefinition(key="tag", label="Tag", type="text", default=None)

FILTERS: list[FilterDefinition] = [CATEGORY_FILTER, TIME_FILTER, SORT_FILTER, TAG_FILTER]


def build_capabilities(settings: Settings) -> CapabilitiesResponse:
    """Render the capabilities document for the given settings."""
    return CapabilitiesResponse(
        name=settings.app_name,
        version=settings.app_version,
        supports=SUPPORT_FLAGS,
        auth=AuthSpec(header=settings.api_header),
        defaults=DefaultValues(page_size=settings.default_page_size),
        filters=FILTERS,
    )


def ensure(feature: str) -> None:
    """Raise 501 if a capability flag is disabled, 500 if it is unknown."""
    flag_value = getattr(SUPPORT_FLAGS, feature, None)
    if not isinstance(flag_value, bool):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Support flag '{feature}' is invalid",
        )
    if not flag_value:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Feature '{feature}' is disabled by server",
        )
