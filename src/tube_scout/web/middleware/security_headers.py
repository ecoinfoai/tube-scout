"""Security headers middleware (T030).

Adds the cross-cutting security headers required by http-routes.md to every
response:

- ``Strict-Transport-Security: max-age=31536000; includeSubDomains``
- ``X-Content-Type-Options: nosniff``
- ``Referrer-Policy: same-origin``
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


HSTS_MAX_AGE_SECONDS = 31_536_000  # 365 days


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that injects HSTS / nosniff / Referrer-Policy."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        response.headers.setdefault(
            "strict-transport-security",
            f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains",
        )
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "same-origin")
        return response
