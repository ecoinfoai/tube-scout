"""Tests for channel comprehensive report (US9 - FR-023/FR-024)."""

from pathlib import Path
from typing import Any

import pytest

from tube_scout.reporting.channel_report import (
    ChannelReportGenerator,
    ImprovementSuggestion,
    compare_videos,
    generate_improvement_suggestions,
)

# --- Fixtures ---


@pytest.fixture
def sample_videos() -> list[dict[str, Any]]:
    """Sample video list with varied characteristics."""
    return [
        {
            "video_id": "v1",
            "title": "Anatomy Ch1 - Introduction",
            "view_count": 5000,
            "like_count": 100,
            "comment_count": 20,
            "duration_seconds": 900,  # 15 min
            "published_at": "2024-01-01T00:00:00Z",
            "tags": ["anatomy", "introduction"],
            "topic_categories": ["https://en.wikipedia.org/wiki/Health"],
            "category_id": "27",
        },
        {
            "video_id": "v2",
            "title": "Anatomy Ch2 - Skeletal System",
            "view_count": 3000,
            "like_count": 60,
            "comment_count": 15,
            "duration_seconds": 2700,  # 45 min
            "published_at": "2024-01-15T00:00:00Z",
            "tags": ["anatomy", "skeletal"],
            "topic_categories": ["https://en.wikipedia.org/wiki/Health"],
            "category_id": "27",
        },
        {
            "video_id": "v3",
            "title": "Anatomy Ch3 - Muscular System",
            "view_count": 8000,
            "like_count": 200,
            "comment_count": 40,
            "duration_seconds": 1200,  # 20 min
            "published_at": "2024-02-01T00:00:00Z",
            "tags": ["anatomy", "muscular"],
            "topic_categories": ["https://en.wikipedia.org/wiki/Health"],
            "category_id": "27",
        },
        {
            "video_id": "v4",
            "title": "Physiology Special Lecture",
            "view_count": 5000,
            "like_count": 10,
            "comment_count": 2,
            "duration_seconds": 5400,  # 90 min
            "published_at": "2024-03-01T00:00:00Z",
            "tags": ["physiology"],
            "topic_categories": ["https://en.wikipedia.org/wiki/Education"],
            "category_id": "27",
        },
    ]


@pytest.fixture
def sample_forecasts() -> list[dict[str, Any]]:
    """Sample forecast data."""
    return [
        {
            "date": 738900,
            "predicted_value": 150.0,
            "lower_bound": 120.0,
            "upper_bound": 180.0,
            "model_used": "arima",
        },
        {
            "date": 738901,
            "predicted_value": 155.0,
            "lower_bound": 125.0,
            "upper_bound": 185.0,
            "model_used": "arima",
        },
    ]


@pytest.fixture
def sample_eqs_scores() -> list[dict[str, Any]]:
    """Sample EQS quality scores."""
    return [
        {
            "video_id": "v1",
            "relevance": 0.9,
            "accuracy": 0.85,
            "clarity": 0.8,
            "engagement": 0.7,
            "depth": 0.6,
            "overall": 0.77,
        },
        {
            "video_id": "v3",
            "relevance": 0.95,
            "accuracy": 0.9,
            "clarity": 0.95,
            "engagement": 0.9,
            "depth": 0.85,
            "overall": 0.91,
        },
    ]


# --- T084: Improvement Suggestion Tests ---


class TestImprovementSuggestionModel:
    """Tests for ImprovementSuggestion Pydantic model (T086)."""

    def test_valid_suggestion(self) -> None:
        s = ImprovementSuggestion(
            video_id="v1",
            category="length",
            suggestion="Consider shorter videos.",
            evidence="Average duration is 45 min, but top videos are 15-20 min.",
            priority="high",
        )
        assert s.video_id == "v1"
        assert s.category == "length"
        assert s.priority == "high"

    def test_channel_level_suggestion_no_video_id(self) -> None:
        s = ImprovementSuggestion(
            video_id=None,
            category="engagement",
            suggestion="Increase interaction prompts.",
            evidence="Average engagement is below threshold.",
            priority="medium",
        )
        assert s.video_id is None

    def test_invalid_category_raises(self) -> None:
        with pytest.raises(ValueError):
            ImprovementSuggestion(
                video_id="v1",
                category="invalid_category",
                suggestion="Test",
                evidence="Test",
                priority="high",
            )

    def test_invalid_priority_raises(self) -> None:
        with pytest.raises(ValueError):
            ImprovementSuggestion(
                video_id="v1",
                category="length",
                suggestion="Test",
                evidence="Test",
                priority="critical",
            )


class TestGenerateImprovementSuggestions:
    """Tests for improvement suggestion generation (T084/T088)."""

    def test_generates_length_suggestion_for_long_video(
        self, sample_videos: list[dict[str, Any]]
    ) -> None:
        suggestions = generate_improvement_suggestions(sample_videos)
        length_suggestions = [s for s in suggestions if s.category == "length"]
        assert len(length_suggestions) > 0
        # Should flag the 90-min video
        long_video_suggestions = [s for s in length_suggestions if s.video_id == "v4"]
        assert len(long_video_suggestions) > 0

    def test_generates_engagement_suggestion_for_low_engagement(
        self, sample_videos: list[dict[str, Any]]
    ) -> None:
        suggestions = generate_improvement_suggestions(sample_videos)
        engagement_suggestions = [s for s in suggestions if s.category == "engagement"]
        # v4 has very low engagement relative to others
        assert any(s.video_id == "v4" for s in engagement_suggestions)

    def test_no_suggestions_for_empty_videos(self) -> None:
        suggestions = generate_improvement_suggestions([])
        assert suggestions == []

    def test_includes_channel_level_suggestions(
        self, sample_videos: list[dict[str, Any]]
    ) -> None:
        suggestions = generate_improvement_suggestions(sample_videos)
        channel_level = [s for s in suggestions if s.video_id is None]
        assert len(channel_level) > 0

    def test_suggestions_have_evidence(
        self, sample_videos: list[dict[str, Any]]
    ) -> None:
        suggestions = generate_improvement_suggestions(sample_videos)
        for s in suggestions:
            assert s.evidence != ""
            assert s.suggestion != ""

    def test_with_eqs_scores(
        self,
        sample_videos: list[dict[str, Any]],
        sample_eqs_scores: list[dict[str, Any]],
    ) -> None:
        suggestions = generate_improvement_suggestions(
            sample_videos, eqs_scores=sample_eqs_scores
        )
        # Should generate content suggestions based on EQS
        assert len(suggestions) > 0


# --- T085: Video Comparison Tests ---


class TestCompareVideos:
    """Tests for video comparison analysis (T085/T087)."""

    def test_comparison_by_views(self, sample_videos: list[dict[str, Any]]) -> None:
        comparison = compare_videos(sample_videos)
        assert "rankings" in comparison
        by_views = comparison["rankings"]["by_views"]
        # v3 has the most views (8000)
        assert by_views[0]["video_id"] == "v3"

    def test_comparison_by_engagement_rate(
        self, sample_videos: list[dict[str, Any]]
    ) -> None:
        comparison = compare_videos(sample_videos)
        by_engagement = comparison["rankings"]["by_engagement_rate"]
        # Engagement rate = (likes + comments) / views
        # v3: (200+40)/8000 = 0.03, v1: (100+20)/5000 = 0.024
        assert len(by_engagement) == len(sample_videos)

    def test_comparison_includes_duration_analysis(
        self, sample_videos: list[dict[str, Any]]
    ) -> None:
        comparison = compare_videos(sample_videos)
        assert "duration_analysis" in comparison
        da = comparison["duration_analysis"]
        assert "avg_duration_minutes" in da
        assert "optimal_range" in da

    def test_comparison_includes_topic_groups(
        self, sample_videos: list[dict[str, Any]]
    ) -> None:
        comparison = compare_videos(sample_videos)
        assert "topic_groups" in comparison
        # videos with tag "anatomy" should be grouped together
        assert len(comparison["topic_groups"]) > 0

    def test_comparison_empty_videos(self) -> None:
        comparison = compare_videos([])
        assert comparison["rankings"]["by_views"] == []
        assert comparison["rankings"]["by_engagement_rate"] == []

    def test_comparison_includes_stats_summary(
        self, sample_videos: list[dict[str, Any]]
    ) -> None:
        comparison = compare_videos(sample_videos)
        assert "summary" in comparison
        summary = comparison["summary"]
        assert "total_videos" in summary
        assert summary["total_videos"] == 4
        assert "total_views" in summary
        assert "avg_views" in summary


# --- T090/T091: Report Generation Integration ---


class TestChannelReportGeneration:
    """Tests for comprehensive channel report generation."""

    def test_generate_includes_comparison_and_suggestions(
        self, tmp_path: Path, sample_videos: list[dict[str, Any]]
    ) -> None:
        # Setup data directory
        data_dir = tmp_path / "data"
        channel_id = "UCtest1234567890123456"
        channel_dir = data_dir / "raw" / "channels" / channel_id
        channel_dir.mkdir(parents=True)

        import json

        (channel_dir / "channel_meta.json").write_text(
            json.dumps(
                {
                    "channel_id": channel_id,
                    "channel_name": "Test Channel",
                    "professor_name": "Test Prof",
                    "subscriber_count": 1000,
                    "total_view_count": 50000,
                }
            )
        )
        (channel_dir / "videos_meta.json").write_text(json.dumps(sample_videos))

        generator = ChannelReportGenerator(data_dir=data_dir)
        output_dir = tmp_path / "reports"
        path = generator.generate(channel_id, output_dir)

        assert path.exists()
        content = path.read_text()
        assert "Test Channel" in content
        assert "Video Comparison" in content
        assert "Improvement Suggestions" in content

    def test_generate_with_daily_data_includes_trend_chart(
        self, tmp_path: Path, sample_videos: list[dict[str, Any]]
    ) -> None:
        import json

        data_dir = tmp_path / "data"
        channel_id = "UCtest1234567890123456"
        channel_dir = data_dir / "raw" / "channels" / channel_id
        channel_dir.mkdir(parents=True)

        (channel_dir / "channel_meta.json").write_text(
            json.dumps(
                {
                    "channel_id": channel_id,
                    "channel_name": "Trend Channel",
                    "professor_name": "Prof",
                }
            )
        )
        (channel_dir / "videos_meta.json").write_text(json.dumps(sample_videos))

        # Create daily analytics data
        daily_dir = data_dir / "raw" / "analytics" / channel_id / "daily"
        daily_dir.mkdir(parents=True)
        daily_data = [
            {"date": f"2024-01-{d:02d}", "views": 100 + d * 5} for d in range(1, 31)
        ]
        (daily_dir / "channel.json").write_text(json.dumps(daily_data))

        generator = ChannelReportGenerator(data_dir=data_dir)
        output_dir = tmp_path / "reports"
        path = generator.generate(channel_id, output_dir)

        content = path.read_text()
        assert "plotly" in content.lower()
        assert "Daily Views Trend" in content


class TestTrendChartGeneration:
    """Tests for plotly trend chart embedding (T089)."""

    def test_create_trend_chart_html_returns_plotly_div(self) -> None:
        from tube_scout.visualization.charts import create_trend_chart_html

        daily_data = [
            {"date": "2024-01-01", "views": 100},
            {"date": "2024-01-02", "views": 150},
            {"date": "2024-01-03", "views": 120},
        ]
        html = create_trend_chart_html(daily_data)
        assert "plotly" in html.lower()
        assert "Daily Views Trend" in html

    def test_create_trend_chart_with_forecasts(self) -> None:
        from tube_scout.visualization.charts import create_trend_chart_html

        daily_data = [
            {"date": "2024-01-01", "views": 100},
            {"date": "2024-01-02", "views": 150},
        ]
        forecasts = [
            {
                "date": "2024-01-03",
                "predicted_value": 160,
                "lower_bound": 140,
                "upper_bound": 180,
            },
        ]
        html = create_trend_chart_html(daily_data, forecasts=forecasts)
        assert "Forecast" in html
        assert "Confidence" in html

    def test_create_trend_chart_empty_data(self) -> None:
        from tube_scout.visualization.charts import create_trend_chart_html

        html = create_trend_chart_html([])
        assert html == ""
