"""Tests for tube_scout.web.repo.reviews_repo (T010 RED).

Covers:
- UPSERT semantics for ``reuse_review_status``
- Status enum CHECK (unreviewed | confirmed_duplicate | false_positive)
- Note length cap at 512 chars
- find_by_pair / list_for_job lookups
- FK to analysis_jobs

Targets ``tube_scout.web.repo.reviews_repo`` — implementation pending (T025).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path))
    return tmp_path


def _job_payload(job_id: str = "20260428-153022") -> dict:
    return {
        "job_id": job_id,
        "department_alias": "physiology",
        "professor_name": "홍길동",
        "course_name": "해부생리학",
        "period_start": "2026-03-01",
        "period_end": "2026-04-30",
        "started_at": datetime.now(UTC).isoformat(),
        "created_by": "operator",
    }


def test_find_by_pair_returns_none_when_absent(state_dir: Path) -> None:
    from tube_scout.web.repo import db, reviews_repo

    db.bootstrap()
    repo = reviews_repo.ReviewsRepo()
    assert repo.find_by_pair("vidA__vidB") is None


def test_upsert_creates_new_row(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo, reviews_repo

    db.bootstrap()
    jobs_repo.JobsRepo().insert_pending(_job_payload())
    repo = reviews_repo.ReviewsRepo()
    repo.upsert_review(
        pair_id="vidA__vidB",
        job_id="20260428-153022",
        status="confirmed_duplicate",
        updated_by="operator",
        note="동일 강의 자료 재업로드",
    )
    row = repo.find_by_pair("vidA__vidB")
    assert row.status == "confirmed_duplicate"
    assert row.note == "동일 강의 자료 재업로드"


def test_upsert_updates_existing_row(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo, reviews_repo

    db.bootstrap()
    jobs_repo.JobsRepo().insert_pending(_job_payload())
    repo = reviews_repo.ReviewsRepo()
    repo.upsert_review(
        pair_id="vidA__vidB",
        job_id="20260428-153022",
        status="confirmed_duplicate",
        updated_by="operator",
        note=None,
    )
    repo.upsert_review(
        pair_id="vidA__vidB",
        job_id="20260428-153022",
        status="false_positive",
        updated_by="operator",
        note="다른 영상",
    )
    row = repo.find_by_pair("vidA__vidB")
    assert row.status == "false_positive"
    assert row.note == "다른 영상"


def test_invalid_status_rejected(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo, reviews_repo

    db.bootstrap()
    jobs_repo.JobsRepo().insert_pending(_job_payload())
    repo = reviews_repo.ReviewsRepo()
    with pytest.raises(sqlite3.IntegrityError):
        repo.upsert_review(
            pair_id="vidA__vidB",
            job_id="20260428-153022",
            status="exploded",
            updated_by="operator",
            note=None,
        )


def test_note_length_cap_at_512(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo, reviews_repo

    db.bootstrap()
    jobs_repo.JobsRepo().insert_pending(_job_payload())
    repo = reviews_repo.ReviewsRepo()
    too_long = "가" * 513
    with pytest.raises(sqlite3.IntegrityError):
        repo.upsert_review(
            pair_id="vidA__vidB",
            job_id="20260428-153022",
            status="confirmed_duplicate",
            updated_by="operator",
            note=too_long,
        )


def test_list_for_job_returns_all_pairs_for_job(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo, reviews_repo

    db.bootstrap()
    jobs_repo.JobsRepo().insert_pending(_job_payload())
    repo = reviews_repo.ReviewsRepo()
    for pid in ("a__b", "c__d", "e__f"):
        repo.upsert_review(
            pair_id=pid,
            job_id="20260428-153022",
            status="confirmed_duplicate",
            updated_by="operator",
            note=None,
        )
    rows = repo.list_for_job("20260428-153022")
    assert {r.pair_id for r in rows} == {"a__b", "c__d", "e__f"}


def test_orphan_job_id_rejected_by_fk(state_dir: Path) -> None:
    from tube_scout.web.repo import db, reviews_repo

    db.bootstrap()
    repo = reviews_repo.ReviewsRepo()
    with pytest.raises(sqlite3.IntegrityError):
        repo.upsert_review(
            pair_id="x__y",
            job_id="orphan",
            status="confirmed_duplicate",
            updated_by="operator",
            note=None,
        )
