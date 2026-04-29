"""Contract tests for the history page (T066 RED).

Targets ``GET /history`` per ``contracts/http-routes.md``. 6 cases MUST fail
until T072 (history.py) lands and is wired in T080. Spec FR-021 + FR-022.
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


def _seed_department(alias: str = DEPT_ALIAS, prefix: str = "PHYS") -> None:
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
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _seed_jobs() -> list[str]:
    """Insert 6 jobs across statuses + 2 departments + 2 days."""
    from tube_scout.web.repo import jobs_repo

    repo = jobs_repo.JobsRepo()
    rows = [
        ("20260427-100000", "physiology", "completed", "done"),
        ("20260427-110000", "physiology", "failed", "transcripts"),
        ("20260428-090000", "nursing", "completed", "done"),
        ("20260428-100000", "nursing", "interrupted", "metadata"),
        ("20260428-110000", "physiology", "running", "analytics"),
        ("20260428-120000", "physiology", "pending", None),
    ]
    for job_id, alias, _status, _stage in rows:
        repo.insert_pending(
            {
                "job_id": job_id,
                "department_alias": alias,
                "professor_name": "홍길동",
                "course_name": "해부생리학",
                "period_start": "2026-04-01",
                "period_end": "2026-04-28",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "created_by": USERNAME,
            }
        )
    for job_id, _alias, status, stage in rows:
        if status == "pending":
            continue
        repo.transition_to(job_id, status=status, current_stage=stage)
    return [r[0] for r in rows]


@pytest.fixture
def history_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    _seed_department("physiology", "PHYS")
    _seed_department("nursing", "NURS")
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
    resp = await client.post(
        "/login",
        data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
    )
    assert resp.status_code in {302, 303}


async def test_history_lists_jobs_newest_first(history_env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history")
    assert resp.status_code == 200
    body = resp.text
    # newest first
    pos_apr28 = body.find("20260428-120000")
    pos_apr27 = body.find("20260427-100000")
    assert pos_apr28 != -1 and pos_apr27 != -1
    assert pos_apr28 < pos_apr27


async def test_history_filters_by_status(history_env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history?status=failed")
    assert resp.status_code == 200
    body = resp.text
    assert "20260427-110000" in body  # failed
    assert "20260427-100000" not in body  # completed must be filtered out


async def test_history_filters_by_department(history_env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history?department=nursing")
    assert resp.status_code == 200
    body = resp.text
    assert "20260428-090000" in body
    assert "20260427-100000" not in body  # physiology excluded


async def test_history_pagination_limit_offset(history_env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            page1 = await client.get("/history?limit=2&offset=0")
            page2 = await client.get("/history?limit=2&offset=2")
    assert page1.status_code == 200
    assert page2.status_code == 200
    # Different rows on each page
    page1_ids = set(re.findall(r"20\d{6}-\d{6}", page1.text))
    page2_ids = set(re.findall(r"20\d{6}-\d{6}", page2.text))
    assert page1_ids
    assert page2_ids
    assert not (page1_ids & page2_ids)


async def test_history_links_each_row_to_job_view(history_env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history")
    assert resp.status_code == 200
    body = resp.text
    for job_id in [
        "20260427-100000",
        "20260427-110000",
        "20260428-090000",
    ]:
        assert f"/jobs/{job_id}" in body, f"missing link for {job_id}"


async def test_history_renders_korean_status_labels(history_env: Path) -> None:
    """Each status MUST render with a Korean label per spec FR-021."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get("/history")
    assert resp.status_code == 200
    body = resp.text
    for label in ["완료", "실패", "진행", "중단", "대기"]:
        assert label in body, f"missing KR status label: {label}"
