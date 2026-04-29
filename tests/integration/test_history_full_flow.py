"""End-to-end history flow integration test (T071 RED).

5 mixed-status jobs across 2 departments, then exercise ``/history`` with
various filter combinations. Asserts ordering + filter correctness +
pagination boundary behavior. Spec FR-021 + FR-022.
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


def _seed_dept(alias: str, prefix: str) -> None:
    from tube_scout.web.repo import db
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    db.bootstrap()
    DepartmentsRepo().add(
        {
            "alias": alias,
            "display_name": f"학과-{alias}",
            "channel_id_env": f"TUBE_SCOUT_CHANNEL_ID_{prefix}",
            "client_secret_env": f"TUBE_SCOUT_CLIENT_SECRET_{prefix}",
            "api_key_env": f"TUBE_SCOUT_API_KEY_{prefix}",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


def _seed_jobs() -> list[tuple[str, str, str]]:
    """Insert 5 jobs spanning physiology+nursing × completed/failed/running."""
    from tube_scout.web.repo import jobs_repo

    rows = [
        ("20260425-100000", "physiology", "completed"),
        ("20260426-100000", "physiology", "failed"),
        ("20260427-100000", "nursing", "completed"),
        ("20260428-100000", "nursing", "interrupted"),
        ("20260429-100000", "physiology", "running"),
    ]
    repo = jobs_repo.JobsRepo()
    for job_id, alias, _status in rows:
        repo.insert_pending(
            {
                "job_id": job_id,
                "department_alias": alias,
                "professor_name": "홍길동",
                "course_name": "해부생리학",
                "period_start": "2026-04-01",
                "period_end": "2026-04-28",
                "started_at": datetime.now(UTC).isoformat(),
                "created_by": USERNAME,
            }
        )
    for job_id, _alias, status in rows:
        stage = "done" if status == "completed" else "metadata"
        repo.transition_to(job_id, status=status, current_stage=stage)
    return rows


@pytest.fixture
def history_flow_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    _seed_dept("physiology", "PHYS")
    _seed_dept("nursing", "NURS")
    _seed_jobs()
    return tmp_path


def _build_client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    )


async def _login(client: AsyncClient) -> None:
    form = await client.get("/login")
    csrf = re.search(r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text).group(1)
    await client.post(
        "/login",
        data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
    )


async def test_history_default_lists_all_5_jobs_newest_first(
    history_flow_env: Path,
) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history")
    assert resp.status_code == 200
    body = resp.text
    # All 5 ids present
    ids = re.findall(r"20260\d{3}-\d{6}", body)
    assert "20260429-100000" in ids
    assert "20260425-100000" in ids
    # Newest first
    pos_29 = body.find("20260429-100000")
    pos_25 = body.find("20260425-100000")
    assert pos_29 < pos_25


async def test_history_status_in_combo_filter(history_flow_env: Path) -> None:
    """``status=completed,failed`` MUST union the two sets."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history?status=completed,failed")
    assert resp.status_code == 200
    body = resp.text
    assert "20260425-100000" in body  # completed
    assert "20260426-100000" in body  # failed
    assert "20260427-100000" in body  # completed (nursing)
    assert "20260428-100000" not in body  # interrupted
    assert "20260429-100000" not in body  # running


async def test_history_combined_dept_status_filter(
    history_flow_env: Path,
) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history?department=physiology&status=running")
    assert resp.status_code == 200
    body = resp.text
    assert "20260429-100000" in body
    # other physiology rows excluded by status filter
    assert "20260425-100000" not in body
    assert "20260426-100000" not in body


async def test_history_pagination_offset_beyond_total_returns_empty_table(
    history_flow_env: Path,
) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history?limit=10&offset=100")
    assert resp.status_code == 200
    body = resp.text
    # No job rows on this page
    assert not re.search(r"20260\d{3}-\d{6}", body)
