"""T026 RED — retry followup integration test (spec 017 US3).

Scenario: retry_pending.json entry 1 + 두 번째 명령 호출 시 매니페스트 영상 우선 재시도
  - 성공 시 manifest entry 제거
  - attempt_count >= max_attempts entry 는 우선큐 제외

All assertions FAIL at RED stage (US3 retry logic not yet implemented).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ALIAS = "nursing_retry"
_CHANNEL_ID = "UCfakeRetryFollowup000000"
KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 5, 16, 8, 43, 42, tzinfo=KST)


def _make_retry_manifest(manifest_path: Path, entries: list[dict]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "alias": _ALIAS,
        "updated_at": NOW.isoformat(),
        "entries": entries,
    }
    manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_ingest_result(mp4_map: dict[str, str]):
    from tube_scout.services.takeout_ingest import IngestResult

    return IngestResult(
        channel_alias=_ALIAS,
        channel_id=_CHANNEL_ID,
        total_videos=len(mp4_map),
        new_videos=len(mp4_map),
        high_confidence_mappings=len(mp4_map),
        medium_confidence_mappings=0,
        ambiguous_mappings=0,
        unmapped_filenames=0,
        ignored_csv_count=0,
        dry_run=False,
        mp4_present_count=len(mp4_map),
        mp4_absent_count=0,
        elapsed_seconds=0.0,
        mp4_video_id_map=mp4_map,
    )


def _make_success_results(video_ids: list[str]):
    from tube_scout.models.content import FingerprintStageResult, TranscriptStageResult

    tr = TranscriptStageResult(
        success_count=len(video_ids),
        failure_count=0,
        skipped_no_mp4_count=0,
        failures=[],
        elapsed_seconds=0.1,
    )
    fr = FingerprintStageResult(
        success_count=len(video_ids),
        failure_count=0,
        skipped_no_mp4_count=0,
        failures=[],
        elapsed_seconds=0.1,
    )
    return tr, fr


@pytest.fixture
def retry_env(tmp_path: Path):
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"
    mp4_dir = tmp_path / "mp4s"
    mp4_dir.mkdir()

    pending_vid = "vidPending001T"
    mp4 = mp4_dir / f"{pending_vid}.mp4"
    mp4.write_bytes(b"\x00" * 512)

    manifest_path = work_root / _ALIAS / "retry_pending.json"
    _make_retry_manifest(manifest_path, [
        {
            "video_id": pending_vid,
            "title": "재시도 대상 영상",
            "failed_stage": "transcript",
            "failure_reason": "model_loading_failed",
            "last_attempt_at": NOW.isoformat(),
            "attempt_count": 1,
        }
    ])

    return {
        "work_root": work_root,
        "db_path": db_path,
        "mp4_paths": [mp4],
        "pending_vid": pending_vid,
        "manifest_path": manifest_path,
    }


def test_retry_followup_success_removes_manifest_entry(retry_env) -> None:
    """Second call with pending video succeeding must remove entry from retry_pending.json."""
    from tube_scout.services.unified_ingest import ingest_unified

    env = retry_env
    mp4_map = {str(env["mp4_paths"][0]): env["pending_vid"]}
    fake_ingest = _make_ingest_result(mp4_map)
    fake_tr, fake_fr = _make_success_results([env["pending_vid"]])

    audit = MagicMock()
    audit.append_row = MagicMock()

    with (
        patch("tube_scout.services.unified_ingest.ingest_takeout", return_value=fake_ingest),
        patch("tube_scout.services.unified_ingest._run_transcript_and_fingerprint",
              return_value=(fake_tr, fake_fr)),
    ):
        ingest_unified(
            takeout_dir=env["work_root"],
            channel_alias=_ALIAS,
            db_path=env["db_path"],
            work_root=env["work_root"],
            delete_source=False,
            audit_writer=audit,
        )

    data = json.loads(env["manifest_path"].read_text(encoding="utf-8"))
    assert data["entries"] == [], (
        f"Manifest entry must be removed when video succeeds on retry, got {data['entries']}"
    )


def test_retry_followup_max_attempts_excluded_from_priority(tmp_path: Path) -> None:
    """Entry with attempt_count >= max_attempts must not be in priority queue."""
    from tube_scout.models.content import RetryManifestEntry
    from tube_scout.services.retry_manifest import RetryManifest, select_retry_targets

    over_max = RetryManifestEntry(
        video_id="overMaxVid001",
        mp4_filename=None,
        title="한도 초과 영상",
        failed_stage="asr",
        failure_reason="model_loading_failed",
        last_attempt_at=NOW,
        attempt_count=5,
    )
    under_max = RetryManifestEntry(
        video_id="underMaxVid01",
        mp4_filename=None,
        title="재시도 가능 영상",
        failed_stage="asr",
        failure_reason="model_loading_failed",
        last_attempt_at=NOW,
        attempt_count=3,
    )
    manifest = RetryManifest(
        schema_version=2,
        alias=_ALIAS,
        updated_at=NOW,
        entries=[over_max, under_max],
    )

    targets = select_retry_targets(manifest, max_attempts=5)

    assert "underMaxVid01" in targets, "under-max entry must be in retry targets"
    assert "overMaxVid001" not in targets, (
        "Entry with attempt_count >= max_attempts must be excluded from retry targets"
    )


def test_retry_followup_priority_targets_are_processed_first(retry_env) -> None:
    """Manifest pending video must appear in mp4_video_id_map processing if mp4 is present."""
    from tube_scout.services.retry_manifest import load_manifest, select_retry_targets

    env = retry_env
    manifest = load_manifest(env["manifest_path"])
    targets = select_retry_targets(manifest, max_attempts=5)

    assert env["pending_vid"] in targets, (
        "Pending video (attempt_count=1) must be in retry priority targets"
    )


def test_retry_followup_delta_reflects_resolved(retry_env) -> None:
    """UnifiedIngestSummary.retry_manifest_delta.resolved_count must equal 1 after retry success."""
    from tube_scout.services.unified_ingest import ingest_unified

    env = retry_env
    mp4_map = {str(env["mp4_paths"][0]): env["pending_vid"]}
    fake_ingest = _make_ingest_result(mp4_map)
    fake_tr, fake_fr = _make_success_results([env["pending_vid"]])

    audit = MagicMock()
    audit.append_row = MagicMock()

    with (
        patch("tube_scout.services.unified_ingest.ingest_takeout", return_value=fake_ingest),
        patch("tube_scout.services.unified_ingest._run_transcript_and_fingerprint",
              return_value=(fake_tr, fake_fr)),
    ):
        summary = ingest_unified(
            takeout_dir=env["work_root"],
            channel_alias=_ALIAS,
            db_path=env["db_path"],
            work_root=env["work_root"],
            delete_source=False,
            audit_writer=audit,
        )

    delta = summary.retry_manifest_delta
    assert delta.resolved_count == 1, (
        f"Expected resolved_count=1 after successful retry, got {delta.resolved_count}"
    )
    assert delta.remaining_count == 0, (
        f"Expected remaining_count=0 after all entries resolved, got {delta.remaining_count}"
    )
