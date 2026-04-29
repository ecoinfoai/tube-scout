"""Tests for tube_scout.web.jobs.progress (T016 RED).

Covers:
- All 8 stages have a Korean label (listing/metadata/transcripts/retention/
  analytics/reuse_detection/reporting/done)
- serialize() returns the JSON shape from http-routes.md GET /progress
- error_message_kr is set when status=='failed', None otherwise
- error_code never leaks internal env/path identifiers (delegated to errors.py
  but progress carries the user-facing message, not the raw detail)

Targets ``tube_scout.web.jobs.progress`` — implementation pending (T033).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

ALL_STAGES = [
    "listing",
    "metadata",
    "transcripts",
    "retention",
    "analytics",
    "reuse_detection",
    "reporting",
    "done",
]


def test_every_stage_has_korean_label() -> None:
    from tube_scout.web.jobs import progress

    for stage in ALL_STAGES:
        label = progress.stage_label_kr(stage)
        assert label
        assert re.search(r"[가-힣]", label), f"no Korean chars for {stage}: {label!r}"


def test_unknown_stage_raises_value_error() -> None:
    from tube_scout.web.jobs import progress

    with pytest.raises(ValueError):
        progress.stage_label_kr("nonexistent")


def test_serialize_running_shape_matches_contract() -> None:
    from tube_scout.web.jobs import progress

    started = datetime(2026, 4, 28, 15, 30, 22, tzinfo=UTC).isoformat()
    snap = progress.JobProgress(
        job_id="20260428-153022",
        status="running",
        current_stage="transcripts",
        processed_count=12,
        total_count=47,
        started_at=started,
        completed_at=None,
        error_code=None,
        error_message_kr=None,
    )
    payload = progress.serialize(snap)
    assert payload == {
        "job_id": "20260428-153022",
        "status": "running",
        "current_stage": "transcripts",
        "stage_label_kr": "자막 수집 중",
        "processed": 12,
        "total": 47,
        "started_at": started,
        "completed_at": None,
        "error_code": None,
        "error_message_kr": None,
    }


def test_serialize_completed_returns_done_label() -> None:
    from tube_scout.web.jobs import progress

    started = datetime(2026, 4, 28, 15, 30, 22, tzinfo=UTC).isoformat()
    completed = datetime(2026, 4, 28, 15, 45, 0, tzinfo=UTC).isoformat()
    snap = progress.JobProgress(
        job_id="20260428-153022",
        status="completed",
        current_stage="done",
        processed_count=47,
        total_count=47,
        started_at=started,
        completed_at=completed,
        error_code=None,
        error_message_kr=None,
    )
    payload = progress.serialize(snap)
    assert payload["status"] == "completed"
    assert payload["current_stage"] == "done"
    assert payload["stage_label_kr"] == "완료"
    assert payload["completed_at"] == completed


def test_serialize_failed_carries_kr_error_message() -> None:
    from tube_scout.web.jobs import progress

    snap = progress.JobProgress(
        job_id="20260428-153022",
        status="failed",
        current_stage="transcripts",
        processed_count=5,
        total_count=47,
        started_at=datetime(2026, 4, 28, 15, 30, 22, tzinfo=UTC).isoformat(),
        completed_at=None,
        error_code="oauth_expired",
        error_message_kr="인증이 만료되었습니다. 운영자에게 토큰 갱신을 요청하세요.",
    )
    payload = progress.serialize(snap)
    assert payload["status"] == "failed"
    assert payload["error_code"] == "oauth_expired"
    assert "만료" in payload["error_message_kr"]


def test_serialize_no_internal_paths_in_payload() -> None:
    from tube_scout.web.jobs import progress

    snap = progress.JobProgress(
        job_id="20260428-153022",
        status="failed",
        current_stage="metadata",
        processed_count=2,
        total_count=10,
        started_at=datetime(2026, 4, 28, 15, 30, 22, tzinfo=UTC).isoformat(),
        completed_at=None,
        error_code="quota_exceeded",
        error_message_kr="API 할당량을 초과했습니다.",
    )
    payload = progress.serialize(snap)
    blob = repr(payload)
    assert "/home/" not in blob
    assert "TUBE_SCOUT_" not in blob
    assert "Traceback" not in blob


def test_serialize_pending_has_null_stage() -> None:
    from tube_scout.web.jobs import progress

    snap = progress.JobProgress(
        job_id="20260428-153022",
        status="pending",
        current_stage=None,
        processed_count=0,
        total_count=0,
        started_at=datetime(2026, 4, 28, 15, 30, 22, tzinfo=UTC).isoformat(),
        completed_at=None,
        error_code=None,
        error_message_kr=None,
    )
    payload = progress.serialize(snap)
    assert payload["current_stage"] is None
    assert payload["stage_label_kr"] is None
