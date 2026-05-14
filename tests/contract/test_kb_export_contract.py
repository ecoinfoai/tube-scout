"""T082 RED — contract test for services/kb_export.py."""
import inspect
import json
import tempfile
from pathlib import Path

import pytest


def _make_transcript_json(tmp_path: Path, video_id: str = "vid001") -> Path:
    data = {
        "video_id": video_id,
        "source": "captions_api_auto",
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "segments": [
            {"start": 0.0, "end": 3.0, "text": "안녕하세요"},
            {"start": 3.0, "end": 7.0, "text": "오늘 강의입니다"},
        ],
    }
    p = tmp_path / f"{video_id}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_export_signature_matches_contract() -> None:
    """export_transcript must accept the 7 parameters defined in the contract."""
    from tube_scout.services.kb_export import export_transcript

    sig = inspect.signature(export_transcript)
    params = sig.parameters

    assert "transcript_json_path" in params
    assert "output_path" in params
    assert "format_" in params
    assert "keep_timestamps" in params
    assert "clean_fillers" in params
    assert "with_meta" in params
    assert "video_meta" in params

    assert params["format_"].default == "txt"
    assert params["keep_timestamps"].default is False
    assert params["clean_fillers"].default is False
    assert params["with_meta"].default is False
    assert params["video_meta"].default is None


def test_export_result_byte_count_matches_file_size(tmp_path: Path) -> None:
    """ExportResult.byte_count must equal the actual bytes written to output_path."""
    from tube_scout.services.kb_export import export_transcript

    transcript_path = _make_transcript_json(tmp_path)
    output_path = tmp_path / "out.txt"

    result = export_transcript(transcript_path, output_path)

    assert output_path.exists()
    assert result.byte_count == output_path.stat().st_size
    assert result.byte_count > 0
    assert result.output_path == output_path
    assert result.segment_count == 2
