"""RED tests for F-11: SIGINT handler in _run_transcript_and_fingerprint (ADV-22).

R-10.a/b + BUX-1.
Test strategy: call _build_ingest_sigint_handler() directly to get the handler
callable, then invoke it — avoids raising KeyboardInterrupt in the pytest process.
"""

from __future__ import annotations

import signal
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# _build_ingest_sigint_handler must be importable from unified_ingest
# ---------------------------------------------------------------------------

def test_build_ingest_sigint_handler_importable() -> None:
    """_build_ingest_sigint_handler must be exported from unified_ingest (F-11 API)."""
    from tube_scout.services.unified_ingest import (
        _build_ingest_sigint_handler,  # noqa: F401
    )


# ---------------------------------------------------------------------------
# R-10.a: handler raises SystemExit(130)
# ---------------------------------------------------------------------------

def test_sigint_handler_exits_130(tmp_path: Path) -> None:
    """_build_ingest_sigint_handler returns a callable that raises SystemExit(130) (R-10.a)."""
    from tube_scout.services.unified_ingest import _build_ingest_sigint_handler

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()

    handler = _build_ingest_sigint_handler(
        current_video_ref=["vid0000"],
        transcript_dir=transcript_dir,
        audit_writer=MagicMock(),
        channel_alias="nursing",
    )

    with pytest.raises(SystemExit) as exc_info:
        handler(signal.SIGINT, None)

    assert exc_info.value.code == 130, (
        f"R-10.a: SIGINT handler must exit 130, got {exc_info.value.code}"
    )


# ---------------------------------------------------------------------------
# R-10.b: handler writes aborted_by_user audit row
# ---------------------------------------------------------------------------

def test_sigint_handler_writes_aborted_by_user_row(tmp_path: Path) -> None:
    """Handler must call audit_writer.append_row with reason='aborted_by_user' (R-10.b)."""
    from tube_scout.services.unified_ingest import _build_ingest_sigint_handler

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    audit_writer = MagicMock()
    rows_written: list[tuple[str, dict]] = []

    def _capture(stage: str, row: dict) -> None:
        rows_written.append((stage, row))

    audit_writer.append_row.side_effect = _capture

    handler = _build_ingest_sigint_handler(
        current_video_ref=["vid0001"],
        transcript_dir=transcript_dir,
        audit_writer=audit_writer,
        channel_alias="nursing",
    )

    with pytest.raises(SystemExit):
        handler(signal.SIGINT, None)

    aborted = [
        (s, r) for s, r in rows_written if r.get("reason") == "aborted_by_user"
    ]
    assert len(aborted) >= 1, (
        f"R-10.b: aborted_by_user audit row must be written; got {rows_written}"
    )
    assert aborted[0][0] == "ingest_orchestrator", (
        f"audit row stage must be 'ingest_orchestrator', got {aborted[0][0]!r}"
    )
    assert aborted[0][1].get("video_id") == "vid0001", (
        "aborted_by_user row must contain the in-flight video_id"
    )
    assert aborted[0][1].get("result") == "fail", (
        "aborted_by_user row result must be 'fail'"
    )


# ---------------------------------------------------------------------------
# BUX-1: handler removes .partial transcript files
# ---------------------------------------------------------------------------

def test_sigint_handler_removes_partial_transcripts(tmp_path: Path) -> None:
    """Handler must remove *.partial files from transcript_dir (BUX-1)."""
    from tube_scout.services.unified_ingest import _build_ingest_sigint_handler

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "vid0000.json.partial").write_text("{}", encoding="utf-8")
    (transcript_dir / "vid0001.json.partial").write_text("{}", encoding="utf-8")
    # Non-partial file must NOT be deleted
    (transcript_dir / "vid0002.json").write_text("{}", encoding="utf-8")

    handler = _build_ingest_sigint_handler(
        current_video_ref=["vid0000"],
        transcript_dir=transcript_dir,
        audit_writer=MagicMock(),
        channel_alias="nursing",
    )

    with pytest.raises(SystemExit):
        handler(signal.SIGINT, None)

    remaining_partial = list(transcript_dir.glob("*.partial"))
    assert remaining_partial == [], (
        f"BUX-1: all .partial files must be removed; found: {remaining_partial}"
    )
    # Normal transcript must survive
    assert (transcript_dir / "vid0002.json").exists(), (
        "Non-partial transcript files must NOT be deleted"
    )


# ---------------------------------------------------------------------------
# G-4: empty current_video_ref → no audit row written
# ---------------------------------------------------------------------------

def test_sigint_handler_no_row_when_no_video_in_flight(tmp_path: Path) -> None:
    """Handler with empty current_video_ref must NOT write audit row (G-4)."""
    from tube_scout.services.unified_ingest import _build_ingest_sigint_handler

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    audit_writer = MagicMock()

    handler = _build_ingest_sigint_handler(
        current_video_ref=[],  # nothing in flight
        transcript_dir=transcript_dir,
        audit_writer=audit_writer,
        channel_alias="nursing",
    )

    with pytest.raises(SystemExit) as exc_info:
        handler(signal.SIGINT, None)

    assert exc_info.value.code == 130
    audit_writer.append_row.assert_not_called(), (
        "G-4: no audit row when current_video_ref is empty"
    )


# ---------------------------------------------------------------------------
# R-10.a: SIGINT handler registered + restored in _run_transcript_and_fingerprint
# ---------------------------------------------------------------------------

def test_original_sigint_handler_restored_after_run(tmp_path: Path) -> None:
    """Original SIGINT handler must be restored after _run_transcript_and_fingerprint returns."""
    from unittest.mock import patch

    from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

    db_path = tmp_path / "test.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS audio_fingerprint "
            "(video_id TEXT PRIMARY KEY, fingerprint BLOB NOT NULL, "
            "duration REAL NOT NULL, extracted_at TEXT NOT NULL, "
            "source TEXT NOT NULL DEFAULT 'fpcalc:1.6.0');"
        )

    original_handler = signal.getsignal(signal.SIGINT)

    with patch(
        "tube_scout.services.unified_ingest.extract_wav_16k_mono",
    ), patch(
        "tube_scout.services.unified_ingest.transcribe_audio",
        return_value=MagicMock(),
    ), patch(
        "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
        return_value=(b"fp", 10.0),
    ), patch(
        "tube_scout.services.unified_ingest.WavLifecycle",
    ) as mock_wav_cls:
        mock_wav_cls.return_value.__enter__ = MagicMock(return_value=tmp_path / "audio.wav")
        mock_wav_cls.return_value.__exit__ = MagicMock(return_value=False)

        _run_transcript_and_fingerprint(
            {"/fake/video0.mp4": "vid0000"},
            tmp_path / "channel",
            MagicMock(),
            db_path=db_path,
        )

    restored = signal.getsignal(signal.SIGINT)
    assert restored == original_handler, (
        f"Original SIGINT handler must be restored; got {restored!r}"
    )


# ---------------------------------------------------------------------------
# F-11 follow-up priority 1 (2026-05-17 audit v3): SIGINT must also append
# the in-flight video to retry_pending.json so ``--resume`` re-picks it.
# Without this, the operator's Ctrl+C silently drops the video from the
# retry queue (audit row alone is non-actionable for resume logic).
# ---------------------------------------------------------------------------


def test_sigint_handler_appends_aborted_by_user_to_retry_manifest(tmp_path: Path) -> None:
    """Handler with retry_manifest_path + current_video_meta must append entry."""
    from tube_scout.services.retry_manifest import load_manifest
    from tube_scout.services.unified_ingest import _build_ingest_sigint_handler

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    manifest_path = tmp_path / "retry_pending.json"

    current_video_meta: dict[str, str | None] = {
        "video_id": "vidAborted9",
        "mp4_filename": "9주차.mp4",
        "title": "9주차 1차시",
    }

    handler = _build_ingest_sigint_handler(
        current_video_ref=["vidAborted9"],
        transcript_dir=transcript_dir,
        audit_writer=MagicMock(),
        channel_alias="nursing",
        retry_manifest_path=manifest_path,
        current_video_meta=current_video_meta,
    )

    with pytest.raises(SystemExit) as exc_info:
        handler(signal.SIGINT, None)

    assert exc_info.value.code == 130

    manifest = load_manifest(manifest_path, expected_alias="nursing")
    aborted = [e for e in manifest.entries if e.failed_stage == "aborted_by_user"]
    assert len(aborted) == 1, f"expected 1 aborted_by_user entry; got {manifest.entries}"
    assert aborted[0].video_id == "vidAborted9"
    assert aborted[0].mp4_filename == "9주차.mp4"
    assert aborted[0].failure_reason == "aborted_by_user"


def test_sigint_handler_skips_retry_when_no_video_in_flight(tmp_path: Path) -> None:
    """G-4: empty current_video_ref → retry_pending.json untouched."""
    from tube_scout.services.unified_ingest import _build_ingest_sigint_handler

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    manifest_path = tmp_path / "retry_pending.json"

    handler = _build_ingest_sigint_handler(
        current_video_ref=[],
        transcript_dir=transcript_dir,
        audit_writer=MagicMock(),
        channel_alias="nursing",
        retry_manifest_path=manifest_path,
        current_video_meta=None,
    )

    with pytest.raises(SystemExit):
        handler(signal.SIGINT, None)

    assert not manifest_path.exists(), (
        "G-4: manifest must not be created when no video in flight"
    )


def test_sigint_handler_retry_failure_does_not_block_exit(tmp_path: Path) -> None:
    """retry manifest append exception must not prevent SystemExit(130)."""
    from unittest.mock import patch

    from tube_scout.services.unified_ingest import _build_ingest_sigint_handler

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    manifest_path = tmp_path / "retry_pending.json"

    handler = _build_ingest_sigint_handler(
        current_video_ref=["vidAborted8"],
        transcript_dir=transcript_dir,
        audit_writer=MagicMock(),
        channel_alias="nursing",
        retry_manifest_path=manifest_path,
        current_video_meta={
            "video_id": "vidAborted8",
            "mp4_filename": "8주차.mp4",
            "title": "8주차 1차시",
        },
    )

    with patch(
        "tube_scout.services.retry_manifest.append_aborted_by_user",
        side_effect=OSError("disk full"),
    ), pytest.raises(SystemExit) as exc_info:
        handler(signal.SIGINT, None)

    assert exc_info.value.code == 130
