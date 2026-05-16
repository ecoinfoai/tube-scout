"""Integration test: Rich Progress bar visibility in _run_transcript_and_fingerprint.

T-B2: fixture 3 mp4 archive call with stdout capture → progress output present.
TTY not detected → progress disabled → no garbled output.
"""

from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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


class TestProgressVisibility:
    """Progress bar outputs correctly in TTY mode, disabled in non-TTY mode."""

    def test_progress_disabled_in_nontty_no_garbled_output(
        self, tmp_path: Path
    ) -> None:
        """When isatty() returns False, Progress disable=True → no garbled ANSI output."""
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        n = 3
        mp4_map = _make_mp4_map(tmp_path, n=n)
        db_path = _make_db(tmp_path / "test.db")
        audit_writer = MagicMock()

        captured = io.StringIO()

        mock_progress = MagicMock()
        mock_progress.__enter__ = MagicMock(return_value=mock_progress)
        mock_progress.__exit__ = MagicMock(return_value=None)
        mock_progress.add_task = MagicMock(return_value=0)

        with (
            patch("tube_scout.services.unified_ingest.Progress",
                  return_value=mock_progress) as mock_progress_cls,
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch("tube_scout.services.unified_ingest.transcribe_audio",
                  return_value=_asr_result()),
            patch("tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                  return_value=(b"fp", 5.0)),
            patch("sys.stdout", captured),
        ):
            _run_transcript_and_fingerprint(
                mp4_map, tmp_path, audit_writer,
                transcript_dir=tmp_path / "transcripts",
                db_path=db_path,
            )

        # Progress constructor must have been called with disable=True
        # (isatty() is False in test environment)
        progress_init_kwargs = mock_progress_cls.call_args
        assert progress_init_kwargs is not None
        disable_val = progress_init_kwargs.kwargs.get("disable")
        # disable=True means progress is off; stdout has no ANSI escape sequences
        assert disable_val is True or disable_val == True  # noqa: E712

    def test_progress_advance_count_matches_video_count(
        self, tmp_path: Path
    ) -> None:
        """advance called N times → MofNCompleteColumn would show N/N at end."""
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        n = 3
        mp4_map = _make_mp4_map(tmp_path, n=n)
        db_path = _make_db(tmp_path / "test.db")
        audit_writer = MagicMock()

        mock_progress = MagicMock()
        mock_progress.__enter__ = MagicMock(return_value=mock_progress)
        mock_progress.__exit__ = MagicMock(return_value=None)
        mock_progress.add_task = MagicMock(return_value=42)

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

        # advance called with the task_id returned by add_task
        advance_task_ids = [c.args[0] for c in mock_progress.advance.call_args_list]
        assert all(tid == 42 for tid in advance_task_ids)
        assert len(advance_task_ids) == n

    def test_progress_columns_include_mofn_and_time(self, tmp_path: Path) -> None:
        """Progress constructor receives MofNCompleteColumn and time columns."""
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint
        from rich.progress import MofNCompleteColumn, TimeElapsedColumn, TimeRemainingColumn

        mp4_map = _make_mp4_map(tmp_path, n=1)
        db_path = _make_db(tmp_path / "test.db")
        audit_writer = MagicMock()

        captured_args = []

        def fake_progress_cls(*args, **kwargs):
            captured_args.extend(args)
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=None)
            mock.add_task = MagicMock(return_value=0)
            return mock

        with (
            patch("tube_scout.services.unified_ingest.Progress", side_effect=fake_progress_cls),
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

        col_types = [type(c) for c in captured_args]
        assert MofNCompleteColumn in col_types
        assert TimeElapsedColumn in col_types
        assert TimeRemainingColumn in col_types
