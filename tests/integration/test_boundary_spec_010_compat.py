"""T020 RED — B-X1-1 boundary: srv3 output JSON compatible with spec 010 consumers.

Verifies that the transcript JSON produced by srv3_to_transcript_json can be
consumed by spec 010 pipeline code (segmenter.py) without conversion.
"""
import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "spec012"
AUTO_FIXTURE = FIXTURE_DIR / "auto_track.ko-orig.srv3"


def _make_srv3_json(video_id: str = "BOUNDARY001") -> dict:
    from tube_scout.services.srv3_parser import srv3_to_transcript_json
    return srv3_to_transcript_json(
        AUTO_FIXTURE.read_text(encoding="utf-8"),
        video_id=video_id,
        source="ytdlp:auto",
    )


def test_b_x1_1_required_top_level_fields() -> None:
    """B-X1-1: srv3 JSON has video_id, language, source, fetched_at, segments."""
    data = _make_srv3_json()
    assert "video_id" in data
    assert "language" in data
    assert "source" in data
    assert "fetched_at" in data
    assert "segments" in data
    assert isinstance(data["segments"], list)
    assert len(data["segments"]) > 0


def test_b_x1_1_segment_schema() -> None:
    """B-X1-1: each segment has start (float), end (float), text (non-empty str)."""
    data = _make_srv3_json()
    for seg in data["segments"]:
        assert isinstance(seg["start"], float), f"start not float: {seg}"
        assert isinstance(seg["end"], float), f"end not float: {seg}"
        assert isinstance(seg["text"], str) and seg["text"].strip(), f"text empty: {seg}"
        assert seg["end"] > seg["start"], f"end <= start: {seg}"


def test_b_x1_1_json_roundtrip(tmp_path: Path) -> None:
    """B-X1-1: JSON serialization and deserialization preserves all fields."""
    data = _make_srv3_json()
    json_path = tmp_path / "BOUNDARY001.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["video_id"] == data["video_id"]
    assert len(loaded["segments"]) == len(data["segments"])
    # Verify first and last segment survive round-trip
    assert loaded["segments"][0] == data["segments"][0]
    assert loaded["segments"][-1] == data["segments"][-1]


def test_b_x1_1_segmenter_accepts_srv3_json() -> None:
    """B-X1-1: spec 011 segmenter.py can ingest srv3 transcript JSON structure."""
    from tube_scout.services.segmenter import segment_transcript

    data = _make_srv3_json()
    # segmenter expects list of segment dicts with 'text', 'start', 'end'
    # srv3 output uses 'start'/'end' keys — must be accepted as-is
    result = segment_transcript(data["segments"], video_id=data["video_id"])
    assert isinstance(result, list)
    assert len(result) > 0
