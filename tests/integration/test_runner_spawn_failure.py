"""Runner.spawn failure recovery (ADV-US2-21).

When ``runner.spawn`` raises (e.g. RunRimeError because pipeline_fn was
not wired), the inserted ``pending`` job MUST be transitioned to
``failed`` with ``error_code=pipeline.runner_unavailable`` so the operator
gets a Korean error and the row does not stick around as a stuck pending
forever.

Constitution II Fail-Fast: silent log-only swallow is rejected — the
state machine MUST visibly mark the failure.
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


async def test_post_jobs_marks_failed_when_spawn_raises(env: Path) -> None:
    """ADV-US2-21: spawn failure on POST /jobs MUST flip job to failed.

    The inserted pending row would otherwise stick forever as the
    background task never starts.
    """
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import jobs_repo

    def boom_spawn(*args, **kwargs):
        raise RuntimeError("simulated runner unavailable")

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner.spawn = boom_spawn
            csrf = await _login_and_csrf(client)
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
    assert resp.status_code in {302, 303}, resp.text
    new_id = resp.headers["location"].rsplit("/", 1)[-1]

    row = jobs_repo.JobsRepo().find_by_id(new_id)
    assert row is not None
    assert row.status == "failed", (
        f"spawn failure must flip job to failed; got status={row.status!r}"
    )
    assert row.error_code == "pipeline.runner_unavailable"


async def test_post_retry_marks_failed_when_spawn_raises(env: Path) -> None:
    """ADV-US2-21: same guarantee for the retry path."""
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import jobs_repo

    repo = jobs_repo.JobsRepo()
    failed_id = "20260429-130000"
    repo.insert_pending(
        {
            "job_id": failed_id,
            "department_alias": DEPT_ALIAS,
            "professor_name": "홍길동",
            "course_name": "해부생리학",
            "period_start": "2026-04-01",
            "period_end": "2026-04-28",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "created_by": USERNAME,
        }
    )
    repo.transition_to(failed_id, status="failed", current_stage="metadata")

    def boom_spawn(*args, **kwargs):
        raise RuntimeError("simulated runner unavailable")

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner.spawn = boom_spawn
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{failed_id}/retry", data={"csrf_token": csrf}
            )
    assert resp.status_code in {302, 303}, resp.text
    new_id = resp.headers["location"].rsplit("/", 1)[-1]

    row = repo.find_by_id(new_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error_code == "pipeline.runner_unavailable"
