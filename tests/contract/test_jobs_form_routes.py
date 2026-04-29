"""Contract tests for job submission routes (T039 RED).

Targets ``GET /jobs/new`` + ``POST /jobs`` per
``specs/008-admin-web-ui/contracts/http-routes.md``. All 8 cases MUST fail
until T053 (jobs.py) lands and is wired in T064.

Spec FR-005 ~ FR-011 + FR-028 are exercised. Job submissions are mediated by
an authenticated session built via ``login_session`` fixture; the CSRF token
in the cookie payload is read back from the rendered ``GET /jobs/new`` form.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

USERNAME = "ops"
PASSWORD = "S3cret-Pass!"
DEPT_ALIAS = "physiology"
DEPT_DISPLAY = "물리치료학과"


def _seed_department(state_dir, alias: str = DEPT_ALIAS) -> None:
    """Create a departments.json + admin.db for the test app."""
    from tube_scout.web.repo import db
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    db.bootstrap()
    repo = DepartmentsRepo()
    repo.add(
        {
            "alias": alias,
            "display_name": DEPT_DISPLAY,
            "channel_id_env": "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "client_secret_env": "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "api_key_env": "TUBE_SCOUT_API_KEY_PHYS",
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@pytest.fixture
def jobs_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    _seed_department(tmp_path / "state")


def _build_client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=False,
    )


async def _login_and_csrf(client: AsyncClient) -> str:
    """Authenticate the client and return a CSRF token bound to the session."""
    form = await client.get("/login")
    assert form.status_code == 200
    csrf_match = re.search(r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text)
    assert csrf_match, "csrf token not found on login form"
    csrf = csrf_match.group(1)
    resp = await client.post(
        "/login",
        data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
    )
    assert resp.status_code in {302, 303}, resp.text
    new_form = await client.get("/jobs/new")
    assert new_form.status_code == 200
    new_csrf = re.search(
        r'name="csrf_token"\s+value="([0-9a-f]{32})"', new_form.text
    )
    assert new_csrf, "csrf token not found on /jobs/new form"
    return new_csrf.group(1)


def _valid_payload(csrf: str, *, alias: str = DEPT_ALIAS) -> dict[str, str]:
    today = date.today()
    return {
        "department_alias": alias,
        "professor_name": "홍길동",
        "course_name": "해부생리학",
        "period_start": (today - timedelta(days=30)).isoformat(),
        "period_end": today.isoformat(),
        "csrf_token": csrf,
    }


async def test_get_jobs_new_renders_form_with_department_dropdown(
    jobs_env: None,
) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login_and_csrf(client)
            resp = await client.get("/jobs/new")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "<select" in body
    assert f'value="{DEPT_ALIAS}"' in body
    assert DEPT_DISPLAY in body
    assert "교수명" in body or 'name="professor_name"' in body
    assert "분석 시작" in body or "<button" in body


async def test_post_jobs_creates_job_and_redirects(jobs_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post("/jobs", data=_valid_payload(csrf))
    assert resp.status_code in {302, 303}
    location = resp.headers["location"]
    assert location.startswith("/jobs/")
    job_id = location.rsplit("/", 1)[-1]
    assert re.fullmatch(r"\d{8}-\d{6}(-\d+)?", job_id)


async def test_post_jobs_validation_blank_fields(jobs_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            payload = _valid_payload(csrf)
            payload["professor_name"] = ""
            resp = await client.post("/jobs", data=payload)
    assert resp.status_code == 200
    assert "교수명을 올바르게 입력하세요." in resp.text


async def test_post_jobs_validation_period_end_before_start(jobs_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            payload = _valid_payload(csrf)
            payload["period_start"] = "2026-04-30"
            payload["period_end"] = "2026-03-01"
            resp = await client.post("/jobs", data=payload)
    assert resp.status_code == 200
    assert "시작일은 종료일 이전이어야 합니다." in resp.text


async def test_post_jobs_validation_future_period_start(jobs_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            payload = _valid_payload(csrf)
            payload["period_start"] = (date.today() + timedelta(days=1)).isoformat()
            payload["period_end"] = (date.today() + timedelta(days=10)).isoformat()
            resp = await client.post("/jobs", data=payload)
    assert resp.status_code == 200
    assert "시작일은 미래일 수 없습니다." in resp.text


async def test_post_jobs_unknown_department_alias(jobs_env: None) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            payload = _valid_payload(csrf, alias="unknown-alias")
            resp = await client.post("/jobs", data=payload)
    assert resp.status_code == 200
    assert "선택한 학과를 찾을 수 없습니다." in resp.text


async def test_post_jobs_rejects_when_same_department_running(
    jobs_env: None, tmp_path
) -> None:
    """Spec FR-028: a second submission for an in-progress alias gets 409."""
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import jobs_repo

    repo = jobs_repo.JobsRepo()
    # Pre-seed a running job to simulate concurrent submission attempt
    repo.insert_pending(
        {
            "job_id": "20260101-120000",
            "department_alias": DEPT_ALIAS,
            "professor_name": "기존",
            "course_name": "기존",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "created_by": USERNAME,
        }
    )
    repo.transition_to(
        "20260101-120000", status="running", current_stage="listing"
    )

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post("/jobs", data=_valid_payload(csrf))
    assert resp.status_code == 409
    assert "동일 학과 분석이 이미 진행 중입니다" in resp.text


async def test_post_jobs_job_id_matches_yyyymmdd_hhmmss_pattern(
    jobs_env: None,
) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post("/jobs", data=_valid_payload(csrf))
    assert resp.status_code in {302, 303}
    location = resp.headers["location"]
    assert re.fullmatch(r"/jobs/\d{8}-\d{6}(-\d+)?", location)
