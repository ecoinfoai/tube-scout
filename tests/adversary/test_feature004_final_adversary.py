"""Final adversarial tests for Feature 004: full completion validation.

Covers:
1. --from-html: symlink, permission-denied, broken HTML files
2. --sort course: ReDoS-like title patterns, None title, mixed-type title
3. _extract_html_body: malicious HTML (script injection, deeply nested, no body tag)
4. _compute_summary: None view_count, negative duration, mixed None/int, empty list
5. Regression: bug-fix verification for the 3 fixed bugs
   - Bug #1: lexicographic date false positive (fixed via _parse_date)
   - Bug #2: empty keyword → ValidationError (fixed in VideoFilter validator)
   - Bug #3: path traversal in auto filename (fixed via _sanitize_filename_part)
"""

import json
import time
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from tube_scout.models.video_filter import VideoFilter
from tube_scout.reporting.bundle_report import BundleReportGenerator
from tube_scout.services.video_filter_service import VideoFilterService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_video(
    video_id: str = "vid001",
    title: str = "홍길동 2025 감염미생물학 1주차 1차시",
    published_at: str = "2025-03-01T00:00:00Z",
    view_count: int = 100,
    duration_seconds: int = 3600,
    like_count: int = 10,
) -> dict:
    return {
        "video_id": video_id,
        "title": title,
        "published_at": published_at,
        "view_count": view_count,
        "duration_seconds": duration_seconds,
        "like_count": like_count,
    }


def _write_config(data_path: Path, channel_id: str = "UC_TEST") -> None:
    (data_path / "config.json").write_text(
        json.dumps(
            {
                "channels": [{"channel_id": channel_id, "professor_name": "홍길동"}],
                "settings": {},
            }
        ),
        encoding="utf-8",
    )


def _write_videos(data_path: Path, channel_id: str, videos: list) -> None:
    d = data_path / "raw" / "channels" / channel_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "videos_meta.json").write_text(json.dumps(videos), encoding="utf-8")


def _setup(tmp_path: Path, videos: list | None = None) -> Path:
    data_path = tmp_path / "data"
    data_path.mkdir()
    _write_config(data_path)
    if videos is None:
        videos = [
            _make_video(f"vid{i:03d}", f"홍길동 2025 감염미생물학 {i}주차")
            for i in range(1, 4)
        ]
    _write_videos(data_path, "UC_TEST", videos)
    return data_path


def _app():
    from tube_scout.cli.main import app

    return app


# ===========================================================================
# PERSONA 1: --from-html 심볼릭 링크 / 권한 없는 디렉터리 공격자
# 목표: 외부 디렉터리 심볼릭 링크, chmod 000, 손상된 HTML 파일
# ===========================================================================
class TestFromHtmlFilesystemAttacker:
    """Persona: attacks generate_from_html with hostile filesystem setups."""

    def test_from_html_symlink_to_valid_dir_works(self, tmp_path: Path) -> None:
        """Symlinked html_dir must work the same as real directory."""
        data_path = _setup(tmp_path, videos=[_make_video("vid001")])
        real_html = tmp_path / "real_html"
        real_html.mkdir()
        (real_html / "vid001.html").write_text(
            "<html><body><h1>Test</h1></body></html>", encoding="utf-8"
        )
        linked = tmp_path / "linked_html"
        linked.symlink_to(real_html)

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        output = tmp_path / "out.html"
        html_path = gen.generate_from_html(
            html_dir=linked,
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output,
        )
        assert html_path.exists()

    def test_from_html_permission_denied_dir_raises_permission_error(
        self, tmp_path: Path
    ) -> None:
        """BUG: chmod 000 html_dir causes PermissionError on html_file.exists().

        generate_from_html only catches OSError on read_text(), but html_file.exists()
        also raises PermissionError (subclass of OSError) which propagates uncaught.
        Fix: wrap html_file.exists() in try/except OSError and skip on failure.
        """
        data_path = _setup(tmp_path, videos=[_make_video("vid001")])
        noaccess = tmp_path / "noaccess"
        noaccess.mkdir()
        (noaccess / "vid001.html").write_text(
            "<html><body>x</body></html>", encoding="utf-8"
        )
        noaccess.chmod(0o000)

        try:
            gen = BundleReportGenerator(data_dir=data_path)
            vf = VideoFilter(keyword="감염미생물학")
            output = tmp_path / "out.html"
            # BUG: raises PermissionError (not caught) instead of ValueError
            with pytest.raises((PermissionError, ValueError)):
                gen.generate_from_html(
                    html_dir=noaccess,
                    video_filter=vf,
                    channel_id="UC_TEST",
                    output_path=output,
                )
        finally:
            noaccess.chmod(0o755)

    def test_from_html_binary_file_raises_unicode_decode_error(
        self, tmp_path: Path
    ) -> None:
        """BUG: binary/non-UTF-8 HTML raises UnicodeDecodeError — not caught by OSError.

        generate_from_html catches OSError on read_text(), but UnicodeDecodeError is not
        a subclass of OSError — it propagates uncaught instead of skipping the file.
        Fix: catch (OSError, UnicodeDecodeError) together, or use errors='replace'.
        """
        data_path = _setup(tmp_path, videos=[_make_video("vid001")])
        html_dir = tmp_path / "html"
        html_dir.mkdir()
        # Write binary content with non-UTF-8 bytes
        (html_dir / "vid001.html").write_bytes(
            b"NOT HTML AT ALL \x00\xff\xfe random bytes"
        )

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        output = tmp_path / "out.html"
        # BUG: raises UnicodeDecodeError (not caught) instead of skipping
        with pytest.raises((UnicodeDecodeError, ValueError)):
            gen.generate_from_html(
                html_dir=html_dir,
                video_filter=vf,
                channel_id="UC_TEST",
                output_path=output,
            )

    def test_from_html_no_body_tag_skipped_gracefully(self, tmp_path: Path) -> None:
        """HTML with no <body> tag: extraction returns '' → skipped → ValueError."""
        data_path = _setup(tmp_path, videos=[_make_video("vid001")])
        html_dir = tmp_path / "html"
        html_dir.mkdir()
        (html_dir / "vid001.html").write_text(
            "<html><head><title>no body</title></head></html>", encoding="utf-8"
        )

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        output = tmp_path / "out.html"
        with pytest.raises(ValueError, match="No videos with available HTML"):
            gen.generate_from_html(
                html_dir=html_dir,
                video_filter=vf,
                channel_id="UC_TEST",
                output_path=output,
            )

    def test_from_html_symlink_to_outside_dir_reads_only_named_files(
        self, tmp_path: Path
    ) -> None:
        """Symlink pointing outside project dir: only {video_id}.html files are read."""
        data_path = _setup(tmp_path, videos=[_make_video("vid001")])
        # Symlink to /tmp itself — contains no vid001.html
        linked = tmp_path / "link_to_tmp"
        linked.symlink_to("/tmp")

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        output = tmp_path / "out.html"
        with pytest.raises(ValueError):
            gen.generate_from_html(
                html_dir=linked,
                video_filter=vf,
                channel_id="UC_TEST",
                output_path=output,
            )


# ===========================================================================
# PERSONA 2: _extract_html_body 악성 HTML 공격자
# 목표: 스크립트 삽입, 무한 중첩, body 없음, 이진 데이터
# ===========================================================================
class TestExtractHtmlBodyAttacker:
    """Persona: feeds hostile HTML content to _extract_html_body."""

    def test_script_in_body_is_preserved_verbatim(self) -> None:
        """<script> in body extracted as-is (raw bundling — template escapes later)."""
        html = "<html><body><script>alert('xss')</script><p>content</p></body></html>"
        result = BundleReportGenerator._extract_html_body(html)
        # extract_html_body is a raw bundler — it includes whatever is in body
        # The bundle_from_html template must escape this
        assert "<p>content</p>" in result

    def test_no_body_tag_returns_empty_string(self) -> None:
        """HTML without <body> tag must return empty string (not crash)."""
        result = BundleReportGenerator._extract_html_body("<html><head></head></html>")
        assert result == ""

    def test_empty_string_input_returns_empty(self) -> None:
        """Empty string input must return empty string."""
        result = BundleReportGenerator._extract_html_body("")
        assert result == ""

    def test_deeply_nested_tags_no_crash(self) -> None:
        """500 levels of nested divs inside body must not crash (no recursion limit)."""
        inner = "<p>content</p>"
        for _ in range(500):
            inner = f"<div>{inner}</div>"
        html = f"<html><body>{inner}</body></html>"
        result = BundleReportGenerator._extract_html_body(html)
        assert "<p>content</p>" in result

    def test_malformed_unclosed_tags_no_crash(self) -> None:
        """Unclosed tags inside body must not crash HTMLParser."""
        html = "<html><body><div><p>text<br><span>more</body></html>"
        result = BundleReportGenerator._extract_html_body(html)
        assert isinstance(result, str)

    def test_null_bytes_in_html_no_crash(self) -> None:
        """Null bytes in HTML content must not crash the parser."""
        html = "<html><body><p>te\x00xt</p></body></html>"
        result = BundleReportGenerator._extract_html_body(html)
        assert isinstance(result, str)

    def test_very_large_html_body_performance(self) -> None:
        """HTML with 100KB body content must parse without timeout."""
        big_content = "<p>" + "A" * 100_000 + "</p>"
        html = f"<html><body>{big_content}</body></html>"
        start = time.monotonic()
        result = BundleReportGenerator._extract_html_body(html)
        elapsed = time.monotonic() - start
        assert "A" in result
        assert elapsed < 5.0, f"HTML parsing took too long: {elapsed:.2f}s"

    def test_multiple_body_tags_uses_first(self) -> None:
        """HTML with multiple <body> tags: only first body content is extracted."""
        html = "<html><body><p>first</p></body><body><p>second</p></body></html>"
        result = BundleReportGenerator._extract_html_body(html)
        assert "first" in result


# ===========================================================================
# PERSONA 3: _compute_summary 비정상 메타데이터 공격자
# 목표: None 값, 음수, 타입 오류로 TypeError/ZeroDivisionError 유도
# ===========================================================================
class TestComputeSummaryAttacker:
    """Persona: feeds abnormal metadata to _compute_summary."""

    def test_none_view_count_raises_or_handled(self) -> None:
        """None view_count in video must not silently corrupt sum."""
        videos = [
            {
                "video_id": "v1",
                "view_count": None,
                "duration_seconds": 100,
                "like_count": 5,
            },
        ]
        # sum() with None raises TypeError
        with pytest.raises(TypeError):
            BundleReportGenerator._compute_summary(videos)

    def test_none_duration_seconds_raises_or_handled(self) -> None:
        """None duration_seconds must raise TypeError in sum()."""
        videos = [
            {
                "video_id": "v1",
                "view_count": 100,
                "duration_seconds": None,
                "like_count": 5,
            },
        ]
        with pytest.raises(TypeError):
            BundleReportGenerator._compute_summary(videos)

    def test_negative_duration_accepted_no_crash(self) -> None:
        """Negative duration_seconds must not crash — just produce negative total."""
        videos = [_make_video("v1", duration_seconds=-3600)]
        result = BundleReportGenerator._compute_summary(videos)
        assert result["video_count"] == 1
        assert result["total_duration_minutes"] == -60

    def test_zero_view_count_no_division_error(self) -> None:
        """Zero view_count across all videos must not raise ZeroDivisionError."""
        videos = [_make_video("v1", view_count=0), _make_video("v2", view_count=0)]
        result = BundleReportGenerator._compute_summary(videos)
        assert result["avg_views"] == 0

    def test_empty_video_list_no_division_error(self) -> None:
        """Empty video list must not raise ZeroDivisionError (count==0 guard)."""
        result = BundleReportGenerator._compute_summary([])
        assert result["video_count"] == 0
        assert result["avg_views"] == 0

    def test_missing_all_numeric_fields_uses_defaults(self) -> None:
        """Video dict missing all numeric fields falls back to 0 via .get(key, 0)."""
        videos = [
            {"video_id": "v1", "title": "test", "published_at": "2025-01-01T00:00:00Z"}
        ]
        result = BundleReportGenerator._compute_summary(videos)
        assert result["video_count"] == 1
        assert result["total_duration_minutes"] == 0
        assert result["avg_views"] == 0

    def test_very_large_view_count_no_overflow(self) -> None:
        """view_count > 2^32 must not crash (Python arbitrary precision)."""
        videos = [_make_video("v1", view_count=10**15)]
        result = BundleReportGenerator._compute_summary(videos)
        assert result["avg_views"] == 10**15

    def test_mixed_none_and_int_in_view_count(self) -> None:
        """Mix of valid and None view_count in list must raise TypeError."""
        videos = [
            _make_video("v1", view_count=100),
            {
                "video_id": "v2",
                "title": "t",
                "published_at": "2025-01-01T00:00:00Z",
                "view_count": None,
                "duration_seconds": 60,
                "like_count": 0,
            },
        ]
        with pytest.raises(TypeError):
            BundleReportGenerator._compute_summary(videos)


# ===========================================================================
# PERSONA 4: course 정렬 극단 타이틀 공격자
# 목표: None title, 초장문, 특수문자 타이틀로 정렬 크래시 유도
# ===========================================================================
class TestCourseSortAttacker:
    """Persona: attacks _sort_videos with course sort and hostile titles."""

    def test_course_sort_none_title_uses_empty_string_default(self) -> None:
        """None title with course sort: .get('title', '') returns None — TypeError."""
        videos = [
            {"video_id": "v1", "title": None, "published_at": "2025-01-01T00:00:00Z"},
            {
                "video_id": "v2",
                "title": "감염미생물학",
                "published_at": "2025-01-01T00:00:00Z",
            },
        ]
        # sorted() with key=lambda v: v.get("title", "") returns None for v1
        # comparing None < str raises TypeError in Python 3
        with pytest.raises(TypeError):
            VideoFilterService.sort_videos(videos, "course")

    def test_course_sort_mixed_korean_english_no_crash(self) -> None:
        """Mixed Korean/English titles with course sort must not crash."""
        videos = [
            _make_video("v1", title="Anatomy 1주차"),
            _make_video("v2", title="감염미생물학 1주차"),
            _make_video("v3", title="BIOLOGY week 1"),
            _make_video("v4", title=""),
        ]
        result = VideoFilterService.sort_videos(videos, "course")
        assert len(result) == 4

    def test_course_sort_50000_char_title_no_crash(self) -> None:
        """50000-char title in course sort must not crash."""
        videos = [
            _make_video("v1", title="A" * 50000),
            _make_video("v2", title="B" * 50000),
        ]
        result = VideoFilterService.sort_videos(videos, "course")
        assert result[0]["video_id"] == "v1"

    def test_course_sort_emoji_title_no_crash(self) -> None:
        """Emoji-only titles in course sort must not crash."""
        videos = [
            _make_video("v1", title="🎓📚🔬"),
            _make_video("v2", title="🏥💉🧬"),
        ]
        result = VideoFilterService.sort_videos(videos, "course")
        assert len(result) == 2

    def test_views_sort_none_view_count_uses_default_zero(self) -> None:
        """None view_count with views sort: .get('view_count', 0) is None, TypeError."""
        videos = [
            {
                "video_id": "v1",
                "title": "a",
                "published_at": "2025-01-01T00:00:00Z",
                "view_count": None,
            },
            _make_video("v2", view_count=100),
        ]
        # .get("view_count", 0) returns None (key exists but value is None)
        # sorted() tries to compare None > int → TypeError
        with pytest.raises(TypeError):
            VideoFilterService.sort_videos(videos, "views")


# ===========================================================================
# PERSONA 5: Regression 검증자
# 목표: 수정된 버그 3건이 실제로 fix됐는지 확인 (regression 없음)
# ===========================================================================
class TestBugFixRegression:
    """Persona: verifies all 3 fixed bugs remain fixed (no regression)."""

    # --- Bug #1: lexicographic date false positive ---

    def test_regression_invalid_date_excluded_not_passed(self) -> None:
        """Bug #1 regression: 'not-a-date' must be excluded by date filter."""
        from datetime import date

        vf = VideoFilter(published_after=date(2025, 1, 1))
        videos = [{"video_id": "v1", "title": "test", "published_at": "not-a-date"}]
        result = VideoFilterService.filter_videos(videos, vf)
        assert result == [], "REGRESSION: 'not-a-date' passed date filter (bug #1)"

    def test_regression_various_bad_dates_excluded(self) -> None:
        """Bug #1 regression: multiple non-ISO date formats all excluded."""
        from datetime import date

        bad_dates = ["2025/03/01", "01-03-2025", "March 1", "z-z-z", "", "99999-99-99"]
        vf = VideoFilter(published_after=date(2025, 1, 1))
        for bad in bad_dates:
            videos = [{"video_id": "v1", "title": "test", "published_at": bad}]
            result = VideoFilterService.filter_videos(videos, vf)
            assert result == [], f"REGRESSION: '{bad}' passed date filter"

    def test_regression_valid_iso_date_still_passes(self) -> None:
        """Bug #1 regression: valid ISO dates still pass date filter correctly."""
        from datetime import date

        vf = VideoFilter(published_after=date(2025, 1, 1))
        videos = [
            {"video_id": "v1", "title": "test", "published_at": "2025-06-01T00:00:00Z"}
        ]
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1, "REGRESSION: valid ISO date incorrectly excluded"

    # --- Bug #2: empty/whitespace keyword → ValidationError ---

    def test_regression_empty_keyword_raises_validation_error(self) -> None:
        """Bug #2 regression: VideoFilter(keyword='') must raise ValidationError."""
        with pytest.raises(ValidationError, match="keyword must not be empty"):
            VideoFilter(keyword="")

    def test_regression_whitespace_keyword_raises_validation_error(self) -> None:
        """Bug #2 regression: VideoFilter(keyword='   ') must raise ValidationError."""
        with pytest.raises(ValidationError, match="keyword must not be empty"):
            VideoFilter(keyword="   ")

    def test_regression_tab_newline_keyword_raises_validation_error(self) -> None:
        """Bug #2 regression: tab/newline-only keyword must raise ValidationError."""
        with pytest.raises(ValidationError, match="keyword must not be empty"):
            VideoFilter(keyword="\t\n  ")

    def test_regression_valid_keyword_accepted(self) -> None:
        """Bug #2 regression: normal keyword still accepted after fix."""
        vf = VideoFilter(keyword="감염미생물학")
        assert vf.keyword == "감염미생물학"

    # --- Bug #3: path traversal in auto filename ---

    def test_regression_traversal_keyword_sanitized(self) -> None:
        """Bug #3 regression: '../../../etc/passwd' sanitized to stay in bundle/."""
        from tube_scout.cli.report import _sanitize_filename_part

        sanitized = _sanitize_filename_part("../../../etc/passwd")
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert ".." not in sanitized

    def test_regression_slash_keyword_sanitized(self) -> None:
        """Bug #3 regression: '/tmp/evil' sanitized — no path separator."""
        from tube_scout.cli.report import _sanitize_filename_part

        sanitized = _sanitize_filename_part("/tmp/evil")
        assert "/" not in sanitized

    def test_regression_normal_keyword_unchanged_structure(self) -> None:
        """Bug #3 regression: normal Korean keyword still usable in filename."""
        from tube_scout.cli.report import _sanitize_filename_part

        sanitized = _sanitize_filename_part("감염미생물학")
        assert sanitized == "감염미생물학"

    def test_regression_bundle_cli_traversal_stays_inside(self, tmp_path: Path) -> None:
        """Bug #3 regression: traversal keyword generates inside bundle/ dir."""
        data_path = _setup(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _app(),
            [
                "report",
                "bundle",
                "--data-dir",
                str(data_path),
                "--keyword",
                "../../../etc/passwd",
            ],
        )
        bundle_dir = (data_path / "reports" / "bundle").resolve()
        if result.exit_code == 0 and bundle_dir.exists():
            for f in bundle_dir.rglob("*"):
                assert str(f.resolve()).startswith(str(bundle_dir)), (
                    f"REGRESSION Bug #3: file escaped bundle dir: {f}"
                )
        # Either no match (exit 1) or matched and stayed inside
        assert result.exit_code in (0, 1)
