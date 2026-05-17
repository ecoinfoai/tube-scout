"""Unit tests for _persist_transcript() — spec 018 T010 RED.

Tests atomic write semantics, 7-key schema, tmp residue cleanup,
mtime update on second call, and PermissionError fail-fast (Principle II).
"""

import json
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tube_scout.services.unified_ingest import _persist_transcript


def _make_asr_result(video_id: str = "VID00001") -> MagicMock:
    asr = MagicMock()
    asr.caption_source_detail = "asr:faster-whisper:large-v3:int8_float16"
    asr.language_detected = "ko"
    asr.duration = 5.0
    asr.segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "안녕하세요",
            "compression_ratio": 1.2,
            "no_speech_prob": 0.01,
        }
    ]
    asr.asr_quality_flags = MagicMock()
    asr.asr_quality_flags.model_dump.return_value = {
        "hallucination_repeat": False,
        "vad_over_truncated": False,
        "language_mismatch": False,
        "short_segments_excess": False,
        "silence_hallucination": False,
        "compression_ratio_violations": 0,
    }
    return asr


def test_persist_transcript_atomic_write(tmp_path: Path) -> None:
    """_persist_transcript calls tempfile.mkstemp + os.replace (atomic write)."""
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    asr = _make_asr_result()
    ts = "2026-05-16T00:00:00+00:00"

    with (
        patch("tube_scout.services.unified_ingest.tempfile") as mock_tf,
        patch("tube_scout.services.unified_ingest.os") as mock_os,
    ):
        tmp_file_path = tmp_path / "tmp_file"
        tmp_file_path.touch()
        fd = tmp_file_path.open("w")
        mock_tf.mkstemp.return_value = (fd.fileno(), str(tmp_file_path))
        mock_os.fdopen.return_value.__enter__ = lambda s: s
        mock_os.fdopen.return_value.__exit__ = lambda *a: None
        mock_os.replace.return_value = None

        _persist_transcript(transcript_dir, "VID00001", asr, ts)

        mock_tf.mkstemp.assert_called_once()
        mock_os.replace.assert_called_once()


def test_persist_transcript_7_key_schema(tmp_path: Path) -> None:
    """Written JSON contains exactly 7 top-level keys matching contract §2."""
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    asr = _make_asr_result()
    ts = "2026-05-16T00:00:00+00:00"

    result_path = _persist_transcript(transcript_dir, "VID00001", asr, ts)

    data = json.loads(result_path.read_text(encoding="utf-8"))
    expected_keys = {"video_id", "source", "language", "duration", "segments",
                     "asr_quality_flags", "fetched_at"}
    assert set(data.keys()) == expected_keys


def test_persist_transcript_no_tmp_residue(tmp_path: Path) -> None:
    """No .tmp files remain after successful write (SC-018-2)."""
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    asr = _make_asr_result()
    ts = "2026-05-16T00:00:00+00:00"

    _persist_transcript(transcript_dir, "VID00001", asr, ts)

    tmp_files = list(transcript_dir.glob("*.tmp"))
    assert tmp_files == [], f"unexpected .tmp residue: {tmp_files}"


def test_persist_transcript_second_call_updates_mtime(tmp_path: Path) -> None:
    """Second call with same video_id overwrites the file (force semantics)."""
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    asr = _make_asr_result()
    ts1 = "2026-05-16T00:00:00+00:00"
    ts2 = "2026-05-16T01:00:00+00:00"

    path1 = _persist_transcript(transcript_dir, "VID00001", asr, ts1)
    mtime1 = path1.stat().st_mtime

    path2 = _persist_transcript(transcript_dir, "VID00001", asr, ts2)
    mtime2 = path2.stat().st_mtime

    assert path1 == path2
    # fetched_at differs → json differs → file is replaced → mtime changes
    data = json.loads(path2.read_text())
    assert data["fetched_at"] == ts2
    assert mtime2 >= mtime1


def test_persist_transcript_permission_error_no_residue(tmp_path: Path) -> None:
    """PermissionError raised when transcript_dir unwritable; no partial residue."""
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    transcript_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read+exec only

    asr = _make_asr_result()
    ts = "2026-05-16T00:00:00+00:00"

    try:
        with pytest.raises((PermissionError, OSError)):
            _persist_transcript(transcript_dir, "VID00001", asr, ts)

        tmp_files = list(transcript_dir.glob("*.tmp"))
        assert tmp_files == [], f"partial write residue: {tmp_files}"
    finally:
        transcript_dir.chmod(stat.S_IRWXU)
