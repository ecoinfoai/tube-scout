"""T096 — security headers across every response (Polish phase).

Spec http-routes.md cross-cutting: every response MUST carry
``Strict-Transport-Security``, ``X-Content-Type-Options: nosniff``,
``Referrer-Policy: same-origin`` regardless of route, status, or method.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

USERNAME = "ops"
PASSWORD = "S3cret-Pass!"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    from tube_scout.web.repo import db
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    db.bootstrap()
    DepartmentsRepo().add(
        {
            "alias": "physiology",
            "display_name": "물리치료학과",
            "channel_id_env": "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "client_secret_env": "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "api_key_env": "TUBE_SCOUT_API_KEY_PHYS",
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return tmp_path


REQUIRED_HEADERS = {
    "strict-transport-security",
    "x-content-type-options",
    "referrer-policy",
}


def _assert_headers(response, label: str) -> None:
    for key in REQUIRED_HEADERS:
        assert key in response.headers, f"{label}: missing {key} header"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "max-age" in response.headers["strict-transport-security"]


async def test_healthz_carries_security_headers(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/healthz")
    assert resp.status_code == 200
    _assert_headers(resp, "/healthz")


async def test_login_form_carries_security_headers(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/login")
    assert resp.status_code == 200
    _assert_headers(resp, "GET /login")


async def test_unauthenticated_redirect_carries_security_headers(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/jobs/new")
    assert resp.status_code in {302, 303}
    _assert_headers(resp, "redirect /jobs/new")


async def test_404_for_unknown_route_carries_security_headers(env: Path) -> None:
    """Authenticated 404 must still carry security headers.

    Unauthenticated requests get 302 → /login (which is also covered),
    so we authenticate first to exercise the actual 404 branch.
    """
    import re

    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            form = await client.get("/login")
            csrf = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text
            ).group(1)
            await client.post(
                "/login",
                data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
            )
            resp = await client.get("/this-route-does-not-exist-zzz")
    assert resp.status_code == 404
    _assert_headers(resp, "404 unknown route")
