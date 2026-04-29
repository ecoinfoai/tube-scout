"""Integration test for Starlette app boot (T019 RED).

Validates that ``create_app()`` builds a Starlette application with all
middlewares wired and that ``/healthz`` responds 200 ``ok``. This is the
Phase 2 Foundational checkpoint.

Targets ``tube_scout.web.app.create_app`` — implementation pending (T036/T037).
"""

from __future__ import annotations

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def boot_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", "ops")
    pw_hash = bcrypt.hashpw(b"S3cret!", bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))


async def test_create_app_returns_starlette_instance(boot_env: None) -> None:
    from starlette.applications import Starlette

    from tube_scout.web.app import create_app

    app = create_app()
    assert isinstance(app, Starlette)


async def test_healthz_returns_ok_text(boot_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.text.strip() == "ok"
    assert resp.headers["content-type"].startswith("text/plain")


async def test_security_headers_present_on_healthz(boot_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get(
                "/healthz", headers={"X-Forwarded-Proto": "https"}
            )
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("referrer-policy") == "same-origin"
    assert "max-age" in resp.headers.get("strict-transport-security", "")


async def test_unauthenticated_request_redirects_to_login(boot_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get(
                "/jobs/new", headers={"X-Forwarded-Proto": "https"}
            )
    assert resp.status_code in {302, 303}
    assert "/login" in resp.headers["location"]


async def test_lifespan_fails_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from tube_scout.web.app import create_app

    monkeypatch.delenv("TUBE_SCOUT_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", raising=False)
    monkeypatch.delenv("TUBE_SCOUT_SESSION_SECRET", raising=False)

    app = create_app()
    with pytest.raises(Exception):
        async with app.router.lifespan_context(app):
            pass


async def test_app_boot_fails_when_password_bcrypt_is_empty_string(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """ADV-US1-77 (adversary informational): empty string is treated as missing.

    A vault entry that's been wiped to ``""`` (rather than fully unset)
    must still trigger ``MissingEnvError`` so the operator gets a clear
    boot failure instead of a silently-broken auth path.
    """
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", "ops")
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", "")
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))

    from tube_scout.web.app import MissingEnvError, create_app

    app = create_app()
    with pytest.raises(MissingEnvError, match="TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT"):
        async with app.router.lifespan_context(app):
            pass
