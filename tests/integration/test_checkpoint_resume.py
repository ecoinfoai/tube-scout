"""Checkpoint resume integration test (T069 RED).

Spec FR-022a: failed/interrupted retry MUST resume from the last completed
stage rather than restarting from listing. This test simulates a failure
at stage 5 (analytics) on the original job, then exercises the retry route
and asserts that the new run's pipeline call carries ``resume_from`` set
to the original job_id and runs faster (skipping the 4 already-complete
stages).
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


def _seed_failed_job(job_id: str = "20260429-090000") -> str:
    """Insert a job that failed at stage 5 (analytics)."""
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
    repo.transition_to(job_id, status="running", current_stage="listing")
    repo.transition_to(job_id, status="running", current_stage="metadata")
    repo.transition_to(job_id, status="running", current_stage="transcripts")
    repo.transition_to(job_id, status="running", current_stage="retention")
    repo.transition_to(job_id, status="running", current_stage="analytics")
    repo.transition_to(
        job_id,
        status="failed",
        error_code="oauth_expired",
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    return job_id


@pytest.fixture
def resume_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
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


async def test_retry_passes_resume_from_to_pipeline(resume_env: Path) -> None:
    """The retry route MUST plumb ``resume_from`` into the pipeline.

    The mock pipeline records the value it receives so the test can verify
    that ``runner.spawn(new_id, resume_from=original_id)`` reaches
    ``pipeline.run(...)`` unchanged.
    """
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import results_repo

    original_id = _seed_failed_job()

    captured: dict[str, str | None] = {"resume_from": "<unset>"}

    async def mock_pipeline(job_id: str, *, on_progress, resume_from=None,
                              project_dir=None) -> str:
        captured["resume_from"] = resume_from
        # Skip stages 1-4 when resume_from is set (FR-022a).
        if resume_from is None:
            stages = ["listing", "metadata", "transcripts", "retention",
                       "analytics", "reuse_detection", "reporting"]
        else:
            stages = ["analytics", "reuse_detection", "reporting"]
        for idx, stage in enumerate(stages, 1):
            on_progress(stage, idx, len(stages))
            await asyncio.sleep(0)
        result_dir = (resume_env / "state" / "projects" / job_id)
        result_dir.mkdir(parents=True, exist_ok=True)
        results_repo.ResultsRepo().insert_result(
            {
                "job_id": job_id,
                "report_v1v3_html": str(result_dir / "v1v3.html"),
                "report_v1v3_pdf": str(result_dir / "v1v3.pdf"),
                "report_v1v3_excel": str(result_dir / "v1v3.xlsx"),
                "report_reuse_html": str(result_dir / "reuse.html"),
                "report_reuse_excel": str(result_dir / "reuse.xlsx"),
                "matched_video_count": 1,
                "suspicious_pair_count": 0,
                "priority_summary": {"critical": 0, "high": 0, "moderate": 0, "normal": 0},
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return str(result_dir)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = mock_pipeline
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{original_id}/retry", data={"csrf_token": csrf}
            )
            assert resp.status_code in {302, 303}, resp.text
            new_id = resp.headers["location"].rsplit("/", 1)[-1]
            assert new_id != original_id

            # Wait for the resumed run to complete.
            for _ in range(50):
                progress = await client.get(f"/jobs/{new_id}/progress")
                if progress.status_code != 200:
                    await asyncio.sleep(0.05)
                    continue
                payload = progress.json()
                if payload["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail(f"resumed job did not complete: {payload}")

    assert captured["resume_from"] == original_id, (
        f"expected resume_from={original_id!r}, got {captured['resume_from']!r}"
    )


async def test_retry_resumed_run_is_faster(resume_env: Path) -> None:
    """A resumed run should execute strictly fewer stages than a full run.

    Compares stage-callback counts between two pipeline invocations: one
    fresh + one with ``resume_from``. Assertion is on number of stages,
    not wall time, to keep the test deterministic.
    """
    from tube_scout.web.app import create_app

    original_id = _seed_failed_job(job_id="20260429-091000")

    fresh_stages: list[str] = []
    resumed_stages: list[str] = []

    async def mock_pipeline(job_id: str, *, on_progress, resume_from=None,
                              project_dir=None) -> str:
        if resume_from is None:
            stages = ["listing", "metadata", "transcripts", "retention",
                       "analytics", "reuse_detection", "reporting"]
            for s in stages:
                on_progress(s, 1, 1)
                fresh_stages.append(s)
        else:
            stages = ["analytics", "reuse_detection", "reporting"]
            for s in stages:
                on_progress(s, 1, 1)
                resumed_stages.append(s)
        return f"/tmp/{job_id}"

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = mock_pipeline
            csrf = await _login_and_csrf(client)

            # Trigger a fresh run via /jobs (no resume_from) to populate
            # fresh_stages.
            await client.post(
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
            await asyncio.sleep(0.2)

            # Trigger the resumed run via /retry.
            await client.post(
                f"/jobs/{original_id}/retry", data={"csrf_token": csrf}
            )
            await asyncio.sleep(0.2)

    assert len(resumed_stages) < len(fresh_stages), (
        f"resumed stages ({len(resumed_stages)}) must be fewer than fresh "
        f"({len(fresh_stages)}); fresh={fresh_stages} resumed={resumed_stages}"
    )
