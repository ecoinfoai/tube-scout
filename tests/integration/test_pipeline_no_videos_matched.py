"""Pipeline empty-result handling (T049 RED).

Spec FR-007e: when filtering yields zero matched videos, the job still
completes (status=completed), but the result page must render the message
``조건에 맞는 영상이 없습니다.`` and MUST NOT show empty file links that
would 404 on click.
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


async def test_no_videos_matched_completes_with_message(env: Path) -> None:
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import results_repo

    _seed()
    state_dir = env / "state"

    async def empty_pipeline(job_id: str, *, on_progress, resume_from=None) -> str:
        for stage in [
            "listing",
            "metadata",
            "transcripts",
            "retention",
            "analytics",
            "reuse_detection",
            "reporting",
        ]:
            on_progress(stage, 0, 0)
        result_dir = state_dir / "projects" / job_id
        result_dir.mkdir(parents=True, exist_ok=True)
        results_repo.ResultsRepo().insert_result(
            {
                "job_id": job_id,
                "report_v1v3_html": None,
                "report_v1v3_pdf": None,
                "report_v1v3_excel": None,
                "report_reuse_html": None,
                "report_reuse_excel": None,
                "matched_video_count": 0,
                "suspicious_pair_count": 0,
                "priority_summary": {
                    "critical": 0,
                    "high": 0,
                    "moderate": 0,
                    "normal": 0,
                },
                "generated_at": datetime.now(UTC).isoformat(),
            }
        )
        return str(result_dir)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = empty_pipeline
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
                if payload["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("job did not complete")

            result_page = await client.get(f"/jobs/{job_id}/results")

    assert result_page.status_code == 200
    body = result_page.text
    assert "조건에 맞는 영상이 없습니다" in body
    # No download links for missing artifacts
    for kind in ["v1v3-html", "v1v3-pdf", "v1v3-excel", "reuse-html", "reuse-excel"]:
        assert f"/jobs/{job_id}/files/{kind}" not in body, f"unexpected link: {kind}"
