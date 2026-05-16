"""T023 RED — skip_count accumulation in TranscriptStageResult / FingerprintStageResult.

Verifies that after _run_transcript_and_fingerprint completes, skip_count in both
stage results equals the number of videos skipped by the idempotency guard (FR-018F).
Also verifies: asr_quality_flags truthy flags do not affect audit reason (T032).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint


_V3_BASELINE_SQL = """
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
        conn.executescript(_V3_BASELINE_SQL)
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


def _make_audit_writer() -> MagicMock:
    aw = MagicMock()
    aw.append_row = MagicMock()
    return aw


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


class TestSkipCountAccumulation:
    """FR-018F: skip_count matches idempotency guard skip count after loop."""

    def test_skip_count_all_skipped(self, tmp_path: Path) -> None:
        """All 3 videos already processed → skip_count == 3, success_count == 0."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        video_ids = ["VID00001", "VID00002", "VID00003"]
        mp4_video_id_map = {}
        for vid in video_ids:
            mp4_path = tmp_path / f"{vid}.mp4"
            mp4_path.write_bytes(b"fake")
            mp4_video_id_map[str(mp4_path)] = vid
            _seed_transcript(transcript_dir, vid)
            _seed_fingerprint(db_path, vid)

        audit_writer = _make_audit_writer()

        tr, fr = _run_transcript_and_fingerprint(
            mp4_video_id_map,
            tmp_path,
            audit_writer,
            transcript_dir=transcript_dir,
            db_path=db_path,
        )

        assert tr.skip_count == 3
        assert fr.skip_count == 3
        assert tr.success_count == 0
        assert fr.success_count == 0

    def test_skip_count_partial_skip(self, tmp_path: Path) -> None:
        """2 videos skipped, 1 new → skip_count == 2, success_count == 1."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        video_ids = ["VID00001", "VID00002", "VID00003"]
        mp4_video_id_map = {}
        for vid in video_ids:
            mp4_path = tmp_path / f"{vid}.mp4"
            mp4_path.write_bytes(b"fake")
            mp4_video_id_map[str(mp4_path)] = vid

        # pre-seed only 2 videos (both transcript + fingerprint)
        for vid in ["VID00001", "VID00002"]:
            _seed_transcript(transcript_dir, vid)
            _seed_fingerprint(db_path, vid)

        audit_writer = _make_audit_writer()
        asr_result = _dummy_asr_result()
        fp_bytes = b"BBBB"

        with (
            patch(
                "tube_scout.services.unified_ingest.extract_wav_16k_mono"
            ),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(fp_bytes, 5.0),
            ),
        ):
            tr, fr = _run_transcript_and_fingerprint(
                mp4_video_id_map,
                tmp_path,
                audit_writer,
                transcript_dir=transcript_dir,
                db_path=db_path,
            )

        assert tr.skip_count == 2
        assert fr.skip_count == 2
        assert tr.success_count == 1
        assert fr.success_count == 1

    def test_skip_count_none_skipped(self, tmp_path: Path) -> None:
        """No prior processing → skip_count == 0, success_count == 1."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        mp4_path = tmp_path / "VID99999.mp4"
        mp4_path.write_bytes(b"fake")
        mp4_video_id_map = {str(mp4_path): "VID99999"}

        audit_writer = _make_audit_writer()
        asr_result = _dummy_asr_result()
        fp_bytes = b"CCCC"

        with (
            patch(
                "tube_scout.services.unified_ingest.extract_wav_16k_mono"
            ),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(fp_bytes, 5.0),
            ),
        ):
            tr, fr = _run_transcript_and_fingerprint(
                mp4_video_id_map,
                tmp_path,
                audit_writer,
                transcript_dir=transcript_dir,
                db_path=db_path,
            )

        assert tr.skip_count == 0
        assert fr.skip_count == 0
        assert tr.success_count == 1
        assert fr.success_count == 1

    def test_quality_flags_truthy_does_not_change_audit_reason(
        self, tmp_path: Path
    ) -> None:
        """T032: asr_quality_flags truthy → audit reason still 'asr_transcribed'."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        mp4_path = tmp_path / "VID11111.mp4"
        mp4_path.write_bytes(b"fake")
        mp4_video_id_map = {str(mp4_path): "VID11111"}

        audit_writer = _make_audit_writer()
        asr_result = _dummy_asr_result()
        # set all quality flags to True / nonzero — should not change audit reason
        asr_result.asr_quality_flags.model_dump.return_value = {
            "hallucination_repeat": True,
            "vad_over_truncated": True,
            "language_mismatch": True,
            "short_segments_excess": True,
            "silence_hallucination": True,
            "compression_ratio_violations": 5,
        }
        fp_bytes = b"DDDD"

        with (
            patch(
                "tube_scout.services.unified_ingest.extract_wav_16k_mono"
            ),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(fp_bytes, 5.0),
            ),
        ):
            _run_transcript_and_fingerprint(
                mp4_video_id_map,
                tmp_path,
                audit_writer,
                transcript_dir=transcript_dir,
                db_path=db_path,
            )

        # Find the asr audit row call
        asr_calls = [
            call
            for call in audit_writer.append_row.call_args_list
            if call.args[0] == "ingest_orchestrator"
            and call.args[1].get("reason") == "asr_transcribed"
        ]
        assert len(asr_calls) == 1, (
            f"Expected 1 'asr_transcribed' audit row regardless of quality flags, "
            f"got {len(asr_calls)}. All calls: {audit_writer.append_row.call_args_list}"
        )
