"""Contract tests for the retry endpoint (T067 RED).

Targets ``POST /jobs/{job_id}/retry`` per ``contracts/http-routes.md``. 4
cases MUST fail until T073 (retry route) lands. Spec FR-022a.
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
DEPT_ALIAS = "physiology"


def _seed_department() -> None:
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


def _seed_job(*, status: str, job_id: str, stage: str | None = None) -> None:
    from tube_scout.web.repo import jobs_repo

    repo = jobs_repo.JobsRepo()
    repo.insert_pending(
        {
            "job_id": job_id,
            "department_alias": DEPT_ALIAS,
            "professor_name": "홍길동",
            "course_name": "해부생리학",
            "period_start": "2026-04-01",
            "period_end": "2026-04-28",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "created_by": USERNAME,
        }
    )
    if status != "pending":
        repo.transition_to(job_id, status=status, current_stage=stage)


@pytest.fixture
def retry_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    _seed_department()
    return tmp_path


def _build_client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    )


async def _login_and_csrf(client: AsyncClient) -> str:
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


async def test_retry_failed_job_creates_new_job_id(retry_env: Path) -> None:
    from tube_scout.web.app import create_app

    failed_id = "20260428-100000"
    _seed_job(status="failed", job_id=failed_id, stage="transcripts")

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{failed_id}/retry", data={"csrf_token": csrf}
            )
    assert resp.status_code in {302, 303}, resp.text
    location = resp.headers["location"]
    new_id = location.rsplit("/", 1)[-1]
    assert re.fullmatch(r"\d{8}-\d{6}(-\d+)?", new_id)
    assert new_id != failed_id


async def test_retry_completed_job_rejected_409(retry_env: Path) -> None:
    from tube_scout.web.app import create_app

    completed_id = "20260428-110000"
    _seed_job(status="completed", job_id=completed_id, stage="done")

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{completed_id}/retry", data={"csrf_token": csrf}
            )
    assert resp.status_code == 409
    assert "재실행할 수 없는 상태입니다." in resp.text


async def test_retry_interrupted_job_succeeds(retry_env: Path) -> None:
    from tube_scout.web.app import create_app

    interrupted_id = "20260428-120000"
    _seed_job(status="interrupted", job_id=interrupted_id, stage="metadata")

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{interrupted_id}/retry", data={"csrf_token": csrf}
            )
    assert resp.status_code in {302, 303}


async def test_retry_missing_csrf_rejected(retry_env: Path) -> None:
    from tube_scout.web.app import create_app

    failed_id = "20260428-130000"
    _seed_job(status="failed", job_id=failed_id, stage="transcripts")

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login_and_csrf(client)
            resp = await client.post(f"/jobs/{failed_id}/retry", data={})
    assert resp.status_code == 400
    assert "보안 토큰" in resp.text
