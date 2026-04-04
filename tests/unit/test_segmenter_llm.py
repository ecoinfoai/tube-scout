"""Tests for LLM-based transcript segmentation (T056, T057, T063a)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from tube_scout.services.segmenter import (
    SegmenterService,
    compare_with_retention,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_adapter_mock(response_data: list[dict] | dict) -> MagicMock:
    """Create a mock LLMAdapter that returns given data from complete_json.

    Args:
        response_data: Data to wrap in a Pydantic-like response.

    Returns:
        Mocked LLMAdapter instance.
    """
    adapter = MagicMock()

    def _complete_json(
        system_prompt: str, user_prompt: str, schema: type[BaseModel],
    ) -> BaseModel:
        # Build the dict the schema expects
        if isinstance(response_data, list):
            payload = {"chapters": response_data}
        else:
            payload = response_data
        return schema.model_validate(payload)

    adapter.complete_json.side_effect = _complete_json
    return adapter


ENGLISH_SEGMENTS = [
    {
        "segment_index": 0,
        "start_seconds": 0.0,
        "end_seconds": 120.0,
        "title": "Introduction",
        "summary": "Overview of the lecture topic.",
        "difficulty_score": 0.2,
        "tags": ["introduction", "overview", "basics"],
    },
    {
        "segment_index": 1,
        "start_seconds": 120.0,
        "end_seconds": 360.0,
        "title": "Core Concepts",
        "summary": "Detailed explanation of main concepts.",
        "difficulty_score": 0.7,
        "tags": ["theory", "concepts", "analysis"],
    },
    {
        "segment_index": 2,
        "start_seconds": 360.0,
        "end_seconds": 600.0,
        "title": "Advanced Applications",
        "summary": "Real-world applications and case studies.",
        "difficulty_score": 0.9,
        "tags": ["applications", "advanced", "case-study"],
    },
]

KOREAN_SEGMENTS = [
    {
        "segment_index": 0,
        "start_seconds": 0.0,
        "end_seconds": 180.0,
        "title": "서론",
        "summary": "강의 주제에 대한 개요입니다.",
        "difficulty_score": 0.3,
        "tags": ["서론", "개요"],
    },
    {
        "segment_index": 1,
        "start_seconds": 180.0,
        "end_seconds": 600.0,
        "title": "핵심 개념",
        "summary": "주요 개념에 대한 상세한 설명입니다.",
        "difficulty_score": 0.8,
        "tags": ["이론", "개념", "분석"],
    },
]


# ===========================================================================
# T056 — LLM-based segmentation with mocked LLMAdapter
# ===========================================================================

class TestSegmenterLLMBasic:
    """T056: LLM-based segmentation with mocked LLMAdapter."""

    def test_transcript_segmented_into_chapters(self) -> None:
        """Transcript is segmented into chapters with title, summary, difficulty."""
        adapter = _make_llm_adapter_mock(ENGLISH_SEGMENTS)
        service = SegmenterService(llm=adapter)

        result = service.segment_transcript("vid001", "Full transcript text here...")

        assert len(result) == 3
        for seg in result:
            assert "title" in seg
            assert "summary" in seg
            assert "difficulty_score" in seg
            assert "start_seconds" in seg
            assert "end_seconds" in seg
            assert "tags" in seg

    def test_topic_tags_generated_per_segment(self) -> None:
        """Each segment has 1-5 topic tags."""
        adapter = _make_llm_adapter_mock(ENGLISH_SEGMENTS)
        service = SegmenterService(llm=adapter)

        result = service.segment_transcript("vid001", "Full transcript text here...")

        for seg in result:
            assert isinstance(seg["tags"], list)
            assert 1 <= len(seg["tags"]) <= 5

    def test_korean_transcript_produces_korean_summaries(self) -> None:
        """Korean transcript produces Korean-language summaries."""
        adapter = _make_llm_adapter_mock(KOREAN_SEGMENTS)
        service = SegmenterService(llm=adapter)

        result = service.segment_transcript(
            "vid_kr",
            "안녕하세요. 오늘 강의에서는 인공지능의 기초에 대해 알아보겠습니다.",
        )

        assert len(result) == 2
        # Summaries should be Korean
        assert "개요" in result[0]["summary"]

    def test_empty_transcript_returns_empty(self) -> None:
        """Empty transcript returns empty result without calling LLM."""
        adapter = _make_llm_adapter_mock([])
        service = SegmenterService(llm=adapter)

        result = service.segment_transcript("vid001", "")

        assert result == []
        adapter.complete_json.assert_not_called()

    def test_whitespace_only_transcript_returns_empty(self) -> None:
        """Whitespace-only transcript returns empty result."""
        adapter = _make_llm_adapter_mock([])
        service = SegmenterService(llm=adapter)

        result = service.segment_transcript("vid001", "   \n\t  ")

        assert result == []
        adapter.complete_json.assert_not_called()


# ===========================================================================
# T057 — Difficulty prediction and retention comparison
# ===========================================================================

class TestDifficultyAndRetention:
    """T057: Difficulty scores and retention comparison."""

    def test_difficulty_scores_are_bounded(self) -> None:
        """All difficulty scores are in [0.0, 1.0]."""
        adapter = _make_llm_adapter_mock(ENGLISH_SEGMENTS)
        service = SegmenterService(llm=adapter)

        result = service.segment_transcript("vid001", "Some transcript content.")

        for seg in result:
            assert 0.0 <= seg["difficulty_score"] <= 1.0

    def test_compare_with_retention_hotspot_overlap(self) -> None:
        """compare_with_retention cross-references difficulty with hotspots."""
        segments = [
            {
                "segment_index": 0,
                "title": "Easy Intro",
                "start_seconds": 0.0,
                "end_seconds": 120.0,
                "difficulty_score": 0.2,
            },
            {
                "segment_index": 1,
                "title": "Hard Section",
                "start_seconds": 120.0,
                "end_seconds": 360.0,
                "difficulty_score": 0.9,
            },
        ]
        hotspots = [
            {"elapsed_ratio": 0.4, "audience_watch_ratio": 1.8},  # 240s / 600s
        ]

        results = compare_with_retention(segments, hotspots, 600)

        assert len(results) == 2
        # Segment 0 (0.0-0.2 ratio): no hotspot overlap
        assert results[0]["has_retention_issue"] is False
        assert results[0]["hotspot_count"] == 0
        # Segment 1 (0.2-0.6 ratio): hotspot at 0.4
        assert results[1]["has_retention_issue"] is True
        assert results[1]["hotspot_count"] == 1
        assert results[1]["predicted_difficulty"] == 0.9

    def test_compare_with_retention_skip_zone_overlap(self) -> None:
        """compare_with_retention detects skip zone overlaps."""
        segments = [
            {
                "segment_index": 0,
                "title": "Intro",
                "start_seconds": 0.0,
                "end_seconds": 300.0,
                "difficulty_score": 0.1,
            },
        ]
        # Skip zone at beginning
        hotspots = [
            {"elapsed_ratio": 0.05, "audience_watch_ratio": 0.3, "is_skip_zone": True},
        ]

        results = compare_with_retention(segments, hotspots, 600)

        assert results[0]["has_retention_issue"] is True


# ===========================================================================
# T063 — Malformed LLM response handling
# ===========================================================================

class TestMalformedLLMResponse:
    """T063: Handling of malformed LLM responses."""

    def test_llm_raises_value_error_service_propagates(self) -> None:
        """If LLMAdapter.complete_json raises ValueError, service raises."""
        adapter = MagicMock()
        adapter.complete_json.side_effect = ValueError("Failed to parse LLM response")
        service = SegmenterService(llm=adapter)

        with pytest.raises(ValueError, match="Failed to parse"):
            service.segment_transcript("vid001", "Some text.")

    def test_no_llm_configured_raises_not_implemented(self) -> None:
        """Without LLM adapter, segment_transcript raises."""
        service = SegmenterService()

        with pytest.raises(NotImplementedError, match="LLM backend"):
            service.segment_transcript("vid001", "Some text.")


# ===========================================================================
# T063a — Boundary accuracy with reference segmentation
# ===========================================================================

class TestBoundaryAccuracy:
    """T063a: Boundary accuracy against reference segmentation."""

    @pytest.fixture()
    def reference_data(self) -> dict:
        """Load reference segmentation fixture."""
        fixture_path = (
            Path(__file__).parent.parent
            / "fixtures"
            / "reference_segmentation.json"
        )
        with open(fixture_path) as f:
            return json.load(f)

    def test_boundary_alignment_within_tolerance(self, reference_data: dict) -> None:
        """LLM segmentation aligns within 30s tolerance for >= 70% of segments."""
        ref_segments = reference_data["reference_segments"]

        # Mock LLM returns segments reasonably aligned with reference
        llm_segments = [
            {
                "segment_index": 0,
                "start_seconds": 0.0,
                "end_seconds": 55.0,  # ref: 60.0, diff = 5s < 30s
                "title": "Introduction to ML",
                "summary": "Overview of machine learning.",
                "difficulty_score": 0.3,
                "tags": ["ml", "intro", "basics"],
            },
            {
                "segment_index": 1,
                "start_seconds": 55.0,
                "end_seconds": 190.0,  # ref: 180.0, diff = 10s < 30s
                "title": "Linear Regression",
                "summary": "Cost functions and gradient descent.",
                "difficulty_score": 0.6,
                "tags": ["regression", "cost-function", "gradient-descent"],
            },
            {
                "segment_index": 2,
                "start_seconds": 190.0,
                "end_seconds": 295.0,  # ref: 300.0, diff = 5s < 30s
                "title": "Classification",
                "summary": "Logistic regression and sigmoid function.",
                "difficulty_score": 0.7,
                "tags": ["classification", "logistic-regression", "sigmoid"],
            },
        ]

        adapter = _make_llm_adapter_mock(llm_segments)
        service = SegmenterService(llm=adapter)

        result = service.segment_transcript(
            reference_data["video_id"],
            reference_data["transcript"],
        )

        assert len(result) == len(ref_segments)

        # Check boundary alignment: at least 70% of end boundaries within 30s
        tolerance = 30.0
        aligned = 0
        for predicted, reference in zip(result, ref_segments):
            if abs(predicted["end_seconds"] - reference["end_seconds"]) <= tolerance:
                aligned += 1

        alignment_ratio = aligned / len(ref_segments)
        assert alignment_ratio >= 0.7, (
            f"Only {aligned}/{len(ref_segments)} segments aligned "
            f"within {tolerance}s tolerance ({alignment_ratio:.0%} < 70%)"
        )
