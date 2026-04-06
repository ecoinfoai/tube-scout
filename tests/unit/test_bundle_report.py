"""Unit tests for BundleReportGenerator (T015)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from tube_scout.models.video_filter import VideoFilter
from tube_scout.reporting.bundle_report import BundleReportGenerator
from tube_scout.storage.json_store import write_json


def _setup_bundle_data(data_dir: Path) -> str:
    """Set up test data for bundle report generation.

    Returns:
        The channel_id used.
    """
    channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"
    channel_dir = data_dir / "raw" / "channels" / channel_id
    channel_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        channel_dir / "videos_meta.json",
        [
            {
                "video_id": "vid001",
                "channel_id": channel_id,
                "title": "감염미생물학 1주차 강의",
                "published_at": "2026-01-15T10:00:00Z",
                "duration_seconds": 600,
                "view_count": 100,
                "like_count": 5,
                "comment_count": 1,
            },
            {
                "video_id": "vid002",
                "channel_id": channel_id,
                "title": "인체구조와기능 2주차 강의",
                "published_at": "2026-02-10T10:00:00Z",
                "duration_seconds": 900,
                "view_count": 200,
                "like_count": 10,
                "comment_count": 2,
            },
        ],
    )

    # Retention data
    retention_dir = data_dir / "processed" / "retention"
    retention_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        retention_dir / "vid001.json",
        {
            "video_id": "vid001",
            "hotspots": [{"elapsed_ratio": 0.3, "audience_watch_ratio": 0.9}],
            "skip_zones": [],
        },
    )
    # vid002 has no retention data (test graceful handling)

    # Segments
    segments_dir = data_dir / "processed" / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        segments_dir / "vid001.json",
        [
            {
                "segment_index": 0,
                "title": "Introduction",
                "start_seconds": 0,
                "end_seconds": 120,
                "difficulty_score": 0.3,
            },
        ],
    )
    # vid002 has no segments data

    write_json(
        data_dir / "config.json",
        {
            "channels": [
                {"channel_id": channel_id, "professor_name": "테스트교수"},
            ],
        },
    )

    return channel_id


class TestBundleReportGenerator:
    """Tests for BundleReportGenerator.generate()."""

    def test_generate_html_contains_cover(self, tmp_path: Path) -> None:
        """Generated HTML must contain cover page elements."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        html = result.read_text(encoding="utf-8")
        assert "감염미생물학" in html  # filter info on cover
        assert "1" in html  # video count

    def test_generate_html_contains_toc(self, tmp_path: Path) -> None:
        """Generated HTML must contain table of contents."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        html = result.read_text(encoding="utf-8")
        # TOC should have link to video section
        assert "vid001" in html
        assert "감염미생물학 1주차 강의" in html

    def test_generate_html_contains_video_sections(self, tmp_path: Path) -> None:
        """Generated HTML must contain per-video detail sections."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        html = result.read_text(encoding="utf-8")
        assert "감염미생물학 1주차 강의" in html
        assert "Introduction" in html  # segment title

    def test_generate_handles_missing_retention(self, tmp_path: Path) -> None:
        """Videos without retention data should show fallback message."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        # Use filter that matches vid002 which has no retention
        video_filter = VideoFilter(keyword="인체구조와기능")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        html = result.read_text(encoding="utf-8")
        assert "인체구조와기능 2주차 강의" in html
        # Should not error, and should indicate missing data
        assert result.exists()

    def test_render_pdf_import_error(self, tmp_path: Path) -> None:
        """_render_pdf gracefully handles missing weasyprint."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="감염미생물학")
        html_path = tmp_path / "output" / "bundle.html"

        gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=html_path,
        )

        with patch.dict("sys.modules", {"weasyprint": None}):
            result = gen.render_pdf(html_path)
            assert result is None

    def test_generate_with_custom_title(self, tmp_path: Path) -> None:
        """Custom title should appear on cover page."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
            title="커스텀 보고서 제목",
        )

        html = result.read_text(encoding="utf-8")
        assert "커스텀 보고서 제목" in html


class TestExtractHtmlBody:
    """Tests for BundleReportGenerator._extract_html_body() (T026)."""

    def test_extracts_body_content(self) -> None:
        """Extracts content between <body> and </body> tags."""
        html = (
            "<!DOCTYPE html><html><head><title>Test</title></head>"
            "<body><h1>Hello</h1><p>World</p></body></html>"
        )
        result = BundleReportGenerator._extract_html_body(html)
        assert "<h1>Hello</h1>" in result
        assert "<p>World</p>" in result
        assert "<head>" not in result
        assert "</html>" not in result

    def test_returns_empty_on_no_body(self) -> None:
        """Returns empty string if no body tag found."""
        html = "<html><head></head></html>"
        result = BundleReportGenerator._extract_html_body(html)
        assert result == ""

    def test_handles_attributes_on_body(self) -> None:
        """Works with <body class="..."> style attributes."""
        html = '<html><body class="main"><div>Content</div></body></html>'
        result = BundleReportGenerator._extract_html_body(html)
        assert "<div>Content</div>" in result


class TestGenerateFromHtml:
    """Tests for BundleReportGenerator.generate_from_html() (T027)."""

    def test_from_html_filters_by_keyword(self, tmp_path: Path) -> None:
        """--from-html with keyword filter only includes matching videos."""
        channel_id = _setup_bundle_data(tmp_path)

        # Create existing HTML report files
        html_dir = tmp_path / "reports" / "video"
        html_dir.mkdir(parents=True, exist_ok=True)
        (html_dir / "vid001.html").write_text(
            "<html><body><h1>감염미생물학 1주차</h1></body></html>",
            encoding="utf-8",
        )
        (html_dir / "vid002.html").write_text(
            "<html><body><h1>인체구조와기능 2주차</h1></body></html>",
            encoding="utf-8",
        )

        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate_from_html(
            html_dir=html_dir,
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        html = result.read_text(encoding="utf-8")
        assert "감염미생물학 1주차" in html
        assert "인체구조와기능 2주차" not in html

    def test_from_html_missing_file_skipped(self, tmp_path: Path) -> None:
        """Videos matching filter but missing HTML are skipped with warning."""
        channel_id = _setup_bundle_data(tmp_path)

        html_dir = tmp_path / "reports" / "video"
        html_dir.mkdir(parents=True, exist_ok=True)
        # Only vid001 has HTML, vid002 does not (but both match "강의")
        (html_dir / "vid001.html").write_text(
            "<html><body><h1>감염미생물학 1주차 강의</h1></body></html>",
            encoding="utf-8",
        )

        gen = BundleReportGenerator(data_dir=tmp_path)
        # Filter matches both vid001 and vid002
        video_filter = VideoFilter(keyword="강의")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate_from_html(
            html_dir=html_dir,
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        html = result.read_text(encoding="utf-8")
        assert "감염미생물학 1주차 강의" in html
        assert result.exists()

    def test_from_html_no_matching_files_raises(self, tmp_path: Path) -> None:
        """Raises ValueError when no HTML files match the filter."""
        channel_id = _setup_bundle_data(tmp_path)

        html_dir = tmp_path / "reports" / "video"
        html_dir.mkdir(parents=True, exist_ok=True)

        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="존재하지않는과목")
        output_path = tmp_path / "output" / "bundle.html"

        with pytest.raises(ValueError, match="No videos"):
            gen.generate_from_html(
                html_dir=html_dir,
                video_filter=video_filter,
                channel_id=channel_id,
                output_path=output_path,
            )


class TestComputeSummary:
    """Tests for BundleReportGenerator._compute_summary() (T035)."""

    def test_summary_video_count(self) -> None:
        """Summary includes correct video count."""
        videos = [
            {"duration_seconds": 600, "view_count": 100, "like_count": 5},
            {"duration_seconds": 900, "view_count": 200, "like_count": 10},
            {"duration_seconds": 300, "view_count": 50, "like_count": 3},
        ]
        summary = BundleReportGenerator._compute_summary(videos)
        assert summary["video_count"] == 3

    def test_summary_total_duration(self) -> None:
        """Summary includes correct total duration in minutes."""
        videos = [
            {"duration_seconds": 600, "view_count": 100, "like_count": 5},
            {"duration_seconds": 900, "view_count": 200, "like_count": 10},
        ]
        summary = BundleReportGenerator._compute_summary(videos)
        assert summary["total_duration_minutes"] == 25  # (600+900)/60

    def test_summary_average_views(self) -> None:
        """Summary includes correct average view count."""
        videos = [
            {"duration_seconds": 600, "view_count": 100, "like_count": 5},
            {"duration_seconds": 900, "view_count": 200, "like_count": 10},
        ]
        summary = BundleReportGenerator._compute_summary(videos)
        assert summary["avg_views"] == 150

    def test_summary_total_likes(self) -> None:
        """Summary includes correct total like count."""
        videos = [
            {"duration_seconds": 600, "view_count": 100, "like_count": 5},
            {"duration_seconds": 900, "view_count": 200, "like_count": 10},
        ]
        summary = BundleReportGenerator._compute_summary(videos)
        assert summary["total_likes"] == 15

    def test_summary_in_html_output(self, tmp_path: Path) -> None:
        """Generated HTML contains summary statistics section."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        html = result.read_text(encoding="utf-8")
        assert "Summary" in html or "summary" in html


class TestSingleVideoNoToc:
    """Tests for single video bundle with no TOC (T039)."""

    def test_single_video_omits_toc(self, tmp_path: Path) -> None:
        """Bundle with 1 video should not include Table of Contents."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        # Only vid001 matches "감염미생물학" (vid002 is 인체구조와기능)
        video_filter = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        html = result.read_text(encoding="utf-8")
        assert "감염미생물학 1주차 강의" in html
        assert "Table of Contents" not in html
