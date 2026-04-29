"""Two simultaneous jobs on different departments (T045 RED).

Spec FR-029: separate per-department locks let two jobs progress in parallel.
Both must complete with separate ``result_dir`` and independent progress
streams.
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


def _seed(alias: str, env_prefix: str) -> None:
    from tube_scout.web.repo import db
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    db.bootstrap()
    DepartmentsRepo().add(
        {
            "alias": alias,
            "display_name": f"학과-{alias}",
            "channel_id_env": f"TUBE_SCOUT_CHANNEL_ID_{env_prefix}",
            "client_secret_env": f"TUBE_SCOUT_CLIENT_SECRET_{env_prefix}",
            "api_key_env": f"TUBE_SCOUT_API_KEY_{env_prefix}",
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


async def test_two_departments_run_concurrently(env: Path) -> None:
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import jobs_repo, results_repo

    _seed("physiology", "PHYS")
    _seed("nursing", "NURS")

    state_dir = env / "state"
    barriers: dict[str, asyncio.Event] = {
        "physiology": asyncio.Event(),
        "nursing": asyncio.Event(),
    }
    started_count: dict[str, int] = {"value": 0}
    overlap_event = asyncio.Event()

    async def parallel_pipeline(job_id: str, *, on_progress, resume_from=None) -> str:
        # Pull alias out of the job row to coordinate the two pipelines
        row = jobs_repo.JobsRepo().find_by_id(job_id)
        alias = row.department_alias
        on_progress("listing", 0, 1)
        started_count["value"] += 1
        if started_count["value"] >= 2:
            overlap_event.set()
        # Wait for both to be in-flight at the same time → proves no global lock
        await asyncio.wait_for(overlap_event.wait(), timeout=2.0)
        for stage in ["metadata", "transcripts", "retention", "analytics",
                      "reuse_detection", "reporting"]:
            on_progress(stage, 1, 1)
            await asyncio.sleep(0)
        result_dir = state_dir / "projects" / job_id
        result_dir.mkdir(parents=True, exist_ok=True)
        for fname in ["v1v3.html", "v1v3.pdf", "v1v3.xlsx", "reuse.html", "reuse.xlsx"]:
            (result_dir / fname).write_text("ok", encoding="utf-8")
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
        barriers[alias].set()
        return str(result_dir)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = parallel_pipeline
            csrf = await _login(client)

            async def submit(alias: str) -> str:
                resp = await client.post(
                    "/jobs",
                    data={
                        "department_alias": alias,
                        "professor_name": "홍길동",
                        "course_name": "과목",
                        "period_start": "2026-04-01",
                        "period_end": "2026-04-28",
                        "csrf_token": csrf,
                    },
                )
                assert resp.status_code in {302, 303}, resp.text
                return resp.headers["location"].rsplit("/", 1)[-1]

            phys_id = await submit("physiology")
            await asyncio.sleep(0.05)
            nurs_id = await submit("nursing")

            # Both must complete (proven by their pipeline barrier events)
            await asyncio.wait_for(barriers["physiology"].wait(), timeout=3.0)
            await asyncio.wait_for(barriers["nursing"].wait(), timeout=3.0)

            for _ in range(50):
                p = (await client.get(f"/jobs/{phys_id}/progress")).json()
                n = (await client.get(f"/jobs/{nurs_id}/progress")).json()
                if p["status"] == "completed" and n["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("jobs did not complete")

    repo = jobs_repo.JobsRepo()
    phys_row = repo.find_by_id(phys_id)
    nurs_row = repo.find_by_id(nurs_id)
    assert phys_row.status == "completed"
    assert nurs_row.status == "completed"
    assert (state_dir / "projects" / phys_id).is_dir()
    assert (state_dir / "projects" / nurs_id).is_dir()
    assert phys_id != nurs_id
