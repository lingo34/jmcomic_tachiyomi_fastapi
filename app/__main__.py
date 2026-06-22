"""Console entrypoint: ``python -m app``.

Runs uvicorn with configuration sourced from the environment so the same command
works in development (``APP_RELOAD=true``) and in the hardened container image.
"""

from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        proxy_headers=settings.proxy_headers,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        server_header=False,
        date_header=False,
        # Access logging is hard-disabled (not configurable): the app must never
        # record client IPs, paths, or any request-identifying information.
        access_log=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
