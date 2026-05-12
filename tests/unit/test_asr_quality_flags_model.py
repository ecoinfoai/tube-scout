"""RED tests for AsrQualityFlags Pydantic model (spec 013 T011).

Ref: data-model.md §E-9.
"""

import json

import pytest
from pydantic import BaseModel

from tube_scout.models.content import AsrQualityFlags


def test_asr_quality_flags_is_pydantic_base_model() -> None:
    """AsrQualityFlags must be a Pydantic BaseModel subclass."""
    assert issubclass(AsrQualityFlags, BaseModel)


def test_asr_quality_flags_default_booleans_are_false() -> None:
    """All boolean fields default to False."""
    flags = AsrQualityFlags()
    assert flags.hallucination_repeat is False
    assert flags.vad_over_truncated is False
    assert flags.language_mismatch is False
    assert flags.short_segments_excess is False
    assert flags.silence_hallucination is False


def test_asr_quality_flags_default_int_is_zero() -> None:
    """compression_ratio_violations defaults to 0."""
    flags = AsrQualityFlags()
    assert flags.compression_ratio_violations == 0


def test_asr_quality_flags_has_all_6_fields() -> None:
    """All 6 spec-defined fields must be present on the model."""
    expected = {
        "hallucination_repeat",
        "vad_over_truncated",
        "language_mismatch",
        "short_segments_excess",
        "silence_hallucination",
        "compression_ratio_violations",
    }
    assert expected <= set(AsrQualityFlags.model_fields)


def test_asr_quality_flags_serializes_to_json() -> None:
    """model_dump_json() must produce valid JSON with all 6 keys."""
    flags = AsrQualityFlags()
    payload = json.loads(flags.model_dump_json())
    assert "hallucination_repeat" in payload
    assert "compression_ratio_violations" in payload


def test_asr_quality_flags_accepts_extra_keys() -> None:
    """model_config extra=allow: unknown fields must not raise."""
    flags = AsrQualityFlags(future_flag=True)
    assert flags.future_flag is True  # type: ignore[attr-defined]
