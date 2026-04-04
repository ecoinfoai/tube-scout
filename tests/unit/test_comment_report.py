"""Tests for CommentReportGenerator (T078)."""

from pathlib import Path
from typing import Any

import pytest

from tube_scout.reporting.comment_report import CommentReportGenerator


@pytest.fixture
def sample_topics() -> list[dict[str, Any]]:
    """Sample topic cluster data."""
    return [
        {
            "video_id": "vid001",
            "topic_label": "audio quality",
            "comment_ids": ["c1", "c2", "c3"],
            "sentiment_distribution": {
                "positive": 0.0,
                "neutral": 0.3333,
                "negative": 0.6667,
            },
            "representative_comments": [
                "음질이 너무 안 좋아요.",
                "Audio is terrible.",
                "소리가 잘 안 들려요.",
            ],
        },
        {
            "video_id": "vid001",
            "topic_label": "teaching style",
            "comment_ids": ["c4", "c5"],
            "sentiment_distribution": {
                "positive": 1.0,
                "neutral": 0.0,
                "negative": 0.0,
            },
            "representative_comments": [
                "설명이 정말 이해하기 쉬워요!",
                "Great explanation, very clear!",
            ],
        },
        {
            "video_id": "vid001",
            "topic_label": "exam schedule",
            "comment_ids": ["c6"],
            "sentiment_distribution": {
                "positive": 0.0,
                "neutral": 1.0,
                "negative": 0.0,
            },
            "representative_comments": [
                "시험 범위가 어디까지인가요?",
            ],
        },
    ]


@pytest.fixture
def sample_questions() -> dict[str, Any]:
    """Sample question extraction data."""
    return {
        "questions": [
            {
                "comment_id": "c6",
                "question_text": "시험 범위가 어디까지인가요?",
            },
            {
                "comment_id": "c7",
                "question_text": "이 강의 시리즈 총 몇 개인가요?",
            },
            {
                "comment_id": "c8",
                "question_text": "교재 이름이 뭔가요?",
            },
        ],
        "hotspot_matches": [
            {
                "video_id": "vid001",
                "comment_id": "c6",
                "question_text": "시험 범위가 어디까지인가요?",
                "matched_hotspot_start": 0.65,
                "matched_hotspot_end": 0.75,
                "relevance_score": 0.9,
            },
        ],
    }


@pytest.fixture
def sample_video_meta() -> dict[str, Any]:
    """Sample video metadata."""
    return {
        "video_id": "vid001",
        "title": "Anatomy Lecture 1: Introduction",
        "view_count": 1500,
        "comment_count": 8,
        "published_at": "2026-03-15T10:00:00Z",
    }


class TestCommentReportGenerator:
    """Tests for CommentReportGenerator (T078)."""

    def test_generate_returns_html_path(
        self,
        tmp_path: Path,
        sample_topics: list[dict[str, Any]],
        sample_questions: dict[str, Any],
        sample_video_meta: dict[str, Any],
    ) -> None:
        """Report generation returns path to valid HTML file."""
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=sample_topics,
            questions_data=sample_questions,
            output_dir=tmp_path,
        )

        assert output.exists()
        assert output.suffix == ".html"
        assert output.name == "vid001_comment_insight.html"

    def test_html_contains_topic_sections(
        self,
        tmp_path: Path,
        sample_topics: list[dict[str, Any]],
        sample_questions: dict[str, Any],
        sample_video_meta: dict[str, Any],
    ) -> None:
        """Generated HTML contains per-topic sentiment summaries (T081)."""
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=sample_topics,
            questions_data=sample_questions,
            output_dir=tmp_path,
        )
        html = output.read_text(encoding="utf-8")

        # Should contain topic labels
        assert "audio quality" in html
        assert "teaching style" in html
        assert "exam schedule" in html

        # Should contain sentiment info
        assert "positive" in html.lower() or "Positive" in html
        assert "negative" in html.lower() or "Negative" in html

        # Should contain representative comments
        assert "음질이 너무 안 좋아요" in html

    def test_html_contains_faq_section(
        self,
        tmp_path: Path,
        sample_topics: list[dict[str, Any]],
        sample_questions: dict[str, Any],
        sample_video_meta: dict[str, Any],
    ) -> None:
        """Generated HTML contains auto-extracted FAQ section (T082)."""
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=sample_topics,
            questions_data=sample_questions,
            output_dir=tmp_path,
        )
        html = output.read_text(encoding="utf-8")

        # Should contain FAQ section heading
        assert "FAQ" in html

        # Should contain extracted questions
        assert "시험 범위가 어디까지인가요?" in html
        assert "이 강의 시리즈 총 몇 개인가요?" in html
        assert "교재 이름이 뭔가요?" in html

    def test_html_contains_video_meta(
        self,
        tmp_path: Path,
        sample_topics: list[dict[str, Any]],
        sample_questions: dict[str, Any],
        sample_video_meta: dict[str, Any],
    ) -> None:
        """Generated HTML contains video metadata."""
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=sample_topics,
            questions_data=sample_questions,
            output_dir=tmp_path,
        )
        html = output.read_text(encoding="utf-8")

        assert "Anatomy Lecture 1" in html
        assert "vid001" in html

    def test_html_contains_hotspot_matches(
        self,
        tmp_path: Path,
        sample_topics: list[dict[str, Any]],
        sample_questions: dict[str, Any],
        sample_video_meta: dict[str, Any],
    ) -> None:
        """Generated HTML shows questions matched to retention hotspots."""
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=sample_topics,
            questions_data=sample_questions,
            output_dir=tmp_path,
        )
        html = output.read_text(encoding="utf-8")

        # Hotspot match should appear
        assert "65%" in html or "0.65" in html

    def test_empty_topics_produces_valid_html(
        self,
        tmp_path: Path,
        sample_video_meta: dict[str, Any],
    ) -> None:
        """Empty topics list still produces valid HTML without errors."""
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=[],
            questions_data={"questions": [], "hotspot_matches": []},
            output_dir=tmp_path,
        )

        assert output.exists()
        html = output.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "vid001" in html

    def test_empty_questions_produces_valid_html(
        self,
        tmp_path: Path,
        sample_topics: list[dict[str, Any]],
        sample_video_meta: dict[str, Any],
    ) -> None:
        """No questions still produces valid HTML with topic section only."""
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=sample_topics,
            questions_data={"questions": [], "hotspot_matches": []},
            output_dir=tmp_path,
        )

        assert output.exists()
        html = output.read_text(encoding="utf-8")
        assert "audio quality" in html

    def test_html_is_well_formed(
        self,
        tmp_path: Path,
        sample_topics: list[dict[str, Any]],
        sample_questions: dict[str, Any],
        sample_video_meta: dict[str, Any],
    ) -> None:
        """Generated HTML is well-formed with proper tags."""
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=sample_topics,
            questions_data=sample_questions,
            output_dir=tmp_path,
        )
        html = output.read_text(encoding="utf-8")

        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "</head>" in html
        assert "<body>" in html
        assert "</body>" in html

    def test_output_dir_created_if_not_exists(
        self,
        tmp_path: Path,
        sample_topics: list[dict[str, Any]],
        sample_questions: dict[str, Any],
        sample_video_meta: dict[str, Any],
    ) -> None:
        """Output directory is created automatically if it does not exist."""
        output_dir = tmp_path / "nested" / "reports"
        generator = CommentReportGenerator()
        output = generator.generate(
            video_id="vid001",
            video_meta=sample_video_meta,
            topics=sample_topics,
            questions_data=sample_questions,
            output_dir=output_dir,
        )

        assert output.exists()
        assert output_dir.exists()
