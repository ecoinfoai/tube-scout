"""T098 — every 4xx user-facing response carries a Korean message.

Spec FR-015 + ADR-007: HTML form 4xx responses must surface a Korean
message; JSON 4xx must include ``error_message_kr`` + ``error_code``.
English stack traces / internal detail strings appear only in log
output, never in the HTTP body.
"""

from __future__ import annotations

import re
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


HANGUL = re.compile(r"[가-힣]")


def _assert_korean(text: str, label: str) -> None:
    assert HANGUL.search(text), f"{label}: response carries no Korean text"


def _assert_no_traceback(text: str, label: str) -> None:
    assert "Traceback" not in text, f"{label}: leaks Python traceback"
    assert ".py:" not in text or "static" in text, (
        f"{label}: leaks .py:line marker"
    )


async def _login(client: AsyncClient) -> str:
    form = await client.get("/login")
    csrf = re.search(r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text).group(1)
    await client.post(
        "/login",
        data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
    )
    new_form = await client.get("/jobs/new")
    return re.search(
        r'name="csrf_token"\s+value="([0-9a-f]{32})"', new_form.text
    ).group(1)


async def test_login_400_missing_csrf_is_korean(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/login",
                data={"username": USERNAME, "password": PASSWORD},
            )
    assert resp.status_code == 400
    _assert_korean(resp.text, "POST /login no-csrf")
    _assert_no_traceback(resp.text, "POST /login no-csrf")


async def test_login_200_bad_credentials_is_korean(env: Path) -> None:
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
            resp = await client.post(
                "/login",
                data={"username": USERNAME, "password": "WRONG", "csrf_token": csrf},
            )
    assert resp.status_code == 200
    _assert_korean(resp.text, "POST /login wrong-pw")


async def test_jobs_400_unknown_dept_is_korean(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login(client)
            resp = await client.post(
                "/jobs",
                data={
                    "department_alias": "no-such-dept",
                    "professor_name": "홍길동",
                    "course_name": "과목",
                    "period_start": "2026-04-01",
                    "period_end": "2026-04-28",
                    "csrf_token": csrf,
                },
            )
    assert resp.status_code == 200
    _assert_korean(resp.text, "POST /jobs unknown-dept")
    _assert_no_traceback(resp.text, "POST /jobs unknown-dept")


async def test_jobs_progress_404_json_has_kr_field(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/jobs/19990101-000000/progress")
    assert resp.status_code == 404
    payload = resp.json()
    assert "error_code" in payload
    assert "error_message_kr" in payload
    _assert_korean(payload["error_message_kr"], "GET /jobs/.../progress 404 JSON")


async def test_files_404_unknown_kind_is_korean(env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/jobs/19990101-000000/files/unknown-kind")
    assert resp.status_code == 404
    _assert_korean(resp.text, "GET /jobs/.../files/unknown")
