"""Contract test: transcript artifact schema equivalence — spec 018 T012 RED.

Verifies FR-018H / SC-018-5: 분리 명령 vs 통합 명령 산출물의 키 집합 동치.
Top-level 7 keys + asr_quality_flags 6 keys + segment object keys must match.

This test is RED until _persist_transcript() is implemented (T014).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tube_scout.services.unified_ingest import _persist_transcript


EXPECTED_TOP_LEVEL_KEYS = frozenset({
    "video_id", "source", "language", "duration",
    "segments", "asr_quality_flags", "fetched_at",
})

EXPECTED_ASR_QUALITY_FLAG_KEYS = frozenset({
    "hallucination_repeat",
    "vad_over_truncated",
    "language_mismatch",
    "short_segments_excess",
    "silence_hallucination",
    "compression_ratio_violations",
})

EXPECTED_SEGMENT_KEYS = frozenset({
    "start", "end", "text", "compression_ratio", "no_speech_prob",
})


def _make_asr_result() -> MagicMock:
    asr = MagicMock()
    asr.caption_source_detail = "asr:faster-whisper:large-v3:int8_float16"
    asr.language_detected = "ko"
    asr.duration = 5.0
    asr.segments = [
        {
            "start": 0.0,
            "end": 2.5,
            "text": "테스트 자막",
            "compression_ratio": 1.1,
            "no_speech_prob": 0.02,
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


def test_transcript_artifact_top_level_keys(tmp_path: Path) -> None:
    """Unified command transcript JSON has exactly 7 top-level keys (contract §2)."""
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    asr = _make_asr_result()
    ts = "2026-05-16T00:00:00+00:00"

    path = _persist_transcript(transcript_dir, "VID00001", asr, ts)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert set(data.keys()) == EXPECTED_TOP_LEVEL_KEYS


def test_transcript_artifact_asr_quality_flags_keys(tmp_path: Path) -> None:
    """asr_quality_flags has exactly 6 required flag keys (contract §3)."""
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    asr = _make_asr_result()
    ts = "2026-05-16T00:00:00+00:00"

    path = _persist_transcript(transcript_dir, "VID00001", asr, ts)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert set(data["asr_quality_flags"].keys()) == EXPECTED_ASR_QUALITY_FLAG_KEYS


def test_transcript_artifact_segment_keys(tmp_path: Path) -> None:
    """Segment objects have exactly the required keys (contract §2.1)."""
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    asr = _make_asr_result()
    ts = "2026-05-16T00:00:00+00:00"

    path = _persist_transcript(transcript_dir, "VID00001", asr, ts)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert len(data["segments"]) > 0
    assert set(data["segments"][0].keys()) == EXPECTED_SEGMENT_KEYS


def test_transcript_artifact_schema_equivalence(tmp_path: Path) -> None:
    """Schema-for-schema equivalence: unified command matches separate command keys.

    Simulates the separate command output (hardcoded reference dict) and
    compares key sets with unified command output (contract §4 / FR-018H).
    """
    # Reference: keys produced by separate 'collect transcripts' command
    # (cli/collect.py:2257-2266 pattern)
    reference_keys = {"video_id", "source", "language", "duration",
                      "segments", "asr_quality_flags", "fetched_at"}
    reference_flag_keys = {
        "hallucination_repeat", "vad_over_truncated", "language_mismatch",
        "short_segments_excess", "silence_hallucination", "compression_ratio_violations",
    }
    reference_segment_keys = {"start", "end", "text", "compression_ratio", "no_speech_prob"}

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    asr = _make_asr_result()
    ts = "2026-05-16T00:00:00+00:00"

    path = _persist_transcript(transcript_dir, "VID00001", asr, ts)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert set(data.keys()) == reference_keys
    assert set(data["asr_quality_flags"].keys()) == reference_flag_keys
    if data["segments"]:
        assert set(data["segments"][0].keys()) == reference_segment_keys
