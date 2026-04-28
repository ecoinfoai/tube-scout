"""Session expiry: 8h window enforced (T050 RED).

Spec FR-004a: a session cookie older than ``SESSION_MAX_AGE_SECONDS`` (8h)
MUST be rejected by ``AuthRequiredMiddleware``, redirecting to ``/login``.

The test fabricates a cookie with an artificially-aged ``last_active`` to
avoid sleeping for 8h. Since we cannot reach into the running app's signer
to forge a stale cookie *and* keep the same secret, we simulate by signing a
payload with the same env-injected secret.
"""

from __future__ import annotations

import re

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

USERNAME = "ops"
PASSWORD = "S3cret-Pass!"
SECRET = "x" * 32


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", SECRET)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)


def _build_client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
        headers={"X-Forwarded-Proto": "https"},
    )


async def test_expired_session_redirects_to_login(env: None) -> None:
    """A cookie aged past 8h MUST be rejected — middleware redirects to login."""
    from tube_scout.web.app import create_app
    from tube_scout.web.middleware.session import (
        SESSION_MAX_AGE_SECONDS,
        SessionSigner,
    )

    # Build a cookie that the middleware will deserialize but reject as expired
    signer = SessionSigner(secret=SECRET)
    stale_payload = {
        "username": USERNAME,
        "issued_at": 1_000_000_000,
        "last_active": 1_000_000_000,  # epoch 2001 — definitely > 8h ago
        "csrf_token": "0" * 32,
    }
    stale_cookie = signer.sign(stale_payload)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            client.cookies.set("session", stale_cookie)
            resp = await client.get("/jobs/new")
    assert resp.status_code in {302, 303}
    assert "/login" in resp.headers["location"]
    # Don't leak the stale cookie further — middleware should not preserve it
    assert SESSION_MAX_AGE_SECONDS == 28800


async def test_fresh_session_passes(env: None) -> None:
    """Fresh login (current epoch) MUST be accepted by the middleware."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            form = await client.get("/login")
            csrf = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text
            ).group(1)
            await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": PASSWORD,
                    "csrf_token": csrf,
                },
            )
            resp = await client.get("/jobs/new")
    assert resp.status_code == 200
