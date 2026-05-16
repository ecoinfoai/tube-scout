"""T034 RED — unit tests for --force option semantics in unified_ingest (spec 018 US3).

Verifies:
1. _check_already_processed(force=True) always returns (False, False, False).
2. _run_transcript_and_fingerprint(force=True) calls transcribe_audio and
   extract_chromaprint_fingerprint for all videos regardless of existing state.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tube_scout.services.unified_ingest import (
    IdempotencyGuardResult,
    _check_already_processed,
    _run_transcript_and_fingerprint,
)


_V3_SQL = """
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,
    duration     REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
"""


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_V3_SQL)
    return db_path


def _seed_transcript(transcript_dir: Path, video_id: str) -> None:
    (transcript_dir / f"{video_id}.json").write_text("{}", encoding="utf-8")


def _seed_fingerprint(db_path: Path, video_id: str) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO audio_fingerprint (video_id, fingerprint, duration, extracted_at)"
            " VALUES (?, ?, ?, ?)",
            (video_id, b"AAAA", 5.0, "2026-05-16T00:00:00+00:00"),
        )


def _dummy_asr_result() -> MagicMock:
    asr = MagicMock()
    asr.caption_source_detail = "asr:faster-whisper:large-v3:int8_float16"
    asr.language_detected = "ko"
    asr.duration = 5.0
    asr.segments = []
    flags = MagicMock()
    flags.model_dump.return_value = {
        "hallucination_repeat": False,
        "vad_over_truncated": False,
        "language_mismatch": False,
        "short_segments_excess": False,
        "silence_hallucination": False,
        "compression_ratio_violations": 0,
    }
    asr.asr_quality_flags = flags
    return asr


class TestCheckAlreadyProcessedForceTrue:
    """_check_already_processed(force=True) always returns all-False."""

    def test_force_true_returns_all_false_when_both_present(
        self, tmp_path: Path
    ) -> None:
        """force=True bypasses guard even when transcript+fingerprint both exist."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        _seed_transcript(transcript_dir, "VID00001")
        _seed_fingerprint(db_path, "VID00001")

        result = _check_already_processed("VID00001", transcript_dir, db_path, force=True)

        assert result == IdempotencyGuardResult(
            video_id="VID00001",
            transcript_skip=False,
            fingerprint_skip=False,
            wav_decode_skip=False,
        )

    def test_force_true_returns_all_false_when_both_absent(
        self, tmp_path: Path
    ) -> None:
        """force=True returns all-False even with no existing state."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        result = _check_already_processed("VID00002", transcript_dir, db_path, force=True)

        assert result == IdempotencyGuardResult(
            video_id="VID00002",
            transcript_skip=False,
            fingerprint_skip=False,
            wav_decode_skip=False,
        )


class TestRunTranscriptFingerprintForceTrue:
    """_run_transcript_and_fingerprint(force=True) reprocesses all videos."""

    def test_force_true_calls_transcribe_for_all_videos(self, tmp_path: Path) -> None:
        """force=True: transcribe_audio called for every video (no skip)."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        video_ids = ["VID00001", "VID00002", "VID00003"]
        mp4_video_id_map = {}
        for vid in video_ids:
            mp4_path = tmp_path / f"{vid}.mp4"
            mp4_path.write_bytes(b"fake")
            mp4_video_id_map[str(mp4_path)] = vid
            # pre-seed both — force=True should reprocess anyway
            _seed_transcript(transcript_dir, vid)
            _seed_fingerprint(db_path, vid)

        audit_writer = MagicMock()
        asr_result = _dummy_asr_result()
        fp_bytes = b"BBBB"

        with (
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ) as mock_asr,
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(fp_bytes, 5.0),
            ) as mock_fp,
        ):
            tr, fr = _run_transcript_and_fingerprint(
                mp4_video_id_map,
                tmp_path,
                audit_writer,
                transcript_dir=transcript_dir,
                db_path=db_path,
                force=True,
            )

        assert mock_asr.call_count == 3, (
            f"Expected transcribe_audio called 3 times with force=True, got {mock_asr.call_count}"
        )
        assert mock_fp.call_count == 3, (
            f"Expected extract_chromaprint_fingerprint called 3 times with force=True, got {mock_fp.call_count}"
        )
        assert tr.success_count == 3
        assert fr.success_count == 3
        assert tr.skip_count == 0
        assert fr.skip_count == 0

    def test_force_true_skip_count_zero(self, tmp_path: Path) -> None:
        """force=True: skip_count == 0 regardless of existing state."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        mp4_path = tmp_path / "VID99999.mp4"
        mp4_path.write_bytes(b"fake")
        _seed_transcript(transcript_dir, "VID99999")
        _seed_fingerprint(db_path, "VID99999")

        audit_writer = MagicMock()
        asr_result = _dummy_asr_result()

        with (
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(b"CCCC", 5.0),
            ),
        ):
            tr, fr = _run_transcript_and_fingerprint(
                {str(mp4_path): "VID99999"},
                tmp_path,
                audit_writer,
                transcript_dir=transcript_dir,
                db_path=db_path,
                force=True,
            )

        assert tr.skip_count == 0
        assert fr.skip_count == 0
