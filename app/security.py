"""Security middleware: hardening response headers."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Strict policy for the JSON/image API surface. The interactive docs are served
# from a CDN and are exempted below so Swagger UI keeps working when enabled.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; img-src 'self' data:"

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "X-Permitted-Cross-Domain-Policies": "none",
}

_DOCS_PREFIXES = ("/docs", "/redoc")
_DOCS_PATHS = frozenset({"/openapi.json"})


def _is_docs_path(path: str) -> bool:
    return path in _DOCS_PATHS or path.startswith(_DOCS_PREFIXES)


class SecurityHeadersMiddleware:
    """Add hardening headers and strip the server fingerprint on every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in _BASE_HEADERS.items():
                    headers[key] = value
                if not _is_docs_path(path):
                    headers["Content-Security-Policy"] = _API_CSP
                # Reduce server fingerprinting.
                del headers["server"]
            await send(message)

        await self.app(scope, receive, send_with_headers)
