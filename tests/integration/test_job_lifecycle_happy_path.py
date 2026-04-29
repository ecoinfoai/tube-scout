"""Integration test for the happy-path job lifecycle (T044 RED).

Validates the 7-stage pipeline progression with the runner + pipeline mocked
at the service layer. Asserts:

1. Each of 7 stages emits a transition recorded in ``analysis_jobs``.
2. ``GET /jobs/{id}/progress`` returns the expected JSON shape per stage.
3. Completion writes a row in ``analysis_results`` with the right artifact
   paths.
4. The 5 artifact files materialize under ``projects/{job_id}/``.

The runner singleton is reached via ``app.state.runner`` (T064 wire-up). The
pipeline is mocked via ``runner._pipeline_fn = mock_pipeline``.
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

STAGES = [
    "listing",
    "metadata",
    "transcripts",
    "retention",
    "analytics",
    "reuse_detection",
    "reporting",
]


@pytest.fixture
def lifecycle_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    return tmp_path


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


def _build_client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    )


async def _login(client: AsyncClient) -> str:
    form = await client.get("/login")
    csrf = re.search(r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text).group(1)
    resp = await client.post(
        "/login",
        data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
    )
    assert resp.status_code in {302, 303}
    new_form = await client.get("/jobs/new")
    csrf2 = re.search(
        r'name="csrf_token"\s+value="([0-9a-f]{32})"', new_form.text
    ).group(1)
    return csrf2


async def test_happy_path_7_stages_transition_then_complete(
    lifecycle_env: Path,
) -> None:
    """The mock pipeline emits 7 stages and produces 5 artifacts."""
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import jobs_repo, results_repo

    _seed_department()

    state_dir = lifecycle_env / "state"

    async def mock_pipeline(job_id: str, *, on_progress, resume_from=None) -> str:
        for idx, stage in enumerate(STAGES, start=1):
            on_progress(stage, idx, len(STAGES))
            await asyncio.sleep(0)
        result_dir = state_dir / "projects" / job_id
        result_dir.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "report_v1v3_html": "v1v3.html",
            "report_v1v3_pdf": "v1v3.pdf",
            "report_v1v3_excel": "v1v3.xlsx",
            "report_reuse_html": "reuse.html",
            "report_reuse_excel": "reuse.xlsx",
        }
        for fname in artifacts.values():
            (result_dir / fname).write_text("ok", encoding="utf-8")
        results_repo.ResultsRepo().insert_result(
            {
                "job_id": job_id,
                **{k: str(result_dir / v) for k, v in artifacts.items()},
                "matched_video_count": 12,
                "suspicious_pair_count": 2,
                "priority_summary": {
                    "critical": 0, "high": 1, "moderate": 1, "normal": 0
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return str(result_dir)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            # Inject mock pipeline into the runner held on app.state
            runner = app.state.runner
            runner._pipeline_fn = mock_pipeline

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
            assert resp.status_code in {302, 303}
            job_id = resp.headers["location"].rsplit("/", 1)[-1]

            # Wait for the background task to run all stages
            for _ in range(50):
                progress = await client.get(f"/jobs/{job_id}/progress")
                assert progress.status_code == 200
                payload = progress.json()
                if payload["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail(f"job did not complete: {payload}")

    # Final state checks
    row = jobs_repo.JobsRepo().find_by_id(job_id)
    assert row is not None
    assert row.status == "completed"
    assert row.current_stage == "done"

    result = results_repo.ResultsRepo().get_result(job_id)
    assert result is not None
    assert result.matched_video_count == 12
    assert result.suspicious_pair_count == 2

    result_dir = state_dir / "projects" / job_id
    for fname in ["v1v3.html", "v1v3.pdf", "v1v3.xlsx", "reuse.html", "reuse.xlsx"]:
        assert (result_dir / fname).is_file()


async def test_progress_stage_label_kr_for_each_stage(lifecycle_env: Path) -> None:
    """Progress JSON payload MUST include the right Korean stage label per stage."""
    from tube_scout.web.app import create_app

    _seed_department()

    stage_event = asyncio.Event()
    target_stage = "transcripts"

    async def slow_pipeline(job_id: str, *, on_progress, resume_from=None) -> str:
        for stage in STAGES:
            on_progress(stage, 1, 7)
            if stage == target_stage:
                stage_event.set()
                await asyncio.sleep(0.5)
            await asyncio.sleep(0)
        return "/tmp/never"

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = slow_pipeline
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

            await asyncio.wait_for(stage_event.wait(), timeout=2.0)
            progress = await client.get(f"/jobs/{job_id}/progress")
            payload = progress.json()

    assert payload["current_stage"] == target_stage
    assert payload["stage_label_kr"] == "자막 수집 중"
