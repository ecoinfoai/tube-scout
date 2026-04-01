"""Tests for SegmenterService."""

from unittest.mock import patch

from tube_scout.services.segmenter import (
    SegmenterService,
    compare_with_retention,
)


class TestSegmenterService:
    """Tests for SegmenterService (T045)."""

    def test_segment_output_structure(self) -> None:
        service = SegmenterService()
        mock_segments = [
            {
                "segment_index": 0,
                "start_seconds": 0.0,
                "end_seconds": 120.0,
                "title": "Introduction",
                "summary": "Overview of the topic.",
                "difficulty_score": 0.2,
                "tags": ["introduction"],
            },
            {
                "segment_index": 1,
                "start_seconds": 120.0,
                "end_seconds": 360.0,
                "title": "Core Concepts",
                "summary": "Main content explanation.",
                "difficulty_score": 0.7,
                "tags": ["core", "theory"],
            },
        ]
        with patch.object(service, "_call_llm", return_value=mock_segments):
            result = service.segment_transcript(
                video_id="vid001",
                transcript_text="Full transcript text here...",
            )
        assert len(result) == 2
        assert result[0]["title"] == "Introduction"
        assert result[1]["difficulty_score"] == 0.7

    def test_difficulty_scoring(self) -> None:
        service = SegmenterService()
        mock_segments = [
            {
                "segment_index": 0,
                "start_seconds": 0.0,
                "end_seconds": 300.0,
                "title": "Complex Theory",
                "summary": "Advanced theoretical discussion.",
                "difficulty_score": 0.9,
                "tags": ["advanced", "theory"],
            },
        ]
        with patch.object(service, "_call_llm", return_value=mock_segments):
            result = service.segment_transcript(
                video_id="vid001",
                transcript_text="Complex content...",
            )
        assert result[0]["difficulty_score"] == 0.9
        assert 0.0 <= result[0]["difficulty_score"] <= 1.0

    def test_empty_transcript(self) -> None:
        service = SegmenterService()
        result = service.segment_transcript(
            video_id="vid001",
            transcript_text="",
        )
        assert result == []


class TestCompareWithRetention:
    """Tests for compare_with_retention (FR-006d)."""

    def test_overlap_detection(self) -> None:
        segments = [
            {
                "segment_index": 0,
                "title": "Intro",
                "start_seconds": 0.0,
                "end_seconds": 120.0,
                "difficulty_score": 0.2,
            },
            {
                "segment_index": 1,
                "title": "Core",
                "start_seconds": 120.0,
                "end_seconds": 360.0,
                "difficulty_score": 0.8,
            },
            {
                "segment_index": 2,
                "title": "Summary",
                "start_seconds": 360.0,
                "end_seconds": 600.0,
                "difficulty_score": 0.3,
            },
        ]
        # Hotspot at 50% (300s) falls in segment 1 (120-360s)
        hotspots = [
            {"elapsed_ratio": 0.5, "audience_watch_ratio": 1.6},
        ]
        results = compare_with_retention(segments, hotspots, 600)
        assert len(results) == 3
        # Segment 0 (0-0.2 ratio): no overlap
        assert results[0]["hotspot_count"] == 0
        assert results[0]["has_retention_issue"] is False
        # Segment 1 (0.2-0.6 ratio): hotspot at 0.5
        assert results[1]["hotspot_count"] == 1
        assert results[1]["has_retention_issue"] is True
        assert results[1]["predicted_difficulty"] == 0.8
        # Segment 2 (0.6-1.0 ratio): no overlap
        assert results[2]["hotspot_count"] == 0

    def test_empty_segments(self) -> None:
        hotspots = [{"elapsed_ratio": 0.5, "audience_watch_ratio": 1.5}]
        results = compare_with_retention([], hotspots, 600)
        assert results == []

    def test_empty_hotspots(self) -> None:
        segments = [
            {
                "segment_index": 0,
                "title": "Intro",
                "start_seconds": 0.0,
                "end_seconds": 120.0,
                "difficulty_score": 0.2,
            },
        ]
        results = compare_with_retention(segments, [], 600)
        assert results == []

    def test_zero_duration(self) -> None:
        segments = [
            {
                "segment_index": 0,
                "title": "X",
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "difficulty_score": 0.5,
            },
        ]
        hotspots = [{"elapsed_ratio": 0.5, "audience_watch_ratio": 1.5}]
        results = compare_with_retention(segments, hotspots, 0)
        assert results == []
