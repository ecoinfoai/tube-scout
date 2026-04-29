"""Review persistence across runs (T070 RED).

Spec FR-020 + SC-009: a pair marked ``false_positive`` (or
``confirmed_duplicate``) in run 1 MUST NOT resurface in run 2's reuse
detection alerts. The web pipeline reads
``reviews_repo.list_resolved_pair_ids()`` before invoking the reuse
detection stage so the stage can filter the alerts list.

This test uses two jobs, posts a review between them, and confirms the
second run's pipeline receives the resolved pair as an excluded id.
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


def _seed_completed_job_with_pair(
    *, job_id: str, pair_id: str
) -> None:
    from tube_scout.web.repo import jobs_repo, results_repo, reviews_repo

    jr = jobs_repo.JobsRepo()
    jr.insert_pending(
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
    jr.transition_to(job_id, status="completed", current_stage="done")
    results_repo.ResultsRepo().insert_result(
        {
            "job_id": job_id,
            "report_v1v3_html": None,
            "report_v1v3_pdf": None,
            "report_v1v3_excel": None,
            "report_reuse_html": None,
            "report_reuse_excel": None,
            "matched_video_count": 1,
            "suspicious_pair_count": 1,
            "priority_summary": {"critical": 0, "high": 1, "moderate": 0, "normal": 0},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    reviews_repo.ReviewsRepo().upsert_review(
        pair_id=pair_id,
        job_id=job_id,
        status="unreviewed",
        updated_by=None,
        note=None,
    )


@pytest.fixture
def review_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
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


async def test_false_positive_pair_excluded_from_next_run(
    review_env: Path,
) -> None:
    from tube_scout.web.app import create_app

    pair_id = "pair-physreuse-001"
    run1_id = "20260429-080000"
    _seed_completed_job_with_pair(job_id=run1_id, pair_id=pair_id)

    captured_excluded: list[list[str]] = []

    async def mock_pipeline(job_id: str, *, on_progress, resume_from=None,
                              project_dir=None) -> str:
        # The pipeline reads list_resolved_pair_ids before reuse_detection
        # — capture what it sees on each invocation.
        from tube_scout.web.repo import reviews_repo

        captured_excluded.append(
            list(reviews_repo.ReviewsRepo().list_resolved_pair_ids())
        )
        for stage in ["listing", "metadata", "transcripts", "retention",
                       "analytics", "reuse_detection", "reporting"]:
            on_progress(stage, 1, 1)
            await asyncio.sleep(0)
        return f"/tmp/{job_id}"

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = mock_pipeline
            csrf = await _login_and_csrf(client)

            # 1. Mark the pair as false_positive.
            review_resp = await client.post(
                f"/jobs/{run1_id}/reviews/{pair_id}",
                data={"status": "false_positive", "csrf_token": csrf},
            )
            assert review_resp.status_code in {302, 303}, review_resp.text

            # 2. Start a new analysis — pipeline must see the excluded pair.
            run2_resp = await client.post(
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
            assert run2_resp.status_code in {302, 303}, run2_resp.text
            run2_id = run2_resp.headers["location"].rsplit("/", 1)[-1]

            # Wait for the new run to invoke the pipeline.
            for _ in range(50):
                if captured_excluded:
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("pipeline mock was never invoked for run2")

    assert pair_id in captured_excluded[-1], (
        f"pair {pair_id!r} not excluded on run2; captured={captured_excluded}"
    )


async def test_confirmed_duplicate_pair_also_excluded(
    review_env: Path,
) -> None:
    """A pair marked ``confirmed_duplicate`` is also excluded next run."""
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import reviews_repo

    pair_id = "pair-physreuse-002"
    run1_id = "20260429-081000"
    _seed_completed_job_with_pair(job_id=run1_id, pair_id=pair_id)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = lambda *a, **k: asyncio.sleep(0)
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{run1_id}/reviews/{pair_id}",
                data={"status": "confirmed_duplicate", "csrf_token": csrf},
            )
            assert resp.status_code in {302, 303}, resp.text

    resolved = reviews_repo.ReviewsRepo().list_resolved_pair_ids()
    assert pair_id in resolved
