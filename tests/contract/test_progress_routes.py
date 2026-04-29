"""Contract tests for the progress JSON route (T040 RED).

Targets ``GET /jobs/{id}/progress`` per
``specs/008-admin-web-ui/contracts/http-routes.md``. All 5 cases MUST fail
until T054 (jobs.py /progress JSON handler) lands and is wired in T064.

Spec FR-013 + FR-015 (no internal-path leakage in progress payloads).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

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


def _seed_job(*, status: str, current_stage: str | None, error_code: str | None = None,
              processed: int = 0, total: int = 0, job_id: str = "20260428-153022") -> str:
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
    repo.transition_to(
        job_id,
        status=status,
        current_stage=current_stage,
        error_code=error_code,
        error_detail="/home/kjeong/secrets/path leak attempt" if error_code else None,
    )
    if processed or total:
        repo.update_progress(job_id, processed_count=processed, total_count=total)
    return job_id


@pytest.fixture
def progress_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    _seed_department()


def _build_client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    )


async def _login(client: AsyncClient) -> None:
    form = await client.get("/login")
    csrf = re.search(r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text)
    assert csrf, "csrf token not found"
    resp = await client.post(
        "/login",
        data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf.group(1)},
    )
    assert resp.status_code in {302, 303}


async def test_progress_running_returns_processed_total(progress_env: None) -> None:
    from tube_scout.web.app import create_app

    job_id = _seed_job(
        status="running", current_stage="transcripts", processed=12, total=47
    )

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{job_id}/progress")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    payload = resp.json()
    assert payload["job_id"] == job_id
    assert payload["status"] == "running"
    assert payload["current_stage"] == "transcripts"
    assert payload["stage_label_kr"] == "자막 수집 중"
    assert payload["processed"] == 12
    assert payload["total"] == 47
    assert payload["error_code"] is None
    assert payload["error_message_kr"] is None


async def test_progress_completed_returns_done_stage(progress_env: None) -> None:
    from tube_scout.web.app import create_app

    job_id = _seed_job(status="completed", current_stage="done")

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{job_id}/progress")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "completed"
    assert payload["current_stage"] == "done"
    assert payload["stage_label_kr"] == "완료"


async def test_progress_failed_returns_kr_error_message(progress_env: None) -> None:
    from tube_scout.web.app import create_app

    job_id = _seed_job(
        status="failed", current_stage="transcripts", error_code="oauth_expired"
    )

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{job_id}/progress")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "failed"
    assert payload["error_code"] == "oauth_expired"
    assert payload["error_message_kr"]
    assert "인증이 만료" in payload["error_message_kr"]


async def test_progress_404_for_unknown_job(progress_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/jobs/19990101-000000/progress")
    assert resp.status_code == 404


async def test_progress_no_internal_paths_in_response(progress_env: None) -> None:
    """Spec FR-015: progress payloads MUST NOT leak filesystem paths or env names."""
    from tube_scout.web.app import create_app

    job_id = _seed_job(
        status="failed", current_stage="metadata", error_code="oauth_expired"
    )

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{job_id}/progress")
    assert resp.status_code == 200
    body = resp.text
    assert "/home/" not in body
    assert "/secrets/" not in body
    assert "TUBE_SCOUT_" not in body
    assert "agenix" not in body.lower()
