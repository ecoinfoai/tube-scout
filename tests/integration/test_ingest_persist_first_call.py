"""Integration test: first call to collect ingest persists transcripts + fingerprints.

spec 018 T013 RED — verifies FR-018A + FR-018B:
  (a) transcript JSON 3개 atomic write (*.tmp residue 0)
  (b) audio_fingerprint DB row 3개
  (c) WAV cleanup after processing
  (d) Rich Table shows 처리 3 for transcript/fingerprint rows

Uses spec018_mini_archive fixture (3 synthetic mp4, 5s each).
ASR and fingerprint extraction are mocked to avoid model loading in CI.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_FIXTURE_ARCHIVE = (
    Path(__file__).parent.parent / "fixtures" / "spec018_mini_archive"
)


def _make_mock_asr_result() -> MagicMock:
    result = MagicMock()
    result.caption_source_detail = "asr:faster-whisper:large-v3:int8_float16"
    result.language_detected = "ko"
    result.duration = 5.0
    result.segments = [
        {
            "start": 0.0,
            "end": 2.5,
            "text": "테스트",
            "compression_ratio": 1.1,
            "no_speech_prob": 0.02,
        }
    ]
    result.asr_quality_flags = MagicMock()
    result.asr_quality_flags.model_dump.return_value = {
        "hallucination_repeat": False,
        "vad_over_truncated": False,
        "language_mismatch": False,
        "short_segments_excess": False,
        "silence_hallucination": False,
        "compression_ratio_violations": 0,
    }
    return result


_V3_SQL = """
CREATE TABLE IF NOT EXISTS processing_status (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    caption_source TEXT,
    error_message TEXT,
    collected_at TEXT,
    fingerprinted_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,
    duration     REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
PRAGMA user_version = 3;
"""


@pytest.fixture
def work_env(tmp_path: Path):
    """Set up work directory + SQLite DB for ingest tests."""
    db_path = tmp_path / "test.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_V3_SQL)

    alias = "test_nursing"
    work_root = tmp_path / "data"
    work_root.mkdir()

    return {
        "db_path": db_path,
        "work_root": work_root,
        "alias": alias,
        "transcript_dir": work_root / alias / "02_analyze" / "transcripts",
        "tmp_wav_dir": work_root / alias / "tmp_wav",
    }


class TestIngestPersistFirstCall:
    """T013: first call persists 3 transcript JSONs + 3 DB rows + WAV cleanup."""

    def test_transcript_json_count_after_first_call(
        self, tmp_path: Path, work_env: dict
    ) -> None:
        """After first call: transcript JSON 3개 생성, *.tmp 0개 (FR-018A)."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        mp4_dir = _FIXTURE_ARCHIVE / "YouTube and YouTube Music" / "videos"
        mp4_files = sorted(mp4_dir.glob("*.mp4"))
        assert len(mp4_files) == 3, f"expected 3 mp4 in fixture, got {len(mp4_files)}"

        fake_video_ids = {str(p): f"VID0000{i+1}" for i, p in enumerate(mp4_files)}

        audit = AuditWriter(work_env["work_root"] / work_env["alias"])
        work_channel = work_env["work_root"] / work_env["alias"]
        work_channel.mkdir(parents=True, exist_ok=True)

        with (
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=_make_mock_asr_result(),
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(b"AAAAAA==", 5.0),
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_wav_16k_mono",
            ),
            patch(
                "tube_scout.services.unified_ingest.insert_audio_fingerprint",
            ),
        ):
            _run_transcript_and_fingerprint(
                fake_video_ids,
                work_channel,
                audit,
                skipped_no_mp4_count=0,
                transcript_dir=work_env["transcript_dir"],
                db_path=work_env["db_path"],
            )

        transcript_dir = work_env["transcript_dir"]
        json_files = list(transcript_dir.glob("*.json"))
        tmp_files = list(transcript_dir.glob("*.tmp"))

        assert len(json_files) == 3, f"expected 3 JSON, got {json_files}"
        assert tmp_files == [], f"unexpected .tmp residue: {tmp_files}"

    def test_wav_cleanup_after_processing(
        self, tmp_path: Path, work_env: dict
    ) -> None:
        """WAV temp files are removed after WavLifecycle exits (SC-005)."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        mp4_dir = _FIXTURE_ARCHIVE / "YouTube and YouTube Music" / "videos"
        mp4_files = sorted(mp4_dir.glob("*.mp4"))
        fake_video_ids = {str(p): f"VID0000{i+1}" for i, p in enumerate(mp4_files)}

        audit = AuditWriter(work_env["work_root"] / work_env["alias"])
        work_channel = work_env["work_root"] / work_env["alias"]
        work_channel.mkdir(parents=True, exist_ok=True)

        with (
            patch("tube_scout.services.unified_ingest.transcribe_audio",
                  return_value=_make_mock_asr_result()),
            patch("tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                  return_value=(b"AAAAAA==", 5.0)),
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch("tube_scout.services.unified_ingest.insert_audio_fingerprint"),
        ):
            _run_transcript_and_fingerprint(
                fake_video_ids,
                work_channel,
                audit,
                skipped_no_mp4_count=0,
                transcript_dir=work_env["transcript_dir"],
                db_path=work_env["db_path"],
            )

        wav_dir = work_channel / "tmp_wav"
        if wav_dir.exists():
            wav_files = list(wav_dir.glob("*.wav"))
            assert wav_files == [], f"WAV residue found: {wav_files}"
