"""Contract tests for authentication routes (T038 RED).

Targets the routes defined in ``specs/008-admin-web-ui/contracts/http-routes.md``
``POST /login`` and ``POST /logout`` sections plus the ``GET /login`` form
render. All seven cases MUST fail until T052 (auth.py) lands and is wired in
T064. None of these tests instantiate the unimplemented routes directly —
they go through ``create_app()`` so the middleware stack is exercised end to
end.

Constitution I (TDD): every assertion encodes a single contract requirement
from http-routes.md POST /login section. Tests are intentionally minimal —
no implementation hints leaked into helpers.
"""

from __future__ import annotations

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

PASSWORD = "S3cret-Pass!"
USERNAME = "ops"


@pytest.fixture
def auth_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> str:
    """Configure agenix-style env vars for the admin web UI app factory.

    Returns:
        The bcrypt hash string injected as ``TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT``
        — exposed so individual tests can craft both correct and incorrect
        password submissions without re-hashing.
    """
    pw_hash = bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    return pw_hash


def _build_client(app) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
        headers={"X-Forwarded-Proto": "https"},
    )


async def _fetch_csrf_token(client: AsyncClient) -> str:
    """Pull a CSRF token from the rendered login form.

    The login template is required by spec to embed the CSRF token in either
    a hidden input named ``csrf_token`` or a ``<meta name="csrf-token">`` tag.
    Tests parse whichever is present so the implementation can choose.
    """
    resp = await client.get("/login")
    assert resp.status_code == 200, resp.text
    body = resp.text
    # accept either pattern; the implementation may use either
    import re

    match = re.search(
        r'name="csrf_token"\s+value="([0-9a-f]{32})"', body
    ) or re.search(r'name="csrf-token"\s+content="([0-9a-f]{32})"', body)
    assert match, "csrf token not found in login form"
    return match.group(1)


async def test_get_login_renders_form(auth_env: str) -> None:
    """GET /login MUST render a Korean HTML form (spec FR-001)."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/login")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "<form" in body
    assert 'name="username"' in body
    assert 'name="password"' in body
    assert 'name="csrf_token"' in body or 'name="csrf-token"' in body


async def test_post_login_success_sets_session_cookie(auth_env: str) -> None:
    """POST /login with valid creds MUST issue a signed session cookie."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _fetch_csrf_token(client)
            resp = await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": PASSWORD,
                    "csrf_token": csrf,
                },
            )
    assert resp.status_code in {302, 303}, resp.text
    cookie_header = resp.headers.get("set-cookie", "")
    assert "session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "SameSite=Lax" in cookie_header
    assert "Max-Age=28800" in cookie_header


async def test_post_login_invalid_credentials_shows_kr_message(auth_env: str) -> None:
    """Wrong password MUST render the form again with a Korean error."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _fetch_csrf_token(client)
            resp = await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": "WRONG",
                    "csrf_token": csrf,
                },
            )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "아이디 또는 비밀번호가 올바르지 않습니다." in resp.text
    assert "set-cookie" not in resp.headers or "session=" not in resp.headers["set-cookie"]


async def test_post_login_locks_after_5_failures(auth_env: str) -> None:
    """5 consecutive failures MUST trigger a lock (spec FR-004c)."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _fetch_csrf_token(client)
            for _ in range(5):
                await client.post(
                    "/login",
                    data={
                        "username": USERNAME,
                        "password": "WRONG",
                        "csrf_token": csrf,
                    },
                )
            # 6th attempt with correct password is rejected because lock active
            resp = await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": PASSWORD,
                    "csrf_token": csrf,
                },
            )
    assert resp.status_code == 403
    assert "로그인이 잠겼습니다" in resp.text


async def test_post_login_locked_returns_403_with_remaining_seconds(
    auth_env: str,
) -> None:
    """Locked state response MUST include remaining lock seconds."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _fetch_csrf_token(client)
            for _ in range(5):
                await client.post(
                    "/login",
                    data={
                        "username": USERNAME,
                        "password": "WRONG",
                        "csrf_token": csrf,
                    },
                )
            resp = await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": "WRONG",
                    "csrf_token": csrf,
                },
            )
    assert resp.status_code == 403
    import re

    match = re.search(r"(\d+)\s*초", resp.text)
    assert match, "remaining seconds not present in response"
    assert int(match.group(1)) > 0


async def test_post_login_missing_csrf_returns_400(auth_env: str) -> None:
    """POST without CSRF token MUST be rejected with 400 + Korean message."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/login",
                data={"username": USERNAME, "password": PASSWORD},
            )
    assert resp.status_code == 400
    assert "보안 토큰" in resp.text


async def test_post_logout_clears_cookie(auth_env: str) -> None:
    """POST /logout MUST clear the session cookie and 302 to /login."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _fetch_csrf_token(client)
            login_resp = await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": PASSWORD,
                    "csrf_token": csrf,
                },
            )
            assert login_resp.status_code in {302, 303}
            # logout — server must accept either CSRF in form or rely on cookie
            resp = await client.post(
                "/logout", data={"csrf_token": csrf}
            )
    assert resp.status_code in {302, 303}
    assert "/login" in resp.headers["location"]
    cookie_header = resp.headers.get("set-cookie", "")
    # Cookie cleared via Max-Age=0 or empty value
    assert "session=" in cookie_header
    assert "Max-Age=0" in cookie_header or 'session=""' in cookie_header or "session=;" in cookie_header
