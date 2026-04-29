"""Two simultaneous jobs on the same department alias (T046 RED).

Spec FR-028: a second submission for an already-running alias must be
rejected with HTTP 409 + the Korean message
``동일 학과 분석이 이미 진행 중입니다 — 잠시 후 다시 시도하세요.``
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

USERNAME = "ops"
PASSWORD = "S3cret-Pass!"
DEPT_ALIAS = "physiology"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _seed() -> None:
    from tube_scout.web.repo import db
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    db.bootstrap()
    DepartmentsRepo().add(
        {
            "alias": DEPT_ALIAS,
            "display_name": "물리치료학과",
            "channel_id_env": "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "client_secret_env": "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "api_key_env": "TUBE_SCOUT_API_KEY_PHYS",
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _build_client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
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


async def test_second_submission_rejected_with_409(env: Path) -> None:
    from tube_scout.web.app import create_app

    _seed()

    busy = asyncio.Event()
    release = asyncio.Event()

    async def slow_pipeline(job_id: str, *, on_progress, resume_from=None) -> str:
        on_progress("listing", 0, 1)
        busy.set()
        await release.wait()
        return "/tmp/never"

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = slow_pipeline
            csrf = await _login(client)

            payload = {
                "department_alias": DEPT_ALIAS,
                "professor_name": "홍길동",
                "course_name": "해부생리학",
                "period_start": "2026-04-01",
                "period_end": "2026-04-28",
                "csrf_token": csrf,
            }
            first = await client.post("/jobs", data=payload)
            assert first.status_code in {302, 303}

            await asyncio.wait_for(busy.wait(), timeout=2.0)

            second = await client.post("/jobs", data=payload)
            assert second.status_code == 409
            assert (
                "동일 학과 분석이 이미 진행 중입니다 — 잠시 후 다시 시도하세요."
                in second.text
            )

            release.set()
