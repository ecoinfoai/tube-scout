"""Pipeline failure: YouTube Data API quotaExceeded (T048 RED).

Spec FR-014: a 403 quotaExceeded response from the API MUST flip the job to
``status=failed`` with ``error_code=quota_exceeded`` and the Korean message
``API 일일 할당량을 초과했습니다. ...``.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
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
            "registered_at": datetime.now(UTC).isoformat(),
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


async def test_quota_exceeded_marks_job_failed(env: Path) -> None:
    from tube_scout.web.app import create_app
    from tube_scout.web.jobs.runner import PipelineError

    _seed()

    async def failing_pipeline(job_id: str, *, on_progress, resume_from=None) -> str:
        on_progress("listing", 0, 0)
        raise PipelineError(
            code="pipeline.quota_exceeded",
            detail="HTTP 403 quotaExceeded — youtube.googleapis.com",
        )

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = failing_pipeline
            csrf = await _login(client)
            resp = await client.post(
                "/jobs",
                data={
                    "department_alias": DEPT_ALIAS,
                    "professor_name": "홍길동",
                    "course_name": "해부생리학",
                    "period_start": "2026-04-01",
                    "period_end": "2026-04-28",
                    "csrf_token": csrf,
                },
            )
            job_id = resp.headers["location"].rsplit("/", 1)[-1]

            for _ in range(50):
                payload = (await client.get(f"/jobs/{job_id}/progress")).json()
                if payload["status"] == "failed":
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("job did not fail")

    assert payload["error_code"] in {"quota_exceeded", "pipeline.quota_exceeded"}
    assert "API 일일 할당량을 초과했습니다." in payload["error_message_kr"]
