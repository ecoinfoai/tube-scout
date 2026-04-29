"""T097 — sweep responses for secret leakage (SC-006).

Spec SC-006 + http-routes.md cross-cutting: no response body OR header
may include env-var names (``TUBE_SCOUT_*``), token strings (``ya29.``,
``1//``), filesystem paths (``~/.config/tube-scout/``, ``/home/``), or
``agenix`` references.

The sweep covers GET routes that don't require POST input (login form,
healthz, /jobs/new redirect, history, error pages). POST endpoints are
covered by the per-endpoint contract tests.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
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
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )
    return tmp_path


LEAK_PATTERNS = [
    re.compile(r"TUBE_SCOUT_[A-Z_]+"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"1//[A-Za-z0-9_-]+"),
    re.compile(r"~/\.config/tube-scout"),
    re.compile(r"/home/[a-z0-9._-]+/", re.IGNORECASE),
    re.compile(r"agenix", re.IGNORECASE),
]


def _assert_no_leak(text: str, label: str) -> None:
    for pattern in LEAK_PATTERNS:
        match = pattern.search(text)
        assert match is None, (
            f"{label}: leak pattern {pattern.pattern!r} matched: {match.group(0)!r}"
        )


async def _login(client: AsyncClient) -> None:
    form = await client.get("/login")
    csrf = re.search(r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text).group(1)
    await client.post(
        "/login",
        data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
    )


async def test_no_leak_in_login_form(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/login")
    _assert_no_leak(resp.text, "GET /login body")
    _assert_no_leak(str(dict(resp.headers)), "GET /login headers")


async def test_no_leak_in_healthz(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/healthz")
    _assert_no_leak(resp.text, "GET /healthz body")


async def test_no_leak_in_jobs_new(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/jobs/new")
    _assert_no_leak(resp.text, "GET /jobs/new body")


async def test_no_leak_in_history(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history")
    _assert_no_leak(resp.text, "GET /history body")


async def test_no_leak_in_404(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/no-such-route")
    _assert_no_leak(resp.text, "GET unknown body")


async def test_no_leak_in_error_messages_dict() -> None:
    """The KR error message catalogue itself must not embed leak patterns."""
    from tube_scout.web import errors

    for code, message in errors.USER_MESSAGES.items():
        _assert_no_leak(message, f"errors.USER_MESSAGES[{code!r}]")
