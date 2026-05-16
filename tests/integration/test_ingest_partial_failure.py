"""T025 RED — partial failure integration test (spec 017 US3).

Scenario: 자막 1 개 실패 강제 + --delete-source + y 응답
  - Stage 1: 실패 1 표시
  - Stage 2: 삭제 후보 N-1
  - N-1 mp4 unlink + 실패 영상 보존
  - retry_pending.json entry 1 추가

All assertions FAIL at RED stage (US3 not yet implemented).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ALIAS = "nursing_test"
_CHANNEL_ID = "UCfakePartialFailure000000"


def _make_registry(alias: str, channel_id: str) -> dict:
    reg = MagicMock()
    reg.channel_id = channel_id
    return {alias: reg}


def _make_fake_takeout(work_root: Path, alias: str, mp4_count: int = 3) -> Path:
    """Create a minimal fake Takeout directory with N mp4 stubs and a CSV."""
    takeout_dir = work_root / "fake_takeout" / "Takeout"
    video_dir = takeout_dir / "YouTube 및 YouTube Music" / "동영상"
    video_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = takeout_dir / "YouTube 및 YouTube Music" / "동영상 메타데이터"
    meta_dir.mkdir(parents=True, exist_ok=True)
    channel_dir = takeout_dir / "YouTube 및 YouTube Music" / "채널"
    channel_dir.mkdir(parents=True, exist_ok=True)

    video_ids = [f"vid{i:04d}Test01" for i in range(mp4_count)]
    mp4_paths = []
    for vid in video_ids:
        mp4 = video_dir / f"{vid}.mp4"
        mp4.write_bytes(b"\x00" * 512)
        mp4_paths.append(mp4)

    rows = ["동영상 URL,동영상 제목,노출 여부,공개 상태,동영상 ID"]
    for i, vid in enumerate(video_ids):
        url = f"https://www.youtube.com/watch?v={vid}"
        rows.append(f"{url},테스트 영상 {i},{_CHANNEL_ID},공개,{vid}")
    (meta_dir / "동영상.csv").write_text("\n".join(rows), encoding="utf-8")

    (channel_dir / "채널.csv").write_text(
        "채널 ID,채널 이름\n"
        f"{_CHANNEL_ID},{alias}\n",
        encoding="utf-8",
    )

    return takeout_dir, video_ids, mp4_paths


class _YesIO:
    def ask_yes_no(self, message: str, *, default: bool = False) -> bool:
        return True


@pytest.fixture
def partial_failure_env(tmp_path: Path):
    """Set up fake takeout + mock ingest_takeout returning 3 videos, 1 forced transcript failure."""
    from tube_scout.models.content import (
        FailureEntry,
        FingerprintStageResult,
        TranscriptStageResult,
    )
    from tube_scout.services.takeout_ingest import IngestResult

    takeout_dir, video_ids, mp4_paths = _make_fake_takeout(tmp_path, _ALIAS, mp4_count=3)
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    mp4_map = {str(mp4): vid for mp4, vid in zip(mp4_paths, video_ids)}

    fake_ingest_result = IngestResult(
        channel_alias=_ALIAS,
        channel_id=_CHANNEL_ID,
        total_videos=3,
        new_videos=3,
        high_confidence_mappings=3,
        medium_confidence_mappings=0,
        ambiguous_mappings=0,
        unmapped_filenames=0,
        ignored_csv_count=0,
        dry_run=False,
        mp4_present_count=3,
        mp4_absent_count=0,
        elapsed_seconds=0.0,
        mp4_video_id_map=mp4_map,
    )

    failed_vid = video_ids[0]
    transcript_failure = FailureEntry(
        video_id=failed_vid,
        title="테스트 영상 0",
        failed_stage="transcript",
        failure_reason="model_loading_failed",
        attempted_at=datetime.now(tz=UTC),
    )
    fake_transcript_result = TranscriptStageResult(
        success_count=2,
        failure_count=1,
        skipped_no_mp4_count=0,
        failures=[transcript_failure],
        elapsed_seconds=0.1,
    )
    fake_fingerprint_result = FingerprintStageResult(
        success_count=3,
        failure_count=0,
        skipped_no_mp4_count=0,
        failures=[],
        elapsed_seconds=0.1,
    )

    return {
        "takeout_dir": takeout_dir,
        "work_root": work_root,
        "db_path": db_path,
        "mp4_paths": mp4_paths,
        "video_ids": video_ids,
        "failed_vid": failed_vid,
        "fake_ingest_result": fake_ingest_result,
        "fake_transcript_result": fake_transcript_result,
        "fake_fingerprint_result": fake_fingerprint_result,
    }


def test_partial_failure_stage1_shows_failure(partial_failure_env) -> None:
    """Stage 1 must display exactly 1 failure in present_failure_table."""
    from tube_scout.services.unified_ingest import ingest_unified

    env = partial_failure_env
    audit = MagicMock()
    audit.append_row = MagicMock()

    with (
        patch("tube_scout.services.unified_ingest.ingest_takeout", return_value=env["fake_ingest_result"]),
        patch("tube_scout.services.unified_ingest._run_transcript_and_fingerprint",
              return_value=(env["fake_transcript_result"], env["fake_fingerprint_result"])),
    ):
        summary = ingest_unified(
            takeout_dir=env["takeout_dir"],
            channel_alias=_ALIAS,
            db_path=env["db_path"],
            work_root=env["work_root"],
            delete_source=True,
            audit_writer=audit,
            prompt_io=_YesIO(),
        )

    assert summary.transcript_result.failure_count == 1, (
        "Stage 1 must have 1 failure to display"
    )
    assert summary.cleanup_result is not None, (
        "--delete-source=True must produce a cleanup_result"
    )


def test_partial_failure_stage2_candidates_exclude_failed(partial_failure_env) -> None:
    """Stage 2 deletion candidates must be N-1 (failed video excluded)."""
    from tube_scout.services.unified_ingest import ingest_unified

    env = partial_failure_env
    audit = MagicMock()
    audit.append_row = MagicMock()

    with (
        patch("tube_scout.services.unified_ingest.ingest_takeout", return_value=env["fake_ingest_result"]),
        patch("tube_scout.services.unified_ingest._run_transcript_and_fingerprint",
              return_value=(env["fake_transcript_result"], env["fake_fingerprint_result"])),
    ):
        summary = ingest_unified(
            takeout_dir=env["takeout_dir"],
            channel_alias=_ALIAS,
            db_path=env["db_path"],
            work_root=env["work_root"],
            delete_source=True,
            audit_writer=audit,
            prompt_io=_YesIO(),
        )

    cr = summary.cleanup_result
    assert cr is not None
    assert cr.deletion_candidate_count == 2, (
        f"Expected N-1=2 deletion candidates (failed video excluded), got {cr.deletion_candidate_count}"
    )


def test_partial_failure_failed_video_mp4_preserved(partial_failure_env) -> None:
    """Failed video's mp4 must NOT be deleted even with operator yes."""
    from tube_scout.services.unified_ingest import ingest_unified

    env = partial_failure_env
    audit = MagicMock()
    audit.append_row = MagicMock()
    failed_mp4 = env["mp4_paths"][0]

    with (
        patch("tube_scout.services.unified_ingest.ingest_takeout", return_value=env["fake_ingest_result"]),
        patch("tube_scout.services.unified_ingest._run_transcript_and_fingerprint",
              return_value=(env["fake_transcript_result"], env["fake_fingerprint_result"])),
    ):
        ingest_unified(
            takeout_dir=env["takeout_dir"],
            channel_alias=_ALIAS,
            db_path=env["db_path"],
            work_root=env["work_root"],
            delete_source=True,
            audit_writer=audit,
            prompt_io=_YesIO(),
        )

    assert failed_mp4.exists(), (
        "Failed video's mp4 must be preserved — only successful videos are candidates for deletion"
    )


def test_partial_failure_retry_manifest_entry_added(partial_failure_env) -> None:
    """retry_pending.json must contain 1 entry for the failed video."""
    from tube_scout.services.unified_ingest import ingest_unified

    env = partial_failure_env
    audit = MagicMock()
    audit.append_row = MagicMock()

    with (
        patch("tube_scout.services.unified_ingest.ingest_takeout", return_value=env["fake_ingest_result"]),
        patch("tube_scout.services.unified_ingest._run_transcript_and_fingerprint",
              return_value=(env["fake_transcript_result"], env["fake_fingerprint_result"])),
    ):
        ingest_unified(
            takeout_dir=env["takeout_dir"],
            channel_alias=_ALIAS,
            db_path=env["db_path"],
            work_root=env["work_root"],
            delete_source=True,
            audit_writer=audit,
            prompt_io=_YesIO(),
        )

    manifest_path = env["work_root"] / _ALIAS / "retry_pending.json"
    assert manifest_path.exists(), "retry_pending.json must be created"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1, (
        f"Expected 1 entry in retry_pending.json, got {len(data['entries'])}"
    )
    assert data["entries"][0]["video_id"] == env["failed_vid"], (
        "retry_pending.json entry must be the failed video"
    )
