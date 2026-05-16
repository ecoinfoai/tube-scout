"""T024 RED — contract tests for idempotency guard.

Contract: idempotency-guard.md §4 (SQL pattern), §5 (file existence),
§6 (wav_decode_skip semantics). Also verifies Fail-Fast on missing DB schema.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tube_scout.services.unified_ingest import _check_already_processed


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


def _empty_db(tmp_path: Path) -> Path:
    """SQLite DB with no tables — schema mismatch scenario."""
    db_path = tmp_path / "empty.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA user_version = 0")
    return db_path


def _seed_fingerprint(db_path: Path, video_id: str) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO audio_fingerprint (video_id, fingerprint, duration, extracted_at)"
            " VALUES (?, ?, ?, ?)",
            (video_id, b"AAAA", 5.0, "2026-05-16T00:00:00+00:00"),
        )


class TestIdempotencyGuardSqlPattern:
    """§4: SQL SELECT 1 FROM audio_fingerprint WHERE video_id=? LIMIT 1."""

    def test_present_row_returns_fingerprint_skip_true(self, tmp_path: Path) -> None:
        """DB row exists → fingerprint_skip=True."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        _seed_fingerprint(db_path, "VID00001")

        result = _check_already_processed("VID00001", transcript_dir, db_path)
        assert result.fingerprint_skip is True

    def test_absent_row_returns_fingerprint_skip_false(self, tmp_path: Path) -> None:
        """No DB row → fingerprint_skip=False."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        result = _check_already_processed("VID99999", transcript_dir, db_path)
        assert result.fingerprint_skip is False

    def test_empty_db_raises_operational_error(self, tmp_path: Path) -> None:
        """§4 Fail-Fast: missing audio_fingerprint table → OperationalError (no auto-create)."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _empty_db(tmp_path)

        with pytest.raises((sqlite3.OperationalError, RuntimeError)):
            _check_already_processed("VID00001", transcript_dir, db_path)


class TestIdempotencyGuardFilePattern:
    """§5: transcript_skip = (transcript_dir / f"{video_id}.json").exists()."""

    def test_transcript_json_exists_returns_skip_true(self, tmp_path: Path) -> None:
        """JSON file exists → transcript_skip=True."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        (transcript_dir / "VID00001.json").write_text("{}", encoding="utf-8")

        result = _check_already_processed("VID00001", transcript_dir, db_path)
        assert result.transcript_skip is True

    def test_transcript_json_absent_returns_skip_false(self, tmp_path: Path) -> None:
        """No JSON file → transcript_skip=False."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)

        result = _check_already_processed("VID99999", transcript_dir, db_path)
        assert result.transcript_skip is False

    def test_tmp_file_is_ignored(self, tmp_path: Path) -> None:
        """*.tmp residue is not treated as a valid transcript (§5.1)."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        # create a .tmp residue, not a .json
        (transcript_dir / "VID00001.json.tmp").write_text("{}", encoding="utf-8")

        result = _check_already_processed("VID00001", transcript_dir, db_path)
        assert result.transcript_skip is False


class TestIdempotencyGuardWavDecodeSkipSemantics:
    """§6: wav_decode_skip = transcript_skip AND fingerprint_skip."""

    def test_wav_decode_skip_requires_both_true(self, tmp_path: Path) -> None:
        """wav_decode_skip=True iff both guards are True."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        (transcript_dir / "VID00001.json").write_text("{}", encoding="utf-8")
        _seed_fingerprint(db_path, "VID00001")

        result = _check_already_processed("VID00001", transcript_dir, db_path)
        assert result.wav_decode_skip is True

    def test_wav_decode_skip_false_when_only_transcript_skip(
        self, tmp_path: Path
    ) -> None:
        """wav_decode_skip=False when only transcript_skip=True."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        (transcript_dir / "VID00002.json").write_text("{}", encoding="utf-8")

        result = _check_already_processed("VID00002", transcript_dir, db_path)
        assert result.wav_decode_skip is False

    def test_wav_decode_skip_false_when_only_fingerprint_skip(
        self, tmp_path: Path
    ) -> None:
        """wav_decode_skip=False when only fingerprint_skip=True."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        db_path = _make_db(tmp_path)
        _seed_fingerprint(db_path, "VID00003")

        result = _check_already_processed("VID00003", transcript_dir, db_path)
        assert result.wav_decode_skip is False
