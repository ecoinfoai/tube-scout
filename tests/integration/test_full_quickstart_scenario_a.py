"""T099 — full quickstart Scenario A end-to-end (Polish phase).

Automates the operator's golden path:

1. Login.
2. Submit a new analysis job from /jobs/new.
3. Poll /jobs/{id}/progress until status=completed.
4. Render /jobs/{id}/results.
5. Download all 5 artifact kinds (v1v3-html/pdf/excel + reuse-html/excel).
6. Assert each download is non-empty and matches the expected MIME.

The pipeline is mocked so the test runs without YouTube credentials.
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
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
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
    return tmp_path


EXPECTED_MIME = {
    "v1v3-html": "text/html",
    "v1v3-pdf": "application/pdf",
    "v1v3-excel": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "reuse-html": "text/html",
    "reuse-excel": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
}


async def test_quickstart_scenario_a_end_to_end(env: Path) -> None:
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import results_repo

    state_dir = env / "state"

    async def mock_pipeline(
        job_id: str, *, on_progress, resume_from=None, project_dir=None
    ) -> str:
        for stage in [
            "listing",
            "metadata",
            "transcripts",
            "retention",
            "analytics",
            "reuse_detection",
            "reporting",
        ]:
            on_progress(stage, 1, 1)
            await asyncio.sleep(0)
        result_dir = state_dir / "projects" / job_id
        result_dir.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "report_v1v3_html": result_dir / "v1v3.html",
            "report_v1v3_pdf": result_dir / "v1v3.pdf",
            "report_v1v3_excel": result_dir / "v1v3.xlsx",
            "report_reuse_html": result_dir / "reuse.html",
            "report_reuse_excel": result_dir / "reuse.xlsx",
        }
        for path in artifacts.values():
            path.write_bytes(b"<artifact bytes>" * 20)
        results_repo.ResultsRepo().insert_result(
            {
                "job_id": job_id,
                **{k: str(v) for k, v in artifacts.items()},
                "matched_video_count": 7,
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
        return str(result_dir)

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            app.state.runner._pipeline_fn = mock_pipeline

            # 1. Login
            form = await client.get("/login")
            csrf = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text
            ).group(1)
            login_resp = await client.post(
                "/login",
                data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
            )
            assert login_resp.status_code in {302, 303}

            # 2. Submit a new analysis job
            new_form = await client.get("/jobs/new")
            assert new_form.status_code == 200
            job_csrf = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', new_form.text
            ).group(1)
            submit = await client.post(
                "/jobs",
                data={
                    "department_alias": DEPT_ALIAS,
                    "professor_name": "홍길동",
                    "course_name": "해부생리학",
                    "period_start": "2026-04-01",
                    "period_end": "2026-04-28",
                    "csrf_token": job_csrf,
                },
            )
            assert submit.status_code in {302, 303}
            job_id = submit.headers["location"].rsplit("/", 1)[-1]

            # 3. Poll progress until completed
            payload = None
            for _ in range(50):
                progress = await client.get(f"/jobs/{job_id}/progress")
                assert progress.status_code == 200
                payload = progress.json()
                if payload["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail(f"job did not complete: {payload}")

            # 4. Render results page
            results = await client.get(f"/jobs/{job_id}/results")
            assert results.status_code == 200
            for kind in EXPECTED_MIME:
                assert f"/jobs/{job_id}/files/{kind}" in results.text

            # 5+6. Download each artifact and assert MIME + non-empty
            for kind, expected_mime in EXPECTED_MIME.items():
                resp = await client.get(f"/jobs/{job_id}/files/{kind}")
                assert resp.status_code == 200, f"{kind}: {resp.status_code}"
                content_type = resp.headers["content-type"]
                assert content_type.startswith(expected_mime), (
                    f"{kind}: expected {expected_mime}, got {content_type}"
                )
                assert resp.content, f"{kind}: empty body"
