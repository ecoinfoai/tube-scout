"""Tests for tube_scout.web.repo.jobs_repo (T008 RED).

Covers:
- insert_pending creates a row with status='pending'
- transition_to running/completed/failed/interrupted
- status CHECK constraint rejects unknown status
- current_stage monotonic transitions (no backward stages)
- FK enforcement against departments registry (soft FK — alias must exist)

These tests target ``tube_scout.web.repo.jobs_repo`` which is NOT YET
implemented (T021/T023). RED is signalled by ImportError until then.
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


def _job_payload(job_id: str = "20260428-153022", alias: str = "physiology") -> dict:
    return {
        "job_id": job_id,
        "department_alias": alias,
        "professor_name": "홍길동",
        "course_name": "해부생리학",
        "period_start": "2026-03-01",
        "period_end": "2026-04-30",
        "started_at": datetime.now(UTC).isoformat(),
        "created_by": "operator",
    }


def test_insert_pending_creates_row_with_pending_status(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload())

    row = repo.find_by_id("20260428-153022")
    assert row is not None
    assert row.status == "pending"
    assert row.current_stage is None
    assert row.processed_count == 0
    assert row.total_count == 0


def test_transition_to_running_then_completed(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload())
    repo.transition_to("20260428-153022", status="running", current_stage="listing")
    repo.transition_to("20260428-153022", status="completed", current_stage="done")
    row = repo.find_by_id("20260428-153022")
    assert row.status == "completed"
    assert row.current_stage == "done"


def test_transition_to_failed_records_error_code(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload())
    repo.transition_to(
        "20260428-153022",
        status="failed",
        error_code="oauth_expired",
        error_detail="HttpError 401: invalid_grant",
    )
    row = repo.find_by_id("20260428-153022")
    assert row.status == "failed"
    assert row.error_code == "oauth_expired"


def test_transition_to_interrupted_on_shutdown(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload())
    repo.transition_to("20260428-153022", status="running", current_stage="metadata")
    repo.transition_to("20260428-153022", status="interrupted")
    assert repo.find_by_id("20260428-153022").status == "interrupted"


def test_unknown_status_rejected_by_check_constraint(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload())
    with pytest.raises(sqlite3.IntegrityError):
        repo.transition_to("20260428-153022", status="exploded")


def test_monotonic_stage_transitions_no_backwards(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload())
    repo.transition_to("20260428-153022", status="running", current_stage="listing")
    repo.transition_to("20260428-153022", status="running", current_stage="metadata")
    repo.transition_to("20260428-153022", status="running", current_stage="transcripts")

    with pytest.raises(jobs_repo.StageRegressionError):
        repo.transition_to("20260428-153022", status="running", current_stage="metadata")


def test_processed_le_total_constraint(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload())
    with pytest.raises(sqlite3.IntegrityError):
        repo.update_progress("20260428-153022", processed_count=10, total_count=5)


def test_find_in_progress_for_department(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload(job_id="20260428-153022", alias="physiology"))
    repo.transition_to("20260428-153022", status="running", current_stage="listing")
    repo.insert_pending(_job_payload(job_id="20260428-153100", alias="physiology"))

    in_progress = repo.find_in_progress_for_department("physiology")
    aliases = {j.job_id for j in in_progress}
    assert aliases == {"20260428-153022", "20260428-153100"}


def test_list_history_orders_by_started_at_desc(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload(job_id="20260427-100000"))
    repo.insert_pending(_job_payload(job_id="20260428-100000"))
    history = repo.list_history(limit=10, offset=0)
    assert [j.job_id for j in history] == ["20260428-100000", "20260427-100000"]


def test_list_history_filters_by_status(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(_job_payload(job_id="20260428-100000"))
    repo.transition_to("20260428-100000", status="completed", current_stage="done")
    repo.insert_pending(_job_payload(job_id="20260428-110000"))
    only_completed = repo.list_history(filters={"status": ["completed"]}, limit=10, offset=0)
    assert [j.job_id for j in only_completed] == ["20260428-100000"]


def test_period_start_le_end_check_constraint(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo

    db.bootstrap()
    repo = jobs_repo.JobsRepo()
    bad = _job_payload()
    bad["period_start"] = "2026-05-01"
    bad["period_end"] = "2026-04-01"
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_pending(bad)
