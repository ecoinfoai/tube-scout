"""Unit tests for Rich Progress bar in _run_transcript_and_fingerprint (Task B RED)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUDIO_FP_SQL = """
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id TEXT PRIMARY KEY,
    fingerprint BLOB,
    duration_seconds REAL,
    captured_at TEXT
);
"""


def _make_db(path: Path) -> Path:
    with sqlite3.connect(path) as conn:
        conn.execute(_AUDIO_FP_SQL)
    return path


def _asr_result() -> MagicMock:
    return MagicMock(
        caption_source_detail="asr:faster-whisper:large-v3:int8_float16",
        language_detected="ko",
        duration=5.0,
        segments=[],
        asr_quality_flags=MagicMock(model_dump=lambda: {
            "hallucination_repeat": False,
            "vad_over_truncated": False,
            "language_mismatch": False,
            "short_segments_excess": False,
            "silence_hallucination": False,
            "compression_ratio_violations": 0,
        }),
    )


def _make_mp4_map(tmp_path: Path, n: int = 3) -> dict[str, str]:
    mp4_dir = tmp_path / "mp4"
    mp4_dir.mkdir()
    result = {}
    for i in range(n):
        mp4 = mp4_dir / f"vid{i:03d}.mp4"
        mp4.write_bytes(b"fake")
        result[str(mp4)] = f"VID{i:05d}"
    return result


# ---------------------------------------------------------------------------
# T-B1: progress.add_task + progress.advance call count
# ---------------------------------------------------------------------------

class TestProgressBarCalls:
    """Rich Progress add_task + advance wired in _run_transcript_and_fingerprint."""

    def test_add_task_called_with_correct_total(self, tmp_path: Path) -> None:
        """progress.add_task receives total=len(mp4_video_id_map)."""
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        n = 3
        mp4_map = _make_mp4_map(tmp_path, n=n)
        db_path = _make_db(tmp_path / "test.db")
        audit_writer = MagicMock()

        mock_progress = MagicMock()
        mock_progress.__enter__ = MagicMock(return_value=mock_progress)
        mock_progress.__exit__ = MagicMock(return_value=None)
        mock_progress.add_task = MagicMock(return_value=0)

        with (
            patch("tube_scout.services.unified_ingest.Progress",
                  return_value=mock_progress),
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch("tube_scout.services.unified_ingest.transcribe_audio",
                  return_value=_asr_result()),
            patch("tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                  return_value=(b"fp", 5.0)),
        ):
            _run_transcript_and_fingerprint(
                mp4_map, tmp_path, audit_writer,
                transcript_dir=tmp_path / "transcripts",
                db_path=db_path,
            )

        mock_progress.add_task.assert_called_once()
        call_kwargs = mock_progress.add_task.call_args
        total = call_kwargs.kwargs.get("total", None)
        if total is None and len(call_kwargs.args) >= 2:
            total = call_kwargs.args[1]
        assert total == n

    def test_advance_called_once_per_video(self, tmp_path: Path) -> None:
        """progress.advance is called exactly N times for N videos."""
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        n = 3
        mp4_map = _make_mp4_map(tmp_path, n=n)
        db_path = _make_db(tmp_path / "test.db")
        audit_writer = MagicMock()

        mock_progress = MagicMock()
        mock_progress.__enter__ = MagicMock(return_value=mock_progress)
        mock_progress.__exit__ = MagicMock(return_value=None)
        mock_progress.add_task = MagicMock(return_value=0)

        with (
            patch("tube_scout.services.unified_ingest.Progress",
                  return_value=mock_progress),
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch("tube_scout.services.unified_ingest.transcribe_audio",
                  return_value=_asr_result()),
            patch("tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                  return_value=(b"fp", 5.0)),
        ):
            _run_transcript_and_fingerprint(
                mp4_map, tmp_path, audit_writer,
                transcript_dir=tmp_path / "transcripts",
                db_path=db_path,
            )

        assert mock_progress.advance.call_count == n

    def test_advance_called_for_skipped_videos(self, tmp_path: Path) -> None:
        """progress.advance called even when wav_decode_skip=True."""
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        n = 2
        mp4_map = _make_mp4_map(tmp_path, n=n)
        db_path = _make_db(tmp_path / "test.db")
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()

        for video_id in mp4_map.values():
            (transcript_dir / f"{video_id}.json").write_text("{}")
        with sqlite3.connect(db_path) as conn:
            for video_id in mp4_map.values():
                conn.execute(
                    "INSERT INTO audio_fingerprint VALUES (?, ?, ?, ?)",
                    (video_id, b"fp", 5.0, "2026-01-01T00:00:00+00:00"),
                )

        audit_writer = MagicMock()

        mock_progress = MagicMock()
        mock_progress.__enter__ = MagicMock(return_value=mock_progress)
        mock_progress.__exit__ = MagicMock(return_value=None)
        mock_progress.add_task = MagicMock(return_value=0)

        with patch("tube_scout.services.unified_ingest.Progress",
                   return_value=mock_progress):
            _run_transcript_and_fingerprint(
                mp4_map, tmp_path, audit_writer,
                transcript_dir=transcript_dir,
                db_path=db_path,
            )

        assert mock_progress.advance.call_count == n

    def test_description_updated_per_video(self, tmp_path: Path) -> None:
        """progress.update sets description containing video_id for each video."""
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        n = 2
        mp4_map = _make_mp4_map(tmp_path, n=n)
        db_path = _make_db(tmp_path / "test.db")
        audit_writer = MagicMock()

        mock_progress = MagicMock()
        mock_progress.__enter__ = MagicMock(return_value=mock_progress)
        mock_progress.__exit__ = MagicMock(return_value=None)
        mock_progress.add_task = MagicMock(return_value=0)

        with (
            patch("tube_scout.services.unified_ingest.Progress",
                  return_value=mock_progress),
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch("tube_scout.services.unified_ingest.transcribe_audio",
                  return_value=_asr_result()),
            patch("tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                  return_value=(b"fp", 5.0)),
        ):
            _run_transcript_and_fingerprint(
                mp4_map, tmp_path, audit_writer,
                transcript_dir=tmp_path / "transcripts",
                db_path=db_path,
            )

        update_calls = mock_progress.update.call_args_list
        descriptions = [
            c.kwargs.get("description", "")
            for c in update_calls
            if "description" in c.kwargs
        ]
        assert len(descriptions) == n
        video_ids = list(mp4_map.values())
        for desc, vid in zip(descriptions, video_ids):
            assert vid[:11] in desc
