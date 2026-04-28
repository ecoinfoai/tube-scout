"""Health check route (T037).

GET /healthz → 200 text/plain ``ok``. No authentication, no logging — used
by the reverse-proxy / systemd watchdog as a liveness probe.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import PlainTextResponse


async def healthz(_request: Request) -> PlainTextResponse:
    """Return 200 ``ok`` for liveness probes.

    Args:
        _request: Starlette request (unused).

    Returns:
        :class:`PlainTextResponse` with body ``"ok"``.
    """
    return PlainTextResponse("ok", status_code=200)
