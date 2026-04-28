"""HTTPS redirect middleware (T051 RED).

Spec http-routes.md cross-cutting: HTTP requests without
``X-Forwarded-Proto: https`` MUST be answered with a 308 redirect to the
HTTPS scheme. The reverse proxy is expected to set the header for legitimate
TLS-terminated traffic.
"""

from __future__ import annotations

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    pw_hash = bcrypt.hashpw(b"x", bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", "ops")
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)


async def test_http_request_without_xfp_redirects_308_to_https(env: None) -> None:
    """Non-allowlisted paths over HTTP MUST be 308 → HTTPS.

    ``/healthz`` is allowlisted for reverse-proxy probes, so use ``/login``
    here to exercise the redirect path (login is unauthenticated but still
    must be served over HTTPS in production).
    """
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/login")
    assert resp.status_code == 308
    location = resp.headers["location"]
    assert location.startswith("https://")
    assert location.endswith("/login")


async def test_http_request_with_xfp_https_passes(env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
        headers={"X-Forwarded-Proto": "https"},
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.text.strip() == "ok"
