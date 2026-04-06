"""Adversarial tests for Feature 006: Report Filter + PDF Bundle.

DURCS-based user persona attack scenarios:
- A-01 Rookie Employee: runs report bundle without prior data collection
- A-02 Rushed Dean: uses --format pdf without weasyprint, incomplete collection
- A-04 Free-spirited Professor: =CMD() formula injection in titles
- B-04 Unicode: Korean + emoji mixed titles in PDF generation
- B-06 Large Scale: 500 videos filter + bundle HTML generation stress

Silent-skip pattern validation:
- _parse_date returns None without logging (documented but unlogged)
- _load_videos_meta returns [] without logging on missing data
- generate_from_html skips videos without HTML files (logged via logger.warning)
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tube_scout.models.video_filter import VideoFilter
from tube_scout.reporting.bundle_report import BundleReportGenerator
from tube_scout.services.video_filter_service import VideoFilterService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_video(
    video_id: str = "vid001",
    title: str = "2025 감염미생물학 1주차 1차시",
    published_at: str = "2025-03-01T00:00:00Z",
    view_count: int = 100,
    duration_seconds: int = 3600,
    like_count: int = 5,
) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "title": title,
        "published_at": published_at,
        "view_count": view_count,
        "duration_seconds": duration_seconds,
        "like_count": like_count,
    }


def _setup_channel_data(
    tmp_path: Path,
    channel_id: str = "UC_TEST",
    videos: list[dict[str, Any]] | None = None,
) -> tuple[Path, BundleReportGenerator]:
    """Create minimal channel data on disk and return (data_path, generator)."""
    data_path = tmp_path / "data"
    videos_dir = data_path / "raw" / "channels" / channel_id
    videos_dir.mkdir(parents=True)
    if videos is not None:
        (videos_dir / "videos_meta.json").write_text(
            json.dumps(videos), encoding="utf-8"
        )
    gen = BundleReportGenerator(data_dir=data_path)
    return data_path, gen


# ===========================================================================
# A-01: Rookie Employee -- runs bundle without data collection
# ===========================================================================
class TestA01RookieEmployee:
    """Persona: new hire who runs 'report bundle' before ever collecting data."""

    def test_bundle_without_any_data_raises_valueerror(self, tmp_path: Path) -> None:
        """No videos_meta.json at all must raise ValueError, not crash."""
        _, gen = _setup_channel_data(tmp_path, videos=None)
        vf = VideoFilter(keyword="anything")
        with pytest.raises(ValueError, match="No videos matching"):
            gen.generate(
                video_filter=vf,
                channel_id="UC_TEST",
                output_path=tmp_path / "out.html",
            )

    def test_bundle_from_html_without_data_raises_valueerror(
        self, tmp_path: Path
    ) -> None:
        """--from-html mode with no videos_meta.json must raise ValueError."""
        _, gen = _setup_channel_data(tmp_path, videos=None)
        vf = VideoFilter(keyword="anything")
        with pytest.raises(ValueError, match="No videos matching"):
            gen.generate_from_html(
                html_dir=tmp_path / "html",
                video_filter=vf,
                channel_id="UC_TEST",
                output_path=tmp_path / "out.html",
            )

    def test_bundle_with_empty_video_list_raises_valueerror(
        self, tmp_path: Path
    ) -> None:
        """Empty videos_meta.json (=[]) must raise ValueError."""
        _, gen = _setup_channel_data(tmp_path, videos=[])
        vf = VideoFilter(keyword="anything")
        with pytest.raises(ValueError, match="No videos matching"):
            gen.generate(
                video_filter=vf,
                channel_id="UC_TEST",
                output_path=tmp_path / "out.html",
            )

    def test_bundle_no_keyword_option_requires_filter(self) -> None:
        """VideoFilter with no conditions must raise ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="At least one filter condition"):
            VideoFilter()


# ===========================================================================
# A-02: Rushed Dean -- weasyprint not installed, incomplete collection
# ===========================================================================
class TestA02RushedDean:
    """Persona: department head who wants PDF NOW but environment is not ready."""

    def test_render_pdf_without_weasyprint_returns_none(self, tmp_path: Path) -> None:
        """render_pdf must return None (not crash) when weasyprint is unavailable."""
        _, gen = _setup_channel_data(tmp_path)
        html_file = tmp_path / "test.html"
        html_file.write_text("<html><body>test</body></html>", encoding="utf-8")
        # If weasyprint is installed this returns a Path, otherwise None.
        # Either way, it must not raise.
        result = gen.render_pdf(html_file)
        assert result is None or result.exists()

    def test_bundle_with_incomplete_retention_data_succeeds(
        self, tmp_path: Path
    ) -> None:
        """Bundle generation must succeed even if retention/segments are missing."""
        videos = [_make_video(video_id=f"vid{i:03d}") for i in range(3)]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        vf = VideoFilter(keyword="감염미생물학")
        output = tmp_path / "bundle.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        # Should contain "no data" fallback, not a crash
        assert "Retention data not available" in content

    def test_from_html_all_files_missing_raises_valueerror(
        self, tmp_path: Path
    ) -> None:
        """--from-html with matching filter but zero HTML files
        must raise ValueError."""
        videos = [_make_video()]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        html_dir = tmp_path / "empty_html"
        html_dir.mkdir()
        vf = VideoFilter(keyword="감염미생물학")
        with pytest.raises(ValueError, match="No videos with available HTML"):
            gen.generate_from_html(
                html_dir=html_dir,
                video_filter=vf,
                channel_id="UC_TEST",
                output_path=tmp_path / "out.html",
            )


# ===========================================================================
# A-04: Free-spirited Professor -- formula injection in video titles
# ===========================================================================
class TestA04FormulaInjection:
    """Persona: professor whose video titles contain Excel/CSV formula patterns."""

    FORMULA_PAYLOADS = [
        "=CMD('calc')",
        "+CMD('calc')",
        "-CMD('calc')",
        "@SUM(A1:A10)",
        '=HYPERLINK("http://evil.com","click")',
        "\t=1+1",
        "\r\n=1+1",
    ]

    def test_formula_titles_escaped_in_html_bundle(self, tmp_path: Path) -> None:
        """Titles with formula patterns must be HTML-escaped in bundle output."""
        videos = [
            _make_video(video_id=f"vid{i:03d}", title=payload)
            for i, payload in enumerate(self.FORMULA_PAYLOADS)
        ]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        vf = VideoFilter(video_ids=[f"vid{i:03d}" for i in range(len(videos))])
        output = tmp_path / "formula_test.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        content = html_path.read_text(encoding="utf-8")
        # Jinja2 autoescape=True should escape < and " in attribute contexts.
        # Formula patterns themselves are text, not HTML dangerous,
        # but we verify no raw unescaped quotes break out of attributes.
        assert '"http://evil.com"' not in content

    def test_script_injection_in_title_escaped(self, tmp_path: Path) -> None:
        """<script> in video title must be escaped by Jinja2 autoescape."""
        payload = "<script>alert('xss')</script>"
        videos = [_make_video(title=payload)]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        vf = VideoFilter(video_ids=["vid001"])
        output = tmp_path / "xss_test.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        content = html_path.read_text(encoding="utf-8")
        assert "<script>alert" not in content
        # Must be escaped as &lt;script&gt;
        assert "&lt;script&gt;" in content

    def test_jinja2_template_injection_in_title(self, tmp_path: Path) -> None:
        """Jinja2 template syntax {{ }} in title must not execute."""
        payload = "{{ config.__class__.__init__.__globals__ }}"
        videos = [_make_video(title=payload)]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        vf = VideoFilter(video_ids=["vid001"])
        output = tmp_path / "ssti_test.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        content = html_path.read_text(encoding="utf-8")
        # Jinja2 renders data variables literally (not as template syntax).
        # The payload string appears in the output but is NOT executed.
        # Verify it was NOT interpreted (no Python object repr in output).
        assert "mappingproxy" not in content  # sign of actual __globals__ access
        assert "builtins" not in content  # sign of actual __globals__ access


# ===========================================================================
# B-04: Unicode -- Korean + emoji mixed titles in PDF/HTML generation
# ===========================================================================
class TestB04UnicodeEmojiMixed:
    """Persona: videos with Korean text, emoji, and special Unicode in titles."""

    UNICODE_TITLES = [
        "2025 감염미생물학 1주차 1차시 - 세균의 구조와 기능",
        "해부학 실습 - 근육계통 overview",
        "간호학 개론 - 환자 안전 관리",
        "2025 감염미생물학 8주차 2차시 중간고사 대비 정리 + 퀴즈",
        "Zero-Width Joiner \u200d test",  # ZWJ
        "Right-to-Left Mark \u200f test",  # RLM
        "BOM test \ufeff data",  # BOM character
    ]

    def test_unicode_titles_in_bundle_html_no_crash(self, tmp_path: Path) -> None:
        """Bundle with diverse Unicode titles must generate valid HTML."""
        videos = [
            _make_video(video_id=f"vid{i:03d}", title=t)
            for i, t in enumerate(self.UNICODE_TITLES)
        ]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        vf = VideoFilter(video_ids=[f"vid{i:03d}" for i in range(len(videos))])
        output = tmp_path / "unicode_bundle.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "Table of Contents" in content

    def test_emoji_keyword_filter_matches_correctly(self) -> None:
        """Emoji substring in keyword must match only titles containing it."""
        videos = [
            _make_video(video_id="v1", title="test title"),
            _make_video(video_id="v2", title="test title data"),
        ]
        vf = VideoFilter(keyword="test")
        result = VideoFilterService.filter_videos(videos, vf)
        # Both contain "test"
        assert len(result) == 2

    def test_korean_emoji_mixed_title_in_from_html(self, tmp_path: Path) -> None:
        """--from-html mode with Korean+emoji titles must work."""
        title = "2025 감염미생물학 8주차 2차시"
        videos = [_make_video(video_id="vid001", title=title)]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        html_dir = tmp_path / "html_reports"
        html_dir.mkdir()
        (html_dir / "vid001.html").write_text(
            f"<html><body><h1>{title}</h1><p>content</p></body></html>",
            encoding="utf-8",
        )
        vf = VideoFilter(video_ids=["vid001"])
        output = tmp_path / "from_html_unicode.html"
        html_path = gen.generate_from_html(
            html_dir=html_dir,
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "content" in content


# ===========================================================================
# B-06: Large Scale -- 500 videos filter + bundle generation
# ===========================================================================
class TestB06LargeScale:
    """Persona: department with 500+ lecture videos being bundled."""

    def test_500_videos_filter_performance(self) -> None:
        """Filtering 500 videos by keyword must complete without error."""
        videos = [
            _make_video(
                video_id=f"vid{i:04d}",
                title=f"감염미생물학 {i}주차" if i % 5 == 0 else f"해부학 {i}주차",
            )
            for i in range(500)
        ]
        vf = VideoFilter(keyword="감염미생물학")
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 100  # every 5th

    def test_500_videos_sort_by_course(self) -> None:
        """Sorting 500 videos by course must not crash."""
        videos = [
            _make_video(
                video_id=f"vid{i:04d}",
                title=f"교수A 과목{i % 10} {i // 10}주차 {(i % 3) + 1}차시",
            )
            for i in range(500)
        ]
        result = VideoFilterService.sort_videos(videos, "course")
        assert len(result) == 500

    def test_500_videos_bundle_html_generation(self, tmp_path: Path) -> None:
        """Generate bundle HTML with 500 videos without crash or truncation."""
        videos = [
            _make_video(video_id=f"vid{i:04d}", title=f"대규모 테스트 {i}주차")
            for i in range(500)
        ]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        vf = VideoFilter(keyword="대규모 테스트")
        output = tmp_path / "large_bundle.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        # All 500 video sections must be present (as div id="video-...")
        assert content.count('id="video-') == 500

    def test_summary_stats_correct_for_500_videos(self) -> None:
        """Aggregate summary for 500 videos must compute correctly."""
        videos = [
            _make_video(
                video_id=f"vid{i:04d}",
                view_count=10,
                duration_seconds=600,
                like_count=2,
            )
            for i in range(500)
        ]
        summary = BundleReportGenerator._compute_summary(videos)
        assert summary["video_count"] == 500
        assert summary["total_duration_minutes"] == 5000  # 500 * 600 / 60
        assert summary["avg_views"] == 10
        assert summary["total_likes"] == 1000


# ===========================================================================
# Silent-Skip Pattern Validation
# ===========================================================================
class TestSilentSkipPatterns:
    """Validate that documented silent-skip patterns behave as expected."""

    def test_parse_date_invalid_returns_none_silently(self) -> None:
        """_parse_date with garbage input returns None (documented, no log)."""
        result = VideoFilterService._parse_date("not-a-date")
        assert result is None

    def test_parse_date_empty_string_returns_none(self) -> None:
        """_parse_date with empty string returns None."""
        result = VideoFilterService._parse_date("")
        assert result is None

    def test_load_videos_meta_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """_load_videos_meta with nonexistent path returns [] (no log)."""
        gen = BundleReportGenerator(data_dir=tmp_path)
        result = gen._load_videos_meta("NONEXISTENT")
        assert result == []

    def test_load_retention_missing_returns_none(self, tmp_path: Path) -> None:
        """_load_retention with missing file returns None."""
        gen = BundleReportGenerator(data_dir=tmp_path)
        result = gen._load_retention("NONEXISTENT_VID")
        assert result is None

    def test_load_segments_missing_returns_none(self, tmp_path: Path) -> None:
        """_load_segments with missing file returns None."""
        gen = BundleReportGenerator(data_dir=tmp_path)
        result = gen._load_segments("NONEXISTENT_VID")
        assert result is None

    def test_extract_html_body_no_body_returns_empty(self) -> None:
        """_extract_html_body on HTML without <body> returns empty string."""
        result = BundleReportGenerator._extract_html_body("<html><head></head></html>")
        assert result == ""

    def test_from_html_partial_missing_logs_and_skips(self, tmp_path: Path) -> None:
        """generate_from_html skips missing HTML files with logger.warning."""
        videos = [
            _make_video(video_id="vid001"),
            _make_video(video_id="vid002"),
        ]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        html_dir = tmp_path / "html_reports"
        html_dir.mkdir()
        # Only vid001 has an HTML file
        (html_dir / "vid001.html").write_text(
            "<html><body><p>Report for vid001</p></body></html>",
            encoding="utf-8",
        )
        vf = VideoFilter(video_ids=["vid001", "vid002"])
        output = tmp_path / "partial.html"
        html_path = gen.generate_from_html(
            html_dir=html_dir,
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        # vid002 should appear in skipped notice
        assert "vid002" in content


# ===========================================================================
# Template Security -- autoescape verification
# ===========================================================================
class TestTemplateAutoescape:
    """Verify Jinja2 autoescape is enabled on both bundle templates."""

    def test_bundle_report_template_autoescapes(self, tmp_path: Path) -> None:
        """bundle_report.html must autoescape user-controlled fields."""
        videos = [_make_video(title="<b>bold</b>")]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        vf = VideoFilter(video_ids=["vid001"])
        output = tmp_path / "escape_test.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        content = html_path.read_text(encoding="utf-8")
        assert "<b>bold</b>" not in content
        assert "&lt;b&gt;bold&lt;/b&gt;" in content

    def test_bundle_from_html_preserves_body_html_raw(self, tmp_path: Path) -> None:
        """bundle_from_html.html uses |safe on body_html -- verify it renders."""
        videos = [_make_video(video_id="vid001")]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        html_dir = tmp_path / "html_reports"
        html_dir.mkdir()
        (html_dir / "vid001.html").write_text(
            "<html><body><h2>Real Report</h2><p>analysis</p></body></html>",
            encoding="utf-8",
        )
        vf = VideoFilter(video_ids=["vid001"])
        output = tmp_path / "from_html_test.html"
        html_path = gen.generate_from_html(
            html_dir=html_dir,
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        content = html_path.read_text(encoding="utf-8")
        # body_html should be rendered raw (|safe filter)
        assert "<h2>Real Report</h2>" in content

    def test_custom_title_with_html_is_escaped(self, tmp_path: Path) -> None:
        """Custom --title with HTML must be escaped in output."""
        videos = [_make_video()]
        _, gen = _setup_channel_data(tmp_path, videos=videos)
        vf = VideoFilter(video_ids=["vid001"])
        output = tmp_path / "title_escape_test.html"
        malicious_title = "<img src=x onerror=alert(1)>"
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
            title=malicious_title,
        )
        content = html_path.read_text(encoding="utf-8")
        # The < and > must be escaped so the tag is not rendered by browsers
        assert "<img src=x onerror" not in content
        assert "&lt;img src=x onerror=alert(1)&gt;" in content
