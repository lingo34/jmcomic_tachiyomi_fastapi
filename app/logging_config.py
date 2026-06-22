"""Logging configuration.

The application is deliberately quiet: it never logs client IPs, request paths,
query strings, or upstream URLs at the default level, so logs cannot leak user
activity. HTTP-client libraries that would log request URLs are pinned to
WARNING to keep that guarantee even if pulled in transitively.
"""

from __future__ import annotations

import logging

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Third-party loggers that emit request URLs / targets at INFO or DEBUG.
_NOISY_LOGGERS = ("httpx", "httpx2", "httpcore", "httpcore2", "urllib3", "jmcomic")


def configure_logging(level: str) -> None:
    """Configure application logging at the given level.

    Adds a stream handler only when one is not already present (e.g. when running
    standalone), so it composes cleanly with uvicorn's own handlers.
    """
    resolved = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
    root.setLevel(resolved)
    logging.getLogger("app").setLevel(resolved)

    # Never let HTTP clients log request targets.
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Hard-disable the access logger so client IPs / paths can never be emitted —
    # regardless of how the app is launched (python -m app, uvicorn, gunicorn).
    # This is intentionally not configurable.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.disabled = True
    access_logger.propagate = False
