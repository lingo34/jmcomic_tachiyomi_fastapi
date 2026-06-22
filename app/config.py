"""Application configuration.

All runtime configuration is read from the environment via ``pydantic-settings``.
Existing deployment variable names (``REMOTEAPI_*`` / ``JMCOMIC_*``) are preserved
through explicit validation aliases so this is a drop-in replacement for the old
``os.getenv`` based configuration.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(raw: str | None) -> list[str]:
    """Parse a comma-separated environment value into a clean list."""
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


class Settings(BaseSettings):
    """Strongly-typed application settings sourced from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    # --- API metadata -------------------------------------------------------
    app_name: str = "JMComic Remote API"
    app_version: str = "0.2.0"

    # --- Authentication -----------------------------------------------------
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REMOTEAPI_API_KEY", "api_key"),
        description="Optional API key. When set, every request must present it.",
    )
    api_header: str = Field(
        default="X-Api-Key",
        validation_alias=AliasChoices("REMOTEAPI_API_HEADER", "api_header"),
        description="Header name carrying the API key.",
    )

    # --- Pagination ---------------------------------------------------------
    default_page_size: int = Field(
        default=40,
        ge=1,
        le=200,
        validation_alias=AliasChoices("JMCOMIC_DEFAULT_PAGE_SIZE", "default_page_size"),
    )

    # --- jmcomic client -----------------------------------------------------
    jmcomic_impl: str = Field(default="api", validation_alias="JMCOMIC_IMPL")
    jmcomic_domain_list_raw: str | None = Field(
        default=None, validation_alias="JMCOMIC_DOMAIN_LIST"
    )
    jmcomic_image_domain: str | None = Field(default=None, validation_alias="JMCOMIC_IMAGE_DOMAIN")
    jmcomic_html_domain: str = Field(default="18comic.vip", validation_alias="JMCOMIC_HTML_DOMAIN")
    jmcomic_disable_log: bool = Field(default=True, validation_alias="JMCOMIC_DISABLE_LOG")
    jmcomic_image_referer: str | None = Field(
        default=None, validation_alias="JMCOMIC_IMAGE_REFERER"
    )
    jmcomic_ua: str | None = Field(default=None, validation_alias="JMCOMIC_UA")

    # --- HTTP / security ----------------------------------------------------
    docs_enabled: bool = Field(default=True, validation_alias="APP_DOCS_ENABLED")
    cors_allow_origins_raw: str | None = Field(
        default=None, validation_alias="APP_CORS_ALLOW_ORIGINS"
    )
    allowed_hosts_raw: str | None = Field(default=None, validation_alias="APP_ALLOWED_HOSTS")
    proxy_headers: bool = Field(default=True, validation_alias="APP_PROXY_HEADERS")
    forwarded_allow_ips: str = Field(
        default="127.0.0.1", validation_alias="APP_FORWARDED_ALLOW_IPS"
    )

    # --- Server / observability --------------------------------------------
    host: str = Field(default="0.0.0.0", validation_alias="APP_HOST")  # noqa: S104
    port: int = Field(default=8000, ge=1, le=65535, validation_alias="APP_PORT")
    log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")
    reload: bool = Field(default=False, validation_alias="APP_RELOAD")
    # NOTE: there is deliberately no "access log" setting. The application is
    # designed to never record client information, and that must not be togglable.

    # --- Resource limits (tuned for small, e.g. 256 MB, containers) ---------
    # Hard ceiling on decoded image size to bound memory and block decompression
    # bombs. A page at this cap costs ~3 bytes/pixel per in-memory copy.
    max_image_pixels: int = Field(
        default=20_000_000, ge=1_000_000, validation_alias="APP_MAX_IMAGE_PIXELS"
    )
    # Cap concurrent image decodes so peak memory stays bounded on tiny hosts.
    max_concurrent_images: int = Field(
        default=2, ge=1, le=64, validation_alias="APP_MAX_CONCURRENT_IMAGES"
    )

    # --- Derived values -----------------------------------------------------
    @property
    def domain_list(self) -> list[str]:
        return _split_csv(self.jmcomic_domain_list_raw)

    @property
    def cors_allow_origins(self) -> list[str]:
        return _split_csv(self.cors_allow_origins_raw)

    @property
    def allowed_hosts(self) -> list[str]:
        hosts = _split_csv(self.allowed_hosts_raw)
        return hosts or ["*"]

    @property
    def auth_enabled(self) -> bool:
        return self.api_key is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, process-wide settings instance."""
    return Settings()
