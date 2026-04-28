"""HTTPS redirect middleware (T031).

Forces all traffic onto HTTPS unless the upstream reverse proxy has set
``X-Forwarded-Proto: https`` (operations deployment), or the configured
host already uses HTTPS at the ASGI scope level.

Allowlists ``/healthz`` so reverse-proxy health probes succeed over HTTP.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp


HEALTH_PATH = "/healthz"


class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    """308 redirect HTTP requests to HTTPS unless a forwarded-proto override
    indicates the request already came in over TLS at the proxy layer."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path == HEALTH_PATH:
            return await call_next(request)
        if request.url.scheme == "https":
            return await call_next(request)
        forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
        if forwarded_proto == "https":
            return await call_next(request)
        secure_url = request.url.replace(scheme="https")
        return RedirectResponse(url=str(secure_url), status_code=308)
