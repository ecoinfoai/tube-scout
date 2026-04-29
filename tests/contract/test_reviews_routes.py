"""Contract tests for the reviews endpoint (T068 RED).

Targets ``POST /jobs/{job_id}/reviews/{pair_id}`` per
``contracts/http-routes.md``. 5 cases MUST fail until T074
(routes/reviews.py) lands. Spec FR-019 + FR-020.
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
JOB_ID = "20260428-100000"
PAIR_ID = "pair-abc123"


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


def _seed_job_and_pair() -> None:
    from tube_scout.web.repo import jobs_repo, reviews_repo

    jobs_repo.JobsRepo().insert_pending(
        {
            "job_id": JOB_ID,
            "department_alias": DEPT_ALIAS,
            "professor_name": "홍길동",
            "course_name": "해부생리학",
            "period_start": "2026-04-01",
            "period_end": "2026-04-28",
            "started_at": datetime.now(UTC).isoformat(),
            "created_by": USERNAME,
        }
    )
    jobs_repo.JobsRepo().transition_to(JOB_ID, status="completed", current_stage="done")
    # Seed a known pair as ``unreviewed`` so the route can resolve it.
    reviews_repo.ReviewsRepo().upsert_review(
        pair_id=PAIR_ID,
        job_id=JOB_ID,
        status="unreviewed",
        updated_by=None,
        note=None,
    )


@pytest.fixture
def reviews_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    _seed_department()
    _seed_job_and_pair()
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


async def test_review_marks_pair_as_confirmed_duplicate(reviews_env: Path) -> None:
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import reviews_repo

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{JOB_ID}/reviews/{PAIR_ID}",
                data={
                    "status": "confirmed_duplicate",
                    "csrf_token": csrf,
                    "note": "동일 강의 재업로드 확인",
                },
            )
    assert resp.status_code in {302, 303}, resp.text
    row = reviews_repo.ReviewsRepo().find_by_pair(PAIR_ID)
    assert row is not None
    assert row.status == "confirmed_duplicate"
    assert row.note == "동일 강의 재업로드 확인"


async def test_review_marks_pair_as_false_positive(reviews_env: Path) -> None:
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import reviews_repo

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{JOB_ID}/reviews/{PAIR_ID}",
                data={"status": "false_positive", "csrf_token": csrf},
            )
    assert resp.status_code in {302, 303}, resp.text
    row = reviews_repo.ReviewsRepo().find_by_pair(PAIR_ID)
    assert row is not None
    assert row.status == "false_positive"


async def test_review_unknown_pair_returns_404(reviews_env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{JOB_ID}/reviews/unknown-pair-zzz",
                data={"status": "confirmed_duplicate", "csrf_token": csrf},
            )
    assert resp.status_code == 404


async def test_review_invalid_status_rejected(reviews_env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{JOB_ID}/reviews/{PAIR_ID}",
                data={"status": "INVALID_STATUS", "csrf_token": csrf},
            )
    assert resp.status_code == 400
    assert "리뷰 상태 값이 올바르지 않습니다." in resp.text


async def test_review_note_over_512_rejected(reviews_env: Path) -> None:
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            resp = await client.post(
                f"/jobs/{JOB_ID}/reviews/{PAIR_ID}",
                data={
                    "status": "confirmed_duplicate",
                    "csrf_token": csrf,
                    "note": "x" * 513,
                },
            )
    assert resp.status_code == 400
    assert "리뷰 메모는 512자 이하여야 합니다." in resp.text


async def test_review_pair_belonging_to_other_job_rejected(
    reviews_env: Path,
) -> None:
    """ADV-US2-22 (IDOR): cannot mutate a pair that belongs to a different job.

    The route URL embeds ``{job_id}``, the form mutates the pair's status.
    If the pair was originally surfaced under a *different* job, the
    request is an IDOR attempt — must be rejected (404).
    """
    from tube_scout.web.app import create_app
    from tube_scout.web.repo import jobs_repo, reviews_repo

    other_job_id = "20260429-090000"
    other_pair = "pair-other-001"
    jobs_repo.JobsRepo().insert_pending(
        {
            "job_id": other_job_id,
            "department_alias": DEPT_ALIAS,
            "professor_name": "다른교수",
            "course_name": "다른과목",
            "period_start": "2026-04-01",
            "period_end": "2026-04-28",
            "started_at": datetime.now(UTC).isoformat(),
            "created_by": USERNAME,
        }
    )
    jobs_repo.JobsRepo().transition_to(
        other_job_id, status="completed", current_stage="done"
    )
    reviews_repo.ReviewsRepo().upsert_review(
        pair_id=other_pair,
        job_id=other_job_id,
        status="unreviewed",
        updated_by=None,
        note=None,
    )

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            # Try to mutate other_pair via JOB_ID's URL — IDOR attempt.
            resp = await client.post(
                f"/jobs/{JOB_ID}/reviews/{other_pair}",
                data={"status": "false_positive", "csrf_token": csrf},
            )
    assert resp.status_code == 404


async def test_review_redirect_rejects_unsafe_referer(reviews_env: Path) -> None:
    """ADV-US2-23: backslash / external referer MUST NOT drive redirect."""
    from tube_scout.web.app import create_app

    app = create_app()
    async with _build_client(app) as client:
        async with app.router.lifespan_context(app):
            csrf = await _login_and_csrf(client)
            for unsafe in [
                "/\\evil.com",
                "//evil.com",
                "https://evil.example.com/path",
                "javascript:alert(1)",
                "/path\rwith\ncrlf",
            ]:
                resp = await client.post(
                    f"/jobs/{JOB_ID}/reviews/{PAIR_ID}",
                    data={"status": "false_positive", "csrf_token": csrf},
                    headers={"referer": unsafe},
                )
                assert resp.status_code in {302, 303}, unsafe
                location = resp.headers["location"]
                assert location == f"/jobs/{JOB_ID}/results", (
                    f"unsafe referer {unsafe!r} drove redirect → {location!r}"
                )
