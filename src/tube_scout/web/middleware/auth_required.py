"""Auth-required middleware (T029).

Redirects unauthenticated requests to ``/login?next=<path>`` (spec FR-002).
The login page itself, ``/healthz``, and any path under ``/static`` are
allowlisted so unauthenticated browsers can render the login form.

The signer instance is read from ``request.app.state.session_signer`` so
T036 can issue a single :class:`SessionSigner` from agenix-injected env at
lifespan startup (pair-programmer T027 review note).
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp

from tube_scout.web.middleware.session import (
    SessionExpired,
    SessionSigner,
    SessionTampered,
)

ALLOWLIST_PREFIXES: tuple[str, ...] = ("/login", "/healthz", "/static")
SESSION_COOKIE_NAME = "session"


class AuthRequiredMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that enforces a verified session cookie.

    Responses:
        - 302 to ``/login?next=<encoded-path>`` for unauthenticated requests.
        - Pass-through for allowlisted prefixes.
        - Pass-through with ``request.state.session = VerifiedSession`` for
          authenticated requests.
    """

    def __init__(self, app: ASGIApp, *, signer: SessionSigner | None = None) -> None:
        super().__init__(app)
        self._signer = signer

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in ALLOWLIST_PREFIXES):
            return await call_next(request)
        signer = self._signer or getattr(request.app.state, "session_signer", None)
        if signer is None:
            # Fail-Fast: app misconfigured — no signer available.
            return _redirect_to_login(path)
        cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if not cookie:
            return _redirect_to_login(path)
        try:
            verified = signer.verify(cookie, now=int(time.time()))
        except (SessionTampered, SessionExpired):
            return _redirect_to_login(path)
        request.state.session = verified
        return await call_next(request)


def _redirect_to_login(next_path: str) -> RedirectResponse:
    query = urlencode({"next": next_path})
    return RedirectResponse(url=f"/login?{query}", status_code=302)
