"""T022 RED — unit tests for _check_already_processed() 4-case matrix.

Contract: idempotency-guard.md §3 + §9 GS-1~GS-5.
transcript_skip / fingerprint_skip evaluate independently; wav_decode_skip = AND.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tube_scout.services.unified_ingest import (
    IdempotencyGuardResult,
    _check_already_processed,
)

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


def _seed_fingerprint(db_path: Path, video_id: str) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO audio_fingerprint (video_id, fingerprint, duration, extracted_at)"
            " VALUES (?, ?, ?, ?)",
            (video_id, b"AAAA", 5.0, "2026-05-16T00:00:00+00:00"),
        )


def _seed_transcript(transcript_dir: Path, video_id: str) -> None:
    (transcript_dir / f"{video_id}.json").write_text("{}", encoding="utf-8")


class TestCheckAlreadyProcessedFourCaseMatrix:
    """GS-1~GS-5 from idempotency-guard.md §9."""

    def test_gs1_both_present_returns_all_skip(self, tmp_path: Path) -> None:
        """GS-1: transcript json + DB row → all-True (wav_decode_skip=True)."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        _seed_transcript(transcript_dir, "VID00001")
        _seed_fingerprint(db_path, "VID00001")

        result = _check_already_processed("VID00001", transcript_dir, db_path)

        assert result == IdempotencyGuardResult(
            video_id="VID00001",
            transcript_skip=True,
            fingerprint_skip=True,
            wav_decode_skip=True,
        )

    def test_gs2_transcript_present_db_absent(self, tmp_path: Path) -> None:
        """GS-2: transcript json exists, no DB row → (True, False, False)."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        _seed_transcript(transcript_dir, "VID00002")

        result = _check_already_processed("VID00002", transcript_dir, db_path)

        assert result == IdempotencyGuardResult(
            video_id="VID00002",
            transcript_skip=True,
            fingerprint_skip=False,
            wav_decode_skip=False,
        )

    def test_both_absent_returns_all_false(self, tmp_path: Path) -> None:
        """Both absent (no transcript, no DB row) → (False, False, False)."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        result = _check_already_processed("VID00003", transcript_dir, db_path)

        assert result == IdempotencyGuardResult(
            video_id="VID00003",
            transcript_skip=False,
            fingerprint_skip=False,
            wav_decode_skip=False,
        )

    def test_db_row_present_transcript_absent(self, tmp_path: Path) -> None:
        """DB row exists, no transcript json → (False, True, False)."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        _seed_fingerprint(db_path, "VID00004")

        result = _check_already_processed("VID00004", transcript_dir, db_path)

        assert result == IdempotencyGuardResult(
            video_id="VID00004",
            transcript_skip=False,
            fingerprint_skip=True,
            wav_decode_skip=False,
        )

    def test_gs3_both_absent_force_true_returns_all_false(self, tmp_path: Path) -> None:
        """GS-3: both absent + force=True → (False, False, False), no IO."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        result = _check_already_processed(
            "VID00005", transcript_dir, db_path, force=True
        )

        assert result == IdempotencyGuardResult(
            video_id="VID00005",
            transcript_skip=False,
            fingerprint_skip=False,
            wav_decode_skip=False,
        )

    def test_gs4_both_present_force_true_bypasses_guard(self, tmp_path: Path) -> None:
        """GS-4: both present + force=True → (False, False, False), guard bypassed."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        _seed_transcript(transcript_dir, "VID00006")
        _seed_fingerprint(db_path, "VID00006")

        result = _check_already_processed(
            "VID00006", transcript_dir, db_path, force=True
        )

        assert result == IdempotencyGuardResult(
            video_id="VID00006",
            transcript_skip=False,
            fingerprint_skip=False,
            wav_decode_skip=False,
        )

    def test_gs5_directory_absent_returns_all_false(self, tmp_path: Path) -> None:
        """GS-5: transcript_dir does not exist → transcript_skip=False (Path.exists() is False)."""
        transcript_dir = tmp_path / "transcripts"  # not created
        db_path = _make_db(tmp_path)

        result = _check_already_processed("VID00007", transcript_dir, db_path)

        assert result.transcript_skip is False
        assert result.wav_decode_skip is False

    def test_wav_decode_skip_is_and_of_both(self, tmp_path: Path) -> None:
        """wav_decode_skip == transcript_skip AND fingerprint_skip in all 4 cases."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        # case: (False, False) → False
        r = _check_already_processed("A", transcript_dir, db_path)
        assert r.wav_decode_skip == (r.transcript_skip and r.fingerprint_skip)

        # case: (True, False) → False
        _seed_transcript(transcript_dir, "B")
        r = _check_already_processed("B", transcript_dir, db_path)
        assert r.wav_decode_skip == (r.transcript_skip and r.fingerprint_skip)

        # case: (False, True) → False
        _seed_fingerprint(db_path, "C")
        r = _check_already_processed("C", transcript_dir, db_path)
        assert r.wav_decode_skip == (r.transcript_skip and r.fingerprint_skip)

        # case: (True, True) → True
        _seed_transcript(transcript_dir, "D")
        _seed_fingerprint(db_path, "D")
        r = _check_already_processed("D", transcript_dir, db_path)
        assert r.wav_decode_skip == (r.transcript_skip and r.fingerprint_skip)
        assert r.wav_decode_skip is True
