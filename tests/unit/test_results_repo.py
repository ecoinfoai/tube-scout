"""Tests for tube_scout.web.repo.results_repo (T009 RED).

Covers:
- insert_result persists path metadata + counts + priority_summary JSON
- get_result returns None when absent
- get_result roundtrips priority_summary as a typed dict (not raw str)
- FK to analysis_jobs: cannot insert result for missing job_id

Targets ``tube_scout.web.repo.results_repo`` — implementation pending (T024).
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


def _result_payload(job_id: str = "20260428-153022") -> dict:
    return {
        "job_id": job_id,
        "report_v1v3_html": "03_report/v1v3.html",
        "report_v1v3_pdf": "03_report/v1v3.pdf",
        "report_v1v3_excel": "03_report/v1v3.xlsx",
        "report_reuse_html": "04_reuse/reuse.html",
        "report_reuse_excel": "04_reuse/reuse.xlsx",
        "matched_video_count": 47,
        "suspicious_pair_count": 3,
        "priority_summary": {"critical": 1, "high": 1, "moderate": 1, "normal": 0},
        "generated_at": datetime.now(UTC).isoformat(),
    }


def test_get_result_returns_none_when_absent(state_dir: Path) -> None:
    from tube_scout.web.repo import db, results_repo

    db.bootstrap()
    repo = results_repo.ResultsRepo()
    assert repo.get_result("nonexistent") is None


def test_insert_then_get_roundtrip(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo, results_repo

    db.bootstrap()
    jobs_repo.JobsRepo().insert_pending(_job_payload())
    repo = results_repo.ResultsRepo()
    repo.insert_result(_result_payload())
    out = repo.get_result("20260428-153022")
    assert out is not None
    assert out.matched_video_count == 47
    assert out.suspicious_pair_count == 3


def test_priority_summary_roundtrips_as_dict(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo, results_repo

    db.bootstrap()
    jobs_repo.JobsRepo().insert_pending(_job_payload())
    results_repo.ResultsRepo().insert_result(_result_payload())
    out = results_repo.ResultsRepo().get_result("20260428-153022")
    assert out.priority_summary == {
        "critical": 1,
        "high": 1,
        "moderate": 1,
        "normal": 0,
    }


def test_insert_without_parent_job_raises_fk(state_dir: Path) -> None:
    from tube_scout.web.repo import db, results_repo

    db.bootstrap()
    repo = results_repo.ResultsRepo()
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_result(_result_payload(job_id="orphan-id"))


def test_negative_counts_rejected(state_dir: Path) -> None:
    from tube_scout.web.repo import db, jobs_repo, results_repo

    db.bootstrap()
    jobs_repo.JobsRepo().insert_pending(_job_payload())
    bad = _result_payload()
    bad["matched_video_count"] = -1
    with pytest.raises(sqlite3.IntegrityError):
        results_repo.ResultsRepo().insert_result(bad)
