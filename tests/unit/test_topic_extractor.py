"""Tests for TopicExtractorService (T048, T049)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tube_scout.services.topic_extractor import TopicExtractorService

# --- Fixtures ---

def _make_comments(n: int = 5) -> list[dict[str, Any]]:
    """Generate test comments with varied topics."""
    samples = [
        {"comment_id": "c0", "text": "강의 음질이 너무 안 좋아요."},
        {"comment_id": "c1", "text": "설명이 정말 이해하기 쉬워요!"},
        {"comment_id": "c2", "text": "시험 범위가 어디까지인가요?"},
        {"comment_id": "c3", "text": "Audio quality is terrible."},
        {"comment_id": "c4", "text": "이 강의 시리즈 총 몇 개인가요?"},
    ]
    return samples[:n]


def _make_mock_adapter_for_topics() -> MagicMock:
    """Create a mock LLMAdapter that returns topic extraction results."""
    adapter = MagicMock()

    def fake_complete_json(
        system_prompt: str, user_prompt: str, schema: type
    ) -> MagicMock:
        import re

        ids = re.findall(r'"comment_id":\s*"(c\d+)"', user_prompt)
        results = []
        for cid in ids:
            results.append({
                "comment_id": cid,
                "topic_label": "audio quality",
                "sentiment": "negative",
                "confidence": 0.9,
                "is_question": cid in ("c2", "c4"),
                "question_text": "시험 범위가 어디까지인가요?" if cid == "c2" else (
                    "이 강의 시리즈 총 몇 개인가요?" if cid == "c4" else None
                ),
            })

        result = MagicMock()
        result.model_dump.return_value = {"results": results}
        return result

    adapter.complete_json.side_effect = fake_complete_json
    return adapter


# --- T048: Topic extraction tests ---

class TestTopicExtraction:
    """Tests for LLM-based topic extraction (T048)."""

    def test_extract_topics_returns_clusters(self) -> None:
        """Topic extraction returns TopicCluster list for given comments."""
        adapter = _make_mock_adapter_for_topics()
        service = TopicExtractorService()
        service._llm_adapter = adapter

        comments = _make_comments(3)
        clusters = service.extract_topics("vid001", comments)

        assert isinstance(clusters, list)
        assert len(clusters) > 0
        for cluster in clusters:
            assert "video_id" in cluster
            assert cluster["video_id"] == "vid001"
            assert "topic_label" in cluster
            assert "comment_ids" in cluster
            assert isinstance(cluster["comment_ids"], list)
            assert len(cluster["comment_ids"]) > 0
            assert "sentiment_distribution" in cluster
            dist = cluster["sentiment_distribution"]
            for key in ("positive", "neutral", "negative"):
                assert key in dist
            assert abs(sum(dist.values()) - 1.0) < 0.01
            assert "representative_comments" in cluster
            assert len(cluster["representative_comments"]) <= 3

    def test_batch_of_20_chunking(self) -> None:
        """Comments are processed in batches of 20 per LLM call."""
        adapter = _make_mock_adapter_for_topics()
        service = TopicExtractorService()
        service._llm_adapter = adapter

        # Create 45 comments
        comments = [
            {"comment_id": f"c{i}", "text": f"Comment about topic {i % 3}"}
            for i in range(45)
        ]
        service.extract_topics("vid001", comments)

        # Should be called 3 times: 20 + 20 + 5
        assert adapter.complete_json.call_count == 3

    def test_mixed_korean_english_topics(self) -> None:
        """Mixed Korean+English comments produce valid topics."""
        adapter = _make_mock_adapter_for_topics()
        service = TopicExtractorService()
        service._llm_adapter = adapter

        comments = [
            {"comment_id": "c0", "text": "Great audio quality!"},
            {"comment_id": "c1", "text": "음질이 너무 좋아요!"},
        ]
        clusters = service.extract_topics("vid001", comments)

        assert isinstance(clusters, list)
        for cluster in clusters:
            assert cluster["topic_label"]  # non-blank

    def test_single_comment_produces_cluster(self) -> None:
        """A single comment still produces a valid topic cluster."""
        adapter = _make_mock_adapter_for_topics()
        service = TopicExtractorService()
        service._llm_adapter = adapter

        comments = [{"comment_id": "c0", "text": "Great lecture!"}]
        clusters = service.extract_topics("vid001", comments)

        assert len(clusters) >= 1


# --- T049: Question extraction and hotspot cross-reference tests ---

class TestQuestionExtraction:
    """Tests for question identification and hotspot cross-reference (T049)."""

    def test_extract_questions_from_comments(self) -> None:
        """Questions are correctly identified from comment analysis."""
        adapter = _make_mock_adapter_for_topics()
        service = TopicExtractorService()
        service._llm_adapter = adapter

        comments = _make_comments(5)
        questions = service.extract_questions("vid001", comments)

        assert isinstance(questions, list)
        assert len(questions) >= 1
        for q in questions:
            assert "comment_id" in q
            assert "question_text" in q
            assert q["question_text"]  # non-blank

    def test_cross_reference_with_hotspots(self) -> None:
        """Questions matched to retention hotspots with relevance scores."""
        adapter = _make_mock_adapter_for_topics()
        service = TopicExtractorService()
        service._llm_adapter = adapter

        comments = _make_comments(5)
        hotspots = [
            {"elapsed_ratio": 0.3, "audience_watch_ratio": 1.5},
            {"elapsed_ratio": 0.7, "audience_watch_ratio": 1.8},
        ]

        matches = service.cross_reference_with_hotspots(
            "vid001", comments, hotspots
        )

        assert isinstance(matches, list)
        for match in matches:
            assert match["video_id"] == "vid001"
            assert "comment_id" in match
            assert "question_text" in match
            assert 0.0 <= match["matched_hotspot_start"] <= 1.0
            assert 0.0 <= match["matched_hotspot_end"] <= 1.0
            assert 0.0 <= match["relevance_score"] <= 1.0

    def test_no_questions_returns_empty_matches(self) -> None:
        """When no questions found, cross-reference returns empty list."""
        adapter = MagicMock()
        result = MagicMock()
        result.model_dump.return_value = {
            "results": [
                {
                    "comment_id": "c0",
                    "topic_label": "teaching",
                    "sentiment": "positive",
                    "confidence": 0.9,
                    "is_question": False,
                    "question_text": None,
                }
            ]
        }
        adapter.complete_json.return_value = result

        service = TopicExtractorService()
        service._llm_adapter = adapter

        comments = [{"comment_id": "c0", "text": "Great lecture!"}]
        hotspots = [{"elapsed_ratio": 0.5, "audience_watch_ratio": 1.3}]

        matches = service.cross_reference_with_hotspots(
            "vid001", comments, hotspots
        )
        assert matches == []

    def test_no_hotspots_returns_empty_matches(self) -> None:
        """When no hotspots, cross-reference returns empty list."""
        adapter = _make_mock_adapter_for_topics()
        service = TopicExtractorService()
        service._llm_adapter = adapter

        comments = _make_comments(5)
        matches = service.cross_reference_with_hotspots("vid001", comments, [])
        assert matches == []


# --- T055: Edge cases ---

class TestTopicExtractorEdgeCases:
    """Tests for edge cases: no comments, comments disabled (T055)."""

    def test_empty_comments_returns_empty_topics(self) -> None:
        """Empty comment list returns empty topic clusters, no error."""
        service = TopicExtractorService()
        clusters = service.extract_topics("vid001", [])
        assert clusters == []

    def test_empty_comments_returns_empty_questions(self) -> None:
        """Empty comment list returns empty questions, no error."""
        service = TopicExtractorService()
        questions = service.extract_questions("vid001", [])
        assert questions == []

    def test_empty_comments_cross_reference_returns_empty(self) -> None:
        """Empty comments with hotspots returns empty matches."""
        service = TopicExtractorService()
        hotspots = [{"elapsed_ratio": 0.5, "audience_watch_ratio": 1.3}]
        matches = service.cross_reference_with_hotspots("vid001", [], hotspots)
        assert matches == []

    def test_no_api_key_raises_clear_error(self) -> None:
        """Missing API key produces clear error message."""
        service = TopicExtractorService()
        comments = [{"comment_id": "c0", "text": "Test"}]

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="API key"):
                service.extract_topics("vid001", comments)
