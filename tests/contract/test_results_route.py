"""Contract tests for the results page + job-id router (T042 RED).

Targets ``GET /jobs/{job_id}/results`` (HTML) and ``GET /jobs/{job_id}``
(branch-by-status redirector) per
``specs/008-admin-web-ui/contracts/http-routes.md``.

3 cases MUST fail until T053 + T055 (jobs.py + results.py) lands and is wired
in T064.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
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
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


def _seed_completed(state_dir: Path, job_id: str = "20260428-150000") -> str:
    from tube_scout.web.repo import jobs_repo, results_repo

    jr = jobs_repo.JobsRepo()
    jr.insert_pending(
        {
            "job_id": job_id,
            "department_alias": DEPT_ALIAS,
            "professor_name": "홍길동",
            "course_name": "해부생리학",
            "period_start": "2026-04-01",
            "period_end": "2026-04-28",
            "started_at": datetime.now(UTC).isoformat(),
            "created_by": USERNAME,
        }
    )
    jr.transition_to(job_id, status="running", current_stage="listing")
    jr.transition_to(job_id, status="completed", current_stage="done")
    result_dir = state_dir / "projects" / job_id
    result_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, fname in [
        ("report_v1v3_html", "v1v3.html"),
        ("report_v1v3_pdf", "v1v3.pdf"),
        ("report_v1v3_excel", "v1v3.xlsx"),
        ("report_reuse_html", "reuse.html"),
        ("report_reuse_excel", "reuse.xlsx"),
    ]:
        (result_dir / fname).write_text("ok", encoding="utf-8")
        paths[key] = str(result_dir / fname)
    results_repo.ResultsRepo().insert_result(
        {
            "job_id": job_id,
            **paths,
            "matched_video_count": 5,
            "suspicious_pair_count": 1,
            "priority_summary": {
                "critical": 0,
                "high": 1,
                "moderate": 0,
                "normal": 0,
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }
    )
    return job_id


def _seed_running(job_id: str = "20260428-160000") -> str:
    from tube_scout.web.repo import jobs_repo

    jr = jobs_repo.JobsRepo()
    jr.insert_pending(
        {
            "job_id": job_id,
            "department_alias": DEPT_ALIAS,
            "professor_name": "홍길동",
            "course_name": "해부생리학",
            "period_start": "2026-04-01",
            "period_end": "2026-04-28",
            "started_at": datetime.now(UTC).isoformat(),
            "created_by": USERNAME,
        }
    )
    jr.transition_to(job_id, status="running", current_stage="listing")
    return job_id


@pytest.fixture
def results_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    _seed_department()
    return tmp_path / "state"


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


async def test_get_jobs_id_results_renders_all_5_download_links(
    results_env: Path,
) -> None:
    from tube_scout.web.app import create_app

    job_id = _seed_completed(results_env)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{job_id}/results")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    for kind in ["v1v3-html", "v1v3-pdf", "v1v3-excel", "reuse-html", "reuse-excel"]:
        assert f"/jobs/{job_id}/files/{kind}" in body, f"missing link: {kind}"


async def test_get_jobs_id_redirects_to_progress_when_running(
    results_env: Path,
) -> None:
    from tube_scout.web.app import create_app

    job_id = _seed_running()

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.text
    # Running job → progress page (not result page)
    assert "/jobs/" in body
    assert "/progress" in body or "영상 목록 수집 중" in body or "current_stage" in body


async def test_get_jobs_id_redirects_to_results_when_completed(
    results_env: Path,
) -> None:
    from tube_scout.web.app import create_app

    job_id = _seed_completed(results_env, job_id="20260428-170000")

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{job_id}")
    # Either renders results inline or 302→/jobs/{id}/results
    if resp.status_code in {302, 303}:
        assert resp.headers["location"].endswith(f"/jobs/{job_id}/results")
    else:
        assert resp.status_code == 200
        assert f"/jobs/{job_id}/files/" in resp.text
