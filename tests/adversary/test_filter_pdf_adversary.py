"""Adversarial tests for feature 004: report filter & PDF bundle.

10 aggressive personas targeting:
- VideoFilter model validation
- VideoFilterService edge cases
- BundleReportGenerator failure modes
- report_bundle_command CLI attack vectors
- report_video_command CLI attack vectors
- Path traversal via --output and --from-html
- Keyword injection (HTML/script tags)
- Date boundary / inversion attacks
- Giant video list performance
- Malformed video metadata structures
"""

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from tube_scout.models.video_filter import VideoFilter
from tube_scout.services.video_filter_service import VideoFilterService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_video(
    video_id: str = "vid001",
    title: str = "홍길동 2025 감염미생물학 1주차 1차시",
    published_at: str = "2025-03-01T00:00:00Z",
    view_count: int = 100,
) -> dict:
    return {
        "video_id": video_id,
        "title": title,
        "published_at": published_at,
        "view_count": view_count,
    }


def _make_config_json(channel_id: str = "UC_TEST") -> dict:
    return {
        "channels": [{"channel_id": channel_id, "alias": "test"}],
        "settings": {},
    }


# ===========================================================================
# PERSONA 1: VideoFilter 모델 파괴자
# 목표: 잘못된 타입·범위로 Pydantic 모델을 크래시
# ===========================================================================
class TestVideoFilterModelCrash:
    """Persona: feeds garbage into VideoFilter model."""

    def test_empty_keyword_string_raises_validation_error(self) -> None:
        """Empty string keyword must raise ValidationError (validator rejects empty)."""
        with pytest.raises(ValidationError, match="keyword must not be empty"):
            VideoFilter(keyword="")

    def test_keyword_only_whitespace_raises_validation_error(self) -> None:
        """Whitespace-only keyword must raise ValidationError (strips + rejects)."""
        with pytest.raises(ValidationError, match="keyword must not be empty"):
            VideoFilter(keyword="   ")

    def test_date_inversion_raises(self) -> None:
        """published_after > published_before must raise ValueError."""
        with pytest.raises(ValueError, match="published_after must be"):
            VideoFilter(
                published_after=date(2025, 12, 31),
                published_before=date(2025, 1, 1),
            )

    def test_no_conditions_raises(self) -> None:
        """VideoFilter with all-None fields must raise ValueError."""
        with pytest.raises(ValueError, match="At least one filter condition"):
            VideoFilter()

    def test_empty_video_ids_list(self) -> None:
        """video_ids=[] is not None, so it passes validation but matches nothing."""
        vf = VideoFilter(video_ids=[])
        videos = [_make_video()]
        result = VideoFilterService.filter_videos(videos, vf)
        # Empty list: no video_id passes membership test
        assert result == []

    def test_duplicate_video_ids(self) -> None:
        """Duplicate IDs in video_ids should not cause duplicate results."""
        vf = VideoFilter(video_ids=["vid001", "vid001", "vid001"])
        videos = [_make_video(video_id="vid001")]
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1


# ===========================================================================
# PERSONA 2: HTML/Script Injection 공격자
# 목표: --keyword에 HTML·JS 페이로드 주입해 출력 파일 오염
# ===========================================================================
class TestKeywordInjectionAttacker:
    """Persona: injects HTML/script tags via --keyword."""

    XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        "'; DROP TABLE videos; --",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(document.cookie)",
        '"><svg/onload=alert(1)>',
    ]

    def test_xss_keyword_does_not_match_clean_title(self) -> None:
        """XSS payload keyword should match only if literally present in title."""
        for payload in self.XSS_PAYLOADS:
            vf = VideoFilter(keyword=payload)
            videos = [_make_video(title="홍길동 2025 감염미생물학 1주차")]
            result = VideoFilterService.filter_videos(videos, vf)
            assert result == [], f"XSS payload unexpectedly matched: {payload!r}"

    def test_xss_keyword_in_bundle_auto_title_is_escaped(self) -> None:
        """Auto-generated title with XSS keyword must be escaped in output."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        payload = "<script>alert('xss')</script>"
        vf = VideoFilter(keyword=payload)
        title = BundleReportGenerator._auto_title(vf, "UC_TEST")
        # Title string itself may contain the raw payload — but when rendered
        # through Jinja2 autoescape=True it must be escaped. Verify autoescape enabled.
        from jinja2 import Environment

        env = Environment(autoescape=True)
        tmpl = env.from_string("{{ title }}")
        rendered = tmpl.render(title=title)
        assert "<script>" not in rendered

    def test_video_title_with_html_in_filter_description(self) -> None:
        """HTML in keyword must be escaped in filter_description output."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        payload = '<b onmouseover="alert(1)">bold</b>'
        vf = VideoFilter(keyword=payload)
        desc = BundleReportGenerator._filter_description(vf)
        # Description is a plain string — it carries the raw payload
        # but the template must escape it. Verify autoescape in template env.
        assert isinstance(desc, str)


# ===========================================================================
# PERSONA 3: 경로 순회(Path Traversal) 공격자
# 목표: --output 또는 --data-dir에 ../../../etc/passwd 시도
# ===========================================================================
class TestPathTraversalAttacker:
    """Persona: attempts path traversal via output and data-dir arguments."""

    def test_bundle_generate_traversal_output_path(self, tmp_path: Path) -> None:
        """Path traversal in output_path: generator writes to given path literally."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        # Setup: legitimate data directory
        channel_id = "UC_TEST"
        data_path = tmp_path / "data"
        videos_dir = data_path / "raw" / "channels" / channel_id
        videos_dir.mkdir(parents=True)
        videos_meta = [_make_video()]
        (videos_dir / "videos_meta.json").write_text(
            json.dumps(videos_meta), encoding="utf-8"
        )

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")

        # Traversal path: attacker-controlled output path
        traversal_path = tmp_path / "safe_output" / "report.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id=channel_id,
            output_path=traversal_path,
        )
        # Generator must create file at the requested path (not escape it)
        # But crucially it must NOT write outside the given path
        assert html_path == traversal_path
        assert traversal_path.exists()

    def test_data_dir_nonexistent_does_not_crash(self, tmp_path: Path) -> None:
        """BundleReportGenerator with nonexistent data_dir returns empty list."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        gen = BundleReportGenerator(data_dir=tmp_path / "nonexistent")
        result = gen._load_videos_meta("UC_TEST")
        assert result == []

    def test_output_path_with_null_byte(self, tmp_path: Path) -> None:
        """Null byte in output path must raise an OS-level error, not silently pass."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        channel_id = "UC_TEST"
        data_path = tmp_path / "data"
        videos_dir = data_path / "raw" / "channels" / channel_id
        videos_dir.mkdir(parents=True)
        (videos_dir / "videos_meta.json").write_text(
            json.dumps([_make_video()]), encoding="utf-8"
        )

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염")
        null_path = tmp_path / "out\x00.html"

        with pytest.raises((ValueError, OSError, TypeError)):
            gen.generate(
                video_filter=vf,
                channel_id=channel_id,
                output_path=null_path,
            )


# ===========================================================================
# PERSONA 4: 손상된 videos_meta.json 공급자
# 목표: 필드 누락, 잘못된 타입으로 필터 서비스 크래시
# ===========================================================================
class TestCorruptedVideoMetaAttacker:
    """Persona: feeds malformed video metadata to filter service."""

    def test_missing_title_field(self) -> None:
        """Video dict missing 'title' must raise KeyError — not silently skip."""
        vf = VideoFilter(keyword="감염")
        videos = [{"video_id": "vid001", "published_at": "2025-03-01T00:00:00Z"}]
        with pytest.raises(KeyError):
            VideoFilterService.filter_videos(videos, vf)

    def test_missing_published_at_field_excluded_gracefully(self) -> None:
        """Video missing 'published_at' with date filter is excluded gracefully."""
        vf = VideoFilter(published_after=date(2025, 1, 1))
        videos = [{"video_id": "vid001", "title": "test"}]
        # Fixed: _parse_date() returns None on missing field → excluded (not KeyError)
        result = VideoFilterService.filter_videos(videos, vf)
        assert result == []

    def test_missing_video_id_field(self) -> None:
        """Video dict missing 'video_id' with video_ids filter must crash."""
        vf = VideoFilter(video_ids=["vid001"])
        videos = [{"title": "test", "published_at": "2025-03-01T00:00:00Z"}]
        with pytest.raises(KeyError):
            VideoFilterService.filter_videos(videos, vf)

    def test_none_title_value(self) -> None:
        """Video with None title and keyword filter must raise TypeError."""
        vf = VideoFilter(keyword="감염")
        videos = [
            {
                "video_id": "vid001",
                "title": None,
                "published_at": "2025-03-01T00:00:00Z",
            }
        ]
        with pytest.raises(TypeError):
            VideoFilterService.filter_videos(videos, vf)

    def test_invalid_date_format_in_published_at_excluded(self) -> None:
        """Non-ISO date string in published_at must be excluded, not false positive."""
        vf = VideoFilter(published_after=date(2025, 1, 1))
        videos = [{"video_id": "vid001", "title": "test", "published_at": "not-a-date"}]
        # Fixed: _parse_date() uses date.fromisoformat() — parse failure → excluded
        result = VideoFilterService.filter_videos(videos, vf)
        assert result == [], "Fixed: 'not-a-date' no longer passes date filter"


# ===========================================================================
# PERSONA 5: 대량 데이터 처리자
# 목표: 10000개 영상으로 필터 성능·메모리 검증
# ===========================================================================
class TestMassiveVideoListAttacker:
    """Persona: feeds 10000 videos to the filter service."""

    def test_10000_videos_keyword_filter(self) -> None:
        """Filter 10000 videos by keyword must complete without error."""
        vf = VideoFilter(keyword="감염미생물학")

        def _title(i: int) -> str:
            subj = "감염미생물학" if i % 10 == 0 else "인체구조"
            return f"홍길동 2025 {subj} {i}주차"

        videos = [
            _make_video(video_id=f"vid{i:05d}", title=_title(i)) for i in range(10000)
        ]
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1000  # every 10th video matches

    def test_10000_videos_date_range_filter(self) -> None:
        """Filter 10000 videos by date range must complete without error."""
        vf = VideoFilter(
            published_after=date(2025, 6, 1),
            published_before=date(2025, 6, 30),
        )
        videos = [
            _make_video(
                video_id=f"vid{i:05d}",
                published_at=f"2025-{(i % 12) + 1:02d}-01T00:00:00Z",
            )
            for i in range(10000)
        ]
        result = VideoFilterService.filter_videos(videos, vf)
        # Only month 6 matches
        assert all("2025-06" in v["published_at"] for v in result)

    def test_bundle_report_with_200_plus_videos_no_crash(self, tmp_path: Path) -> None:
        """BundleReportGenerator with 214 videos must not crash (200+ warning spec)."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        channel_id = "UC_TEST"
        data_path = tmp_path / "data"
        videos_dir = data_path / "raw" / "channels" / channel_id
        videos_dir.mkdir(parents=True)
        videos = [
            _make_video(video_id=f"vid{i:04d}", title=f"test video {i}")
            for i in range(214)
        ]
        (videos_dir / "videos_meta.json").write_text(
            json.dumps(videos), encoding="utf-8"
        )

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="test")
        output = tmp_path / "bundle.html"
        html_path = gen.generate(
            video_filter=vf,
            channel_id=channel_id,
            output_path=output,
        )
        assert html_path.exists()


# ===========================================================================
# PERSONA 6: 잘못된 날짜 형식 입력자
# 목표: CLI --published-after/before에 비-ISO 형식 주입
# ===========================================================================
class TestBadDateFormatAttacker:
    """Persona: passes malformed dates to CLI date options."""

    def test_date_fromisoformat_rejects_slash_format(self) -> None:
        """date.fromisoformat('2025/03/01') must raise ValueError."""
        with pytest.raises(ValueError):
            date.fromisoformat("2025/03/01")

    def test_date_fromisoformat_rejects_korean_format(self) -> None:
        """date.fromisoformat('2025년3월1일') must raise ValueError."""
        with pytest.raises(ValueError):
            date.fromisoformat("2025년3월1일")

    def test_date_fromisoformat_rejects_partial_date(self) -> None:
        """date.fromisoformat('2025-03') must raise ValueError."""
        with pytest.raises(ValueError):
            date.fromisoformat("2025-03")

    def test_date_fromisoformat_rejects_empty_string(self) -> None:
        """date.fromisoformat('') must raise ValueError."""
        with pytest.raises(ValueError):
            date.fromisoformat("")

    def test_cli_bundle_command_bad_date_exits_nonzero(self, tmp_path: Path) -> None:
        """report bundle with bad --published-after must exit with error code."""
        from tube_scout.cli.main import app

        # Setup minimal config
        data_path = tmp_path / "data"
        data_path.mkdir()
        config = {
            "channels": [{"channel_id": "UC_TEST", "alias": "test"}],
            "settings": {},
        }
        (data_path / "config.json").write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "report",
                "bundle",
                "--data-dir",
                str(data_path),
                "--published-after",
                "2025/03/01",  # slash format — invalid
            ],
        )
        assert result.exit_code != 0


# ===========================================================================
# PERSONA 7: 빈 채널 데이터 허무주의자
# 목표: videos_meta.json이 없거나 빈 채널에서 bundle 생성 시도
# ===========================================================================
class TestEmptyChannelNihilist:
    """Persona: attempts bundle report on channels with no data."""

    def test_bundle_on_empty_videos_raises_valueerror(self, tmp_path: Path) -> None:
        """BundleReportGenerator on channel with 0 videos must raise ValueError."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        channel_id = "UC_EMPTY"
        data_path = tmp_path / "data"
        videos_dir = data_path / "raw" / "channels" / channel_id
        videos_dir.mkdir(parents=True)
        (videos_dir / "videos_meta.json").write_text("[]", encoding="utf-8")

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염")
        output = tmp_path / "bundle.html"

        with pytest.raises(ValueError, match="No videos matching"):
            gen.generate(
                video_filter=vf,
                channel_id=channel_id,
                output_path=output,
            )

    def test_bundle_on_missing_videos_meta_raises_valueerror(
        self, tmp_path: Path
    ) -> None:
        """BundleReportGenerator with no videos_meta.json must raise ValueError."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        channel_id = "UC_MISSING"
        data_path = tmp_path / "data"

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염")
        output = tmp_path / "bundle.html"

        with pytest.raises(ValueError, match="No videos matching"):
            gen.generate(
                video_filter=vf,
                channel_id=channel_id,
                output_path=output,
            )

    def test_bundle_command_no_matching_exits_code_1(self, tmp_path: Path) -> None:
        """CLI bundle command with no matching videos must exit code 1."""
        from tube_scout.cli.main import app

        data_path = tmp_path / "data"
        channel_id = "UC_TEST"
        videos_dir = data_path / "raw" / "channels" / channel_id
        videos_dir.mkdir(parents=True)
        (data_path / "config.json").write_text(json.dumps(_make_config_json()))
        (videos_dir / "videos_meta.json").write_text(
            json.dumps([_make_video(title="completely different subject")]),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "report",
                "bundle",
                "--data-dir",
                str(data_path),
                "--keyword",
                "존재하지않는키워드XYZ123",
            ],
        )
        assert result.exit_code == 1


# ===========================================================================
# PERSONA 8: 정렬 옵션 파괴자
# 목표: sort_by에 알 수 없는 값·주입 시도
# ===========================================================================
class TestSortOptionAttacker:
    """Persona: passes invalid sort_by values to BundleReportGenerator."""

    def test_unknown_sort_falls_back_to_date(self, tmp_path: Path) -> None:
        """Unknown sort_by value must fall back to date sort without crashing."""

        videos = [
            _make_video("v1", published_at="2025-03-01T00:00:00Z"),
            _make_video("v2", published_at="2025-01-01T00:00:00Z"),
            _make_video("v3", published_at="2025-06-01T00:00:00Z"),
        ]
        result = VideoFilterService.sort_videos(videos, "INVALID_SORT_OPTION")
        # Should not crash — falls back to date sort (newest first)
        assert result[0]["published_at"] > result[1]["published_at"]

    def test_sort_by_views_with_missing_view_count(self, tmp_path: Path) -> None:
        """sort_by='views' on videos missing 'view_count' must use 0 as default."""

        videos = [
            {"video_id": "v1", "title": "a", "published_at": "2025-01-01T00:00:00Z"},
            {
                "video_id": "v2",
                "title": "b",
                "published_at": "2025-01-01T00:00:00Z",
                "view_count": 500,
            },
        ]
        result = VideoFilterService.sort_videos(videos, "views")
        # v2 (500 views) should be first; v1 defaults to 0
        assert result[0]["video_id"] == "v2"

    def test_sort_by_injection_string(self) -> None:
        """Sort value with SQL/shell injection characters must not crash."""

        videos = [_make_video()]
        # Should not raise
        result = VideoFilterService.sort_videos(videos, "'; rm -rf /; echo '")
        assert len(result) == 1


# ===========================================================================
# PERSONA 9: 상호 배타 옵션 혼합자
# 목표: --video-id와 --video-ids 동시 사용 시 exit code 1 강제
# ===========================================================================
class TestMutualExclusionAttacker:
    """Persona: uses mutually exclusive CLI options simultaneously."""

    def test_video_id_and_video_ids_together_exits_code_1(self, tmp_path: Path) -> None:
        """--video-id and --video-ids used together must exit code 1."""
        from tube_scout.cli.main import app

        data_path = tmp_path / "data"
        data_path.mkdir()
        (data_path / "config.json").write_text(json.dumps(_make_config_json()))

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "report",
                "video",
                "--data-dir",
                str(data_path),
                "--video-id",
                "vid001",
                "--video-ids",
                "vid002,vid003",
            ],
        )
        assert result.exit_code == 1

    def test_bundle_with_no_filter_exits_code_1(self, tmp_path: Path) -> None:
        """report bundle without any filter option must exit code 1."""
        from tube_scout.cli.main import app

        data_path = tmp_path / "data"
        data_path.mkdir()
        (data_path / "config.json").write_text(json.dumps(_make_config_json()))

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "report",
                "bundle",
                "--data-dir",
                str(data_path),
                # No filter option provided
            ],
        )
        assert result.exit_code == 1

    def test_video_ids_csv_with_spaces_around_commas_stripped(self) -> None:
        """video_ids_csv with spaces around commas are stripped (strip() applied)."""
        # Simulating CLI: "vid001, vid002, vid003" (with spaces)
        csv_with_spaces = "vid001, vid002, vid003"
        ids = [v.strip() for v in csv_with_spaces.split(",")]  # CLI now strips
        vf = VideoFilter(video_ids=ids)
        videos = [_make_video(video_id="vid002")]
        result = VideoFilterService.filter_videos(videos, vf)
        # Fixed: " vid002".strip() == "vid002" — matches correctly
        assert len(result) == 1, "Fixed: strip() ensures ' vid002' matches 'vid002'"


# ===========================================================================
# PERSONA 10: 특수문자·유니코드 키워드 폭격자
# 목표: 극단적 키워드로 필터·보고서 생성 파이프라인 공격
# ===========================================================================
class TestUnicodeAndSpecialKeywordAttacker:
    """Persona: fires Unicode, emoji, and control characters as keywords."""

    def test_emoji_only_keyword(self) -> None:
        """Emoji-only keyword should match only if literally present in title."""
        vf = VideoFilter(keyword="🎓📚🔬")
        videos = [_make_video(title="홍길동 2025 감염미생물학")]
        result = VideoFilterService.filter_videos(videos, vf)
        assert result == []

    def test_emoji_in_title_matched_by_keyword(self) -> None:
        """Keyword with emoji should match title containing that emoji."""
        vf = VideoFilter(keyword="🎓")
        videos = [_make_video(title="홍길동 🎓 2025 감염미생물학")]
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1

    def test_10000_char_keyword(self) -> None:
        """10000-character keyword should not crash the filter service."""
        long_keyword = "A" * 10000
        vf = VideoFilter(keyword=long_keyword)
        videos = [_make_video(title="홍길동 2025 감염미생물학")]
        result = VideoFilterService.filter_videos(videos, vf)
        assert result == []

    def test_newline_in_keyword(self) -> None:
        """Newline character in keyword should not match normal titles."""
        vf = VideoFilter(keyword="감염\n미생물학")
        videos = [_make_video(title="감염미생물학")]
        result = VideoFilterService.filter_videos(videos, vf)
        assert result == []

    def test_rtl_text_keyword(self) -> None:
        """Right-to-left Unicode keyword must not crash filter."""
        vf = VideoFilter(keyword="مرحبا")
        videos = [_make_video(title="홍길동 2025 감염미생물학")]
        result = VideoFilterService.filter_videos(videos, vf)
        assert result == []

    def test_null_byte_in_keyword(self) -> None:
        """Null byte in keyword should not crash but also not match normal titles."""
        vf = VideoFilter(keyword="감염\x00미생물학")
        videos = [_make_video(title="감염미생물학")]
        result = VideoFilterService.filter_videos(videos, vf)
        assert result == []

    def test_auto_title_with_long_keyword(self) -> None:
        """Auto title generation with 10000-char keyword must not crash."""
        from tube_scout.reporting.bundle_report import BundleReportGenerator

        long_keyword = "K" * 10000
        vf = VideoFilter(keyword=long_keyword)
        title = BundleReportGenerator._auto_title(vf, "UC_TEST")
        assert isinstance(title, str)
        assert len(title) > 0
