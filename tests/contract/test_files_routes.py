"""Contract tests for the file download route (T041 RED).

Targets ``GET /jobs/{id}/files/{kind}`` per
``specs/008-admin-web-ui/contracts/http-routes.md``. All 6 cases MUST fail
until T055 (results.py) lands and is wired in T064.

Spec FR-016, FR-018: 5 file kinds (v1v3-html/pdf/excel + reuse-html/excel),
Korean filename slug via RFC 5987, traversal protection.
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
DEPT_DISPLAY = "물리치료학과"
PROFESSOR = "홍길동"
COURSE = "해부생리학"
PERIOD_START = "2026-04-01"
PERIOD_END = "2026-04-28"
JOB_ID = "20260428-153022"


def _seed_department() -> None:
    from tube_scout.web.repo import db
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    db.bootstrap()
    DepartmentsRepo().add(
        {
            "alias": DEPT_ALIAS,
            "display_name": DEPT_DISPLAY,
            "channel_id_env": "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "client_secret_env": "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "api_key_env": "TUBE_SCOUT_API_KEY_PHYS",
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _seed_completed_job(state_dir: Path, *, files_present: bool = True) -> Path:
    """Insert a completed job + result row + (optionally) materialize files."""
    from tube_scout.web.repo import jobs_repo, results_repo

    repo = jobs_repo.JobsRepo()
    repo.insert_pending(
        {
            "job_id": JOB_ID,
            "department_alias": DEPT_ALIAS,
            "professor_name": PROFESSOR,
            "course_name": COURSE,
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "created_by": USERNAME,
        }
    )
    repo.transition_to(JOB_ID, status="running", current_stage="listing")
    repo.transition_to(JOB_ID, status="completed", current_stage="done")

    result_dir = state_dir / "projects" / JOB_ID
    result_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "report_v1v3_html": "v1v3.html",
        "report_v1v3_pdf": "v1v3.pdf",
        "report_v1v3_excel": "v1v3.xlsx",
        "report_reuse_html": "reuse.html",
        "report_reuse_excel": "reuse.xlsx",
    }
    if files_present:
        for fname in artifacts.values():
            (result_dir / fname).write_bytes(b"<bytes for test>")

    results_repo.ResultsRepo().insert_result(
        {
            "job_id": JOB_ID,
            **{k: str(result_dir / v) for k, v in artifacts.items()},
            "matched_video_count": 5,
            "suspicious_pair_count": 1,
            "priority_summary": {"critical": 0, "high": 1, "moderate": 0, "normal": 0},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return result_dir


@pytest.fixture
def files_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
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


async def test_files_v1v3_html_inline_disposition(files_env: Path) -> None:
    from tube_scout.web.app import create_app

    _seed_completed_job(files_env)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{JOB_ID}/files/v1v3-html")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    cd = resp.headers.get("content-disposition", "")
    assert "inline" in cd


async def test_files_pdf_attachment_with_korean_filename(files_env: Path) -> None:
    from tube_scout.web.app import create_app

    _seed_completed_job(files_env)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{JOB_ID}/files/v1v3-pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    cd = resp.headers.get("content-disposition", "")
    assert cd.startswith("attachment")
    # RFC 5987: filename* with utf-8 + percent-encoded Korean
    assert "filename*=" in cd or "filename*=UTF-8''" in cd
    assert "%EB" in cd or "%ED" in cd or DEPT_DISPLAY in cd  # Korean bytes encoded


async def test_files_unknown_kind_returns_404(files_env: Path) -> None:
    from tube_scout.web.app import create_app

    _seed_completed_job(files_env)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{JOB_ID}/files/unknown-kind")
    assert resp.status_code == 404


async def test_files_missing_disk_returns_kr_message(files_env: Path) -> None:
    from tube_scout.web.app import create_app

    _seed_completed_job(files_env, files_present=False)

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            resp = await client.get(f"/jobs/{JOB_ID}/files/v1v3-html")
    assert resp.status_code == 404
    assert "파일을 찾을 수 없습니다 — 재실행이 필요합니다." in resp.text


async def test_files_traversal_rejected(files_env: Path) -> None:
    """ADV-US1-51/52 (QA P1): expanded traversal payload coverage.

    Covers:
    - Bare ``..`` in path component (existing).
    - Encoded ``%2e%2e%2f`` (lowercase + uppercase variants).
    - Windows-style ``..\\path`` separators that some clients normalise.
    - Mixed-case and double-encoded variants.
    """
    from tube_scout.web.app import create_app

    _seed_completed_job(files_env)

    payloads = [
        "..%2Fetc%2Fpasswd",
        "v1v3-html/../etc/passwd",
        "%2e%2e%2fetc%2fpasswd",
        "%2E%2E%2Fetc%2Fpasswd",
        "..%5cetc%5cpasswd",  # backslash-encoded
        "..\\etc\\passwd",  # raw Windows separator
        "%252e%252e%252f",  # double-encoded ../
    ]

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            for payload in payloads:
                resp = await client.get(f"/jobs/{JOB_ID}/files/{payload}")
                assert resp.status_code in {400, 404}, (
                    f"payload {payload!r} returned {resp.status_code}"
                )


async def test_files_all_5_kinds_resolve_for_completed_job(files_env: Path) -> None:
    from tube_scout.web.app import create_app

    _seed_completed_job(files_env)

    app = create_app()
    kinds = ["v1v3-html", "v1v3-pdf", "v1v3-excel", "reuse-html", "reuse-excel"]
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            await _login(client)
            for kind in kinds:
                resp = await client.get(f"/jobs/{JOB_ID}/files/{kind}")
                assert resp.status_code == 200, f"{kind}: {resp.status_code} {resp.text[:120]}"
