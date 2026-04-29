"""End-to-end login flow integration test (T043 RED).

Validates the full login round-trip via ``create_app()``:

1. Browser GET /login → 200 form with CSRF token.
2. POST /login with valid creds → 302 to ``next`` URL + signed Set-Cookie.
3. Authenticated request to a protected route succeeds.
4. POST /logout → 302 to /login + cleared cookie.
5. Re-fetch protected route → 302 to /login.

All assertions intentionally treat the cookie as opaque — only the signer in
``app.state.session_signer`` may decode it. This guards against accidentally
leaking the secret into the test, and exercises the bcrypt verification +
signing round-trip end-to-end (Constitution III/VI).
"""

from __future__ import annotations

import re

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

USERNAME = "ops"
PASSWORD = "S3cret-Pass!"


@pytest.fixture
def login_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)


def _build_client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    )


async def test_full_login_round_trip_with_bcrypt(login_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            # Hit a protected route first → 302 with ?next=...
            unauthed = await client.get("/jobs/new")
            assert unauthed.status_code in {302, 303}
            assert "next=%2Fjobs%2Fnew" in unauthed.headers["location"]

            # GET /login renders the form
            form = await client.get("/login?next=/jobs/new")
            assert form.status_code == 200
            csrf_match = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text
            )
            assert csrf_match
            csrf = csrf_match.group(1)

            # POST /login → redirect to next URL with signed cookie
            login_resp = await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": PASSWORD,
                    "csrf_token": csrf,
                    "next": "/jobs/new",
                },
            )
            assert login_resp.status_code in {302, 303}
            assert login_resp.headers["location"] == "/jobs/new"
            cookie = login_resp.headers["set-cookie"]
            assert "session=" in cookie
            assert "HttpOnly" in cookie
            assert "Secure" in cookie

            # Authenticated request to protected route succeeds (200)
            authed = await client.get("/jobs/new")
            assert authed.status_code == 200

            # POST /logout → 302 + cleared cookie
            logout = await client.post("/logout", data={"csrf_token": csrf})
            assert logout.status_code in {302, 303}
            assert "/login" in logout.headers["location"]
            cleared = logout.headers["set-cookie"]
            assert "Max-Age=0" in cleared or 'session=""' in cleared or "session=;" in cleared

            # Re-access protected route → 302 to /login (session invalidated)
            re_access = await client.get("/jobs/new")
            assert re_access.status_code in {302, 303}
            assert "/login" in re_access.headers["location"]


async def test_login_with_wrong_password_does_not_issue_cookie(login_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            form = await client.get("/login")
            csrf = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text
            ).group(1)
            resp = await client.post(
                "/login",
                data={"username": USERNAME, "password": "WRONG", "csrf_token": csrf},
            )
    assert resp.status_code == 200
    assert "session=" not in resp.headers.get("set-cookie", "")
    assert "아이디 또는 비밀번호가 올바르지 않습니다." in resp.text


async def test_login_redirects_to_jobs_new_when_no_next_param(login_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            form = await client.get("/login")
            csrf = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text
            ).group(1)
            resp = await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": PASSWORD,
                    "csrf_token": csrf,
                },
            )
    assert resp.status_code in {302, 303}
    assert resp.headers["location"] == "/jobs/new"


async def test_login_open_redirect_protection(login_env: None) -> None:
    """Spec FR-002 hardening: ``next`` must be relative or rejected."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            form = await client.get("/login")
            csrf = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text
            ).group(1)
            resp = await client.post(
                "/login",
                data={
                    "username": USERNAME,
                    "password": PASSWORD,
                    "csrf_token": csrf,
                    "next": "https://evil.example.com/steal",
                },
            )
    assert resp.status_code in {302, 303}
    location = resp.headers["location"]
    # External redirect MUST be rejected — fall back to /jobs/new
    assert location.startswith("/")
    assert "evil.example.com" not in location
