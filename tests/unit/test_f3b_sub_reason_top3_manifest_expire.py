"""RED tests for F-3b: sub_reason + top-3 failures + logger.exception + manifest expire.

ADV-1/54 + R-7.a + LOG-3/5.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ADV-1: sub_reason in INGEST_ORCHESTRATOR_FIELDNAMES
# ---------------------------------------------------------------------------

def test_ingest_orchestrator_fieldnames_has_sub_reason() -> None:
    """INGEST_ORCHESTRATOR_FIELDNAMES must include 'sub_reason' column (ADV-1)."""
    from tube_scout.services.audit_writer import INGEST_ORCHESTRATOR_FIELDNAMES
    assert "sub_reason" in INGEST_ORCHESTRATOR_FIELDNAMES


# ---------------------------------------------------------------------------
# LOG-5: _logger.exception on ASR/fingerprint/audio_decode failure
# ---------------------------------------------------------------------------

_AUDIO_FP_SQL = """
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,
    duration     REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
"""


def _make_test_db(path: Path) -> Path:
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(_AUDIO_FP_SQL)
    return path


def _make_ingest_result(mp4_map: dict[str, str] | None = None):
    from tube_scout.services.takeout_ingest import IngestResult
    mp4_map = mp4_map or {"/fake/video0.mp4": "vid0000"}
    return IngestResult(
        channel_id="UCtest001",
        channel_alias="nursing",
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


def _make_retry_delta(manifest_path: Path | None = None):
    from tube_scout.models.content import RetryManifestDelta
    return RetryManifestDelta(
        added_count=0, resolved_count=0, remaining_count=0,
        manifest_path=manifest_path or Path("/tmp/retry_pending.json"),
    )


def test_logger_exception_on_asr_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """_logger.exception must be called when transcribe_audio raises (LOG-5)."""
    from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

    db_path = _make_test_db(tmp_path / "test.db")
    wav_dir = tmp_path / "wav"
    wav_dir.mkdir()

    with patch(
        "tube_scout.services.unified_ingest.extract_wav_16k_mono",
    ), patch(
        "tube_scout.services.unified_ingest.transcribe_audio",
        side_effect=RuntimeError("model load failed"),
    ), patch(
        "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
        return_value=(b"fp", 10.0),
    ), patch(
        "tube_scout.services.unified_ingest.WavLifecycle",
    ) as mock_wav_cls:
        mock_wav_cls.return_value.__enter__ = MagicMock(return_value=tmp_path / "audio.wav")
        mock_wav_cls.return_value.__exit__ = MagicMock(return_value=False)

        with caplog.at_level(logging.ERROR, logger="tube_scout.services.unified_ingest"):
            _run_transcript_and_fingerprint(
                {"/fake/video0.mp4": "vid0000"},
                tmp_path / "channel",
                MagicMock(),
                transcript_dir=tmp_path / "transcripts",
                db_path=db_path,
            )

    # logger.exception emits at ERROR level
    assert any("model load failed" in r.message or "RuntimeError" in r.message
               for r in caplog.records if r.levelno >= logging.ERROR), (
        "LOG-5: _logger.exception must log the exception on ASR failure"
    )


def test_logger_exception_on_fingerprint_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """_logger.exception must be called when extract_chromaprint_fingerprint raises (LOG-5)."""
    from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint
    from tube_scout.services.asr import TranscribeResult

    db_path = _make_test_db(tmp_path / "test.db")

    fake_asr = MagicMock(spec=TranscribeResult)
    fake_asr.caption_source_detail = "whisper"
    fake_asr.language_detected = "ko"
    fake_asr.duration = 10.0
    fake_asr.segments = []
    fake_asr.asr_quality_flags = MagicMock()
    fake_asr.asr_quality_flags.model_dump.return_value = {}

    with patch(
        "tube_scout.services.unified_ingest.extract_wav_16k_mono",
    ), patch(
        "tube_scout.services.unified_ingest.transcribe_audio",
        return_value=fake_asr,
    ), patch(
        "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
        side_effect=RuntimeError("fpcalc not found"),
    ), patch(
        "tube_scout.services.unified_ingest.WavLifecycle",
    ) as mock_wav_cls:
        mock_wav_cls.return_value.__enter__ = MagicMock(return_value=tmp_path / "audio.wav")
        mock_wav_cls.return_value.__exit__ = MagicMock(return_value=False)

        with caplog.at_level(logging.ERROR, logger="tube_scout.services.unified_ingest"):
            _run_transcript_and_fingerprint(
                {"/fake/video0.mp4": "vid0000"},
                tmp_path / "channel",
                MagicMock(),
                db_path=db_path,
            )

    assert any("fpcalc" in r.message or "RuntimeError" in r.message
               for r in caplog.records if r.levelno >= logging.ERROR), (
        "LOG-5: _logger.exception must log the exception on fingerprint failure"
    )


# ---------------------------------------------------------------------------
# LOG-3: _logger.warning in _persist_transcript except
# ---------------------------------------------------------------------------

def test_persist_transcript_logs_warning_on_permission_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """_persist_transcript must emit a warning before re-raising PermissionError (LOG-3)."""
    from tube_scout.services.unified_ingest import _persist_transcript
    from tube_scout.services.asr import TranscribeResult

    fake_asr = MagicMock(spec=TranscribeResult)
    fake_asr.caption_source_detail = "whisper"
    fake_asr.language_detected = "ko"
    fake_asr.duration = 10.0
    fake_asr.segments = []
    fake_asr.asr_quality_flags = MagicMock()
    fake_asr.asr_quality_flags.model_dump.return_value = {}

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()

    with patch("os.replace", side_effect=PermissionError("read-only")):
        with caplog.at_level(logging.WARNING, logger="tube_scout.services.unified_ingest"):
            with pytest.raises(PermissionError):
                _persist_transcript(transcript_dir, "vid0001", fake_asr, "2026-01-01T00:00:00+00:00")

    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "LOG-3: _persist_transcript must log a warning before re-raising"
    )


# ---------------------------------------------------------------------------
# R-7.a: top-3 failure_reason printed when failure_count > 0
# ---------------------------------------------------------------------------

def test_print_summary_table_shows_top3_failures_when_failures_exist(
    tmp_path: Path,
) -> None:
    """_print_summary_table must print top-3 failure_reason when failure_count > 0 (R-7.a)."""
    from datetime import datetime, timezone
    from rich.console import Console
    from tube_scout.models.content import (
        FailureEntry,
        FingerprintStageResult,
        RetryManifestDelta,
        TranscriptStageResult,
        UnifiedIngestSummary,
    )
    from tube_scout.services.unified_ingest import _print_summary_table
    from tube_scout.services.takeout_ingest import IngestResult

    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    later = now + timedelta(seconds=2)
    failures = [
        FailureEntry(
            video_id=f"vid{i:04d}",
            title=f"Video {i}",
            failed_stage="transcript",
            failure_reason="model_load_failed",
            attempted_at=now,
        )
        for i in range(3)
    ] + [
        FailureEntry(
            video_id="vid0099",
            title="Video 99",
            failed_stage="transcript",
            failure_reason="cuda_oom",
            attempted_at=now,
        )
    ]

    ingest_result = _make_ingest_result()
    tr = TranscriptStageResult(
        success_count=0,
        failure_count=4,
        skipped_no_mp4_count=0,
        failures=failures,
        elapsed_seconds=1.0,
    )
    fr = FingerprintStageResult(
        success_count=0,
        failure_count=0,
        skipped_no_mp4_count=0,
        failures=[],
        elapsed_seconds=1.0,
    )
    rd = RetryManifestDelta(
        added_count=4, resolved_count=0, remaining_count=4,
        manifest_path=tmp_path / "retry_pending.json",
    )
    summary = UnifiedIngestSummary(
        channel_alias="nursing",
        ingest_result=ingest_result,
        transcript_result=tr,
        fingerprint_result=fr,
        cleanup_result=None,
        retry_manifest_delta=rd,
        total_elapsed_seconds=2.0,
        started_at=now,
        completed_at=later,
    )

    output_buf = []
    console = Console(record=True, width=120)
    _print_summary_table(summary, console=console)
    rendered = console.export_text()

    assert "model_load_failed" in rendered, (
        "R-7.a: top-3 failure reasons must appear in console output"
    )
    assert "3" in rendered, (
        "R-7.a: count for top failure reason (model_load_failed x3) must be shown"
    )


# ---------------------------------------------------------------------------
# ADV-54: select_retry_targets overflows expired entries to manual_intervention
# ---------------------------------------------------------------------------

def test_select_retry_targets_overflow_to_manual_intervention(tmp_path: Path) -> None:
    """Entries with attempt_count >= max_attempts overflow to manual_intervention_required.json (ADV-54)."""
    from datetime import datetime, timezone
    from tube_scout.models.content import RetryManifestEntry
    from tube_scout.services.retry_manifest import RetryManifest, select_retry_targets

    now = datetime.now(tz=timezone.utc)
    entries = [
        RetryManifestEntry(
            video_id=f"vid{i:04d}",
            mp4_filename=None,
            title=f"Video {i}",
            failed_stage="asr",
            failure_reason="model_load_failed",
            last_attempt_at=now,
            attempt_count=5,  # at or above max_attempts=5
        )
        for i in range(2)
    ] + [
        RetryManifestEntry(
            video_id="vid0010",
            mp4_filename=None,
            title="Video 10",
            failed_stage="asr",
            failure_reason="model_load_failed",
            last_attempt_at=now,
            attempt_count=2,  # eligible for retry
        )
    ]

    manifest = RetryManifest(
        schema_version=2,
        alias="nursing",
        updated_at=now,
        entries=entries,
    )

    manual_path = tmp_path / "manual_intervention_required.json"
    result = select_retry_targets(
        manifest,
        max_attempts=5,
        overflow_path=manual_path,
    )

    # Only eligible entries returned
    assert result == ["vid0010"], (
        "select_retry_targets must return only entries with attempt_count < max_attempts"
    )

    # Expired entries written to manual_intervention_required.json
    assert manual_path.exists(), (
        "ADV-54: overflow entries must be written to manual_intervention_required.json"
    )
    import json
    overflow = json.loads(manual_path.read_text())
    assert len(overflow["entries"]) == 2, (
        "Both expired entries must be in the overflow file"
    )
