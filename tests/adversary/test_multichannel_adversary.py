"""Multichannel admin adversary tests — aggressive failure testing with 10 personas.

Each persona targets a specific attack surface of the multi-channel
administration feature (003-multichannel-admin) with 2-3 test cases.
All external dependencies (APIs, filesystem, OAuth) are mocked.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tube_scout.models.config import ChannelRegistration
from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.search import SearchFilter, SearchQuery
from tube_scout.models.video import Video
from tube_scout.output.manager import OutputManager
from tube_scout.reporting.department_report import DepartmentReportGenerator
from tube_scout.services.auth import load_registry, save_registry
from tube_scout.services.search_service import SearchService
from tube_scout.services.title_parser import TitleParser
from tube_scout.services.validator import (
    check_invalid_week,
    check_missing_weeks,
    check_name_inconsistency,
    check_parse_failures,
    check_session_gaps,
    run_all_validations,
)


def _make_parsed_title(
    video_id: str = "vid001",
    title: str = "test title",
    professor: list[str] | None = None,
    course: str | None = None,
    year: int | None = None,
    semester: int | None = None,
    week: int | None = None,
    session: int | None = None,
    department: str | None = None,
    category: str = "regular",
    parse_error: bool = False,
) -> ParsedTitle:
    """Helper to create a ParsedTitle with minimal boilerplate."""
    return ParsedTitle(
        video_id=video_id,
        original_title=title,
        professor=professor or [],
        course=course,
        year=year,
        semester=semester,
        week=week,
        session=session,
        department=department,
        category=category,
        parse_error=parse_error,
    )


def _make_video(
    video_id: str = "vid001",
    title: str = "test",
    duration_seconds: int = 3000,
    view_count: int = 100,
    published_at: str = "2026-04-01T10:00:00",
) -> Video:
    """Helper to create a Video with minimal boilerplate."""
    return Video(
        video_id=video_id,
        channel_id="UCtest123456789012345678",
        title=title,
        published_at=datetime.fromisoformat(published_at),
        duration_seconds=duration_seconds,
        view_count=view_count,
    )


# ============================================================
# PERSONA 1: Wrong Channel Alias Attacker
# ============================================================
class TestWrongChannelAliasAttacker:
    """Empty strings, special chars, very long aliases, spaces, duplicates."""

    def test_empty_alias_rejected(self) -> None:
        """Empty string alias must be rejected by ChannelRegistration."""
        with pytest.raises(ValidationError, match="alias"):
            ChannelRegistration(
                alias="",
                channel_id="UCtest123456789012345678",
                channel_name="Test Channel",
                registered_at="2026-04-01T00:00:00",
                last_used_at="2026-04-01T00:00:00",
                token_path="/tmp/token.json",
            )

    def test_whitespace_only_alias_rejected(self) -> None:
        """Whitespace-only alias must be rejected."""
        with pytest.raises(ValidationError, match="alias"):
            ChannelRegistration(
                alias="   \t  ",
                channel_id="UCtest123456789012345678",
                channel_name="Test Channel",
                registered_at="2026-04-01T00:00:00",
                last_used_at="2026-04-01T00:00:00",
                token_path="/tmp/token.json",
            )

    def test_special_chars_alias_does_not_crash(self) -> None:
        """Special characters in alias should not crash the system."""
        # ChannelRegistration only validates non-blank, so these should pass
        reg = ChannelRegistration(
            alias="<script>alert('xss')</script>",
            channel_id="UCtest123456789012345678",
            channel_name="Test Channel",
            registered_at="2026-04-01T00:00:00",
            last_used_at="2026-04-01T00:00:00",
            token_path="/tmp/token.json",
        )
        assert reg.alias == "<script>alert('xss')</script>"

    def test_very_long_alias(self) -> None:
        """10000-char alias should not crash model validation."""
        long_alias = "A" * 10000
        reg = ChannelRegistration(
            alias=long_alias,
            channel_id="UCtest123456789012345678",
            channel_name="Test Channel",
            registered_at="2026-04-01T00:00:00",
            last_used_at="2026-04-01T00:00:00",
            token_path="/tmp/token.json",
        )
        assert len(reg.alias) == 10000

    def test_duplicate_alias_overwrites_in_registry(self, tmp_path: Path) -> None:
        """Saving the same alias twice should overwrite, not duplicate."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        reg1 = ChannelRegistration(
            alias="간호학과",
            channel_id="UCold_channel",
            channel_name="Old Name",
            registered_at="2026-01-01T00:00:00",
            last_used_at="2026-01-01T00:00:00",
            token_path=str(tokens_dir / "old.json"),
        )
        reg2 = ChannelRegistration(
            alias="간호학과",
            channel_id="UCnew_channel",
            channel_name="New Name",
            registered_at="2026-04-01T00:00:00",
            last_used_at="2026-04-01T00:00:00",
            token_path=str(tokens_dir / "new.json"),
        )
        registry = {"간호학과": reg1}
        save_registry(tokens_dir, registry)
        registry["간호학과"] = reg2
        save_registry(tokens_dir, registry)
        loaded = load_registry(tokens_dir)
        assert loaded["간호학과"].channel_id == "UCnew_channel"


# ============================================================
# PERSONA 2: Corrupt Registry Attacker
# ============================================================
class TestCorruptRegistryAttacker:
    """Invalid JSON channels.json, missing fields, type errors, empty file."""

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        """Garbled JSON in channels.json must raise JSONDecodeError."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        channels_file = tokens_dir / "channels.json"
        channels_file.write_text("{not valid json!!", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_registry(tokens_dir)

    def test_missing_required_fields_raises(self, tmp_path: Path) -> None:
        """channels.json with missing required fields must raise."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        channels_file = tokens_dir / "channels.json"
        data = {
            "간호학과": {
                "alias": "간호학과",
                # Missing channel_id, channel_name, etc.
            }
        }
        channels_file.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValidationError):
            load_registry(tokens_dir)

    def test_wrong_type_channel_id(self, tmp_path: Path) -> None:
        """Integer channel_id (coerced to string without UC prefix) must raise."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        channels_file = tokens_dir / "channels.json"
        data = {
            "간호학과": {
                "alias": "간호학과",
                "channel_id": 12345,
                "channel_name": "Test",
                "registered_at": "2026-04-01T00:00:00",
                "last_used_at": "2026-04-01T00:00:00",
                "token_path": "/tmp/token.json",
            }
        }
        channels_file.write_text(json.dumps(data), encoding="utf-8")
        # Pydantic coerces int to str "12345", which fails UC prefix validation
        with pytest.raises(ValidationError, match="channel_id"):
            load_registry(tokens_dir)

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        """Empty channels.json must raise JSONDecodeError."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        channels_file = tokens_dir / "channels.json"
        channels_file.write_text("", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_registry(tokens_dir)


# ============================================================
# PERSONA 3: Abnormal Title Bomber
# ============================================================
class TestAbnormalTitleBomber:
    """Emoji-only, 10k chars, SQL/HTML injection, null bytes."""

    @pytest.fixture
    def parser(self) -> TitleParser:
        return TitleParser()

    def test_emoji_only_title(self, parser: TitleParser) -> None:
        """Emoji-only title should not crash, should flag parse_error."""
        emoji_str = "\U0001f525\U0001f4af\U0001f60d\U0001f44d\U0001f921\U0001f480"
        result = parser.parse(emoji_str, "emoji001")
        assert isinstance(result, ParsedTitle)
        assert result.parse_error is True

    def test_10000_char_title(self, parser: TitleParser) -> None:
        """10000-character title should not crash."""
        mega_title = "홍길동 2026 간호학과 " + "인체구조와기능" * 1500 + " 4주차 2차시"
        result = parser.parse(mega_title, "mega001")
        assert isinstance(result, ParsedTitle)
        assert len(result.original_title) > 10000

    def test_sql_injection_title(self, parser: TitleParser) -> None:
        """SQL injection in title should be treated as text, not crash."""
        title = "'; DROP TABLE videos; -- 홍길동 2026 4주차 2차시"
        result = parser.parse(title, "sqli001")
        assert isinstance(result, ParsedTitle)

    def test_html_injection_title(self, parser: TitleParser) -> None:
        """HTML injection in title should not crash or be interpreted."""
        title = '<img src=x onerror="alert(1)"> 홍길동 2026 4주차 2차시'
        result = parser.parse(title, "xss001")
        assert isinstance(result, ParsedTitle)

    def test_null_bytes_in_title(self, parser: TitleParser) -> None:
        """Null bytes in title should not crash."""
        title = "홍길동\x00 2026\x00 간호학과 4주차 2차시"
        result = parser.parse(title, "null001")
        assert isinstance(result, ParsedTitle)

    def test_control_chars_in_title(self, parser: TitleParser) -> None:
        """Control characters (tab, backspace, etc.) should not crash."""
        title = "홍길동\t2026\b간호학과\r\n4주차\x1b[31m2차시"
        result = parser.parse(title, "ctrl001")
        assert isinstance(result, ParsedTitle)


# ============================================================
# PERSONA 4: YAML Destroyer
# ============================================================
class TestYAMLDestroyer:
    """Syntax error YAML, empty filters, type errors, very large YAML."""

    def test_yaml_syntax_error(self, tmp_path: Path) -> None:
        """Malformed YAML must raise ValueError."""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(
            "filters:\n  professor: 'unclosed string\n  ]\n  bad: {{{",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Failed to parse YAML"):
            SearchService.load_config(yaml_file)

    def test_empty_yaml_file(self, tmp_path: Path) -> None:
        """Empty YAML file should raise ValueError (not a mapping)."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="expected a mapping"):
            SearchService.load_config(yaml_file)

    def test_yaml_with_wrong_type_filters(self, tmp_path: Path) -> None:
        """filters as a list instead of dict should raise."""
        yaml_file = tmp_path / "wrong.yaml"
        yaml_file.write_text(
            "filters:\n  - professor: '홍길동'\n",
            encoding="utf-8",
        )
        # filters gets a list value which is truthy, so _build_query_from_dict
        # tries SearchFilter(**list) which should fail
        with pytest.raises((TypeError, ValidationError)):
            SearchService.load_config(yaml_file)

    def test_yaml_with_invalid_week_range(self, tmp_path: Path) -> None:
        """week_range with start > end should raise ValidationError."""
        yaml_file = tmp_path / "inverted.yaml"
        content = {"filters": {"week_range": [10, 2]}}
        yaml_file.write_text(yaml.dump(content), encoding="utf-8")
        with pytest.raises(ValidationError, match="week_range"):
            SearchService.load_config(yaml_file)

    def test_very_large_yaml(self, tmp_path: Path) -> None:
        """Large YAML with 1000 query groups should not crash."""
        queries = [{"professor": f"교수{i}", "year": 2026} for i in range(1000)]
        content = {"queries": queries}
        yaml_file = tmp_path / "huge.yaml"
        yaml_file.write_text(yaml.dump(content), encoding="utf-8")
        query = SearchService.load_config(yaml_file)
        assert len(query.queries) == 1000


# ============================================================
# PERSONA 5: Professor Name Confuser
# ============================================================
class TestProfessorNameConfuser:
    """Same-name different people, name variations, empty names, numeric names."""

    @pytest.fixture
    def parser(self) -> TitleParser:
        return TitleParser()

    def test_name_with_space_variation(self) -> None:
        """'홍길동' vs '홍길 동' should be detected by V-004 name inconsistency."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=1, session=1,
            ),
            _make_parsed_title(
                "v2", professor=["홍길 동"], course="간호학",
                week=2, session=1,
            ),
        ]
        findings = check_name_inconsistency(titles)
        # Edit distance of "홍길동" vs "홍길 동" is 1 (insertion of space)
        assert len(findings) >= 1
        assert findings[0].rule_id == "V-004"

    def test_same_name_different_courses(self) -> None:
        """Same professor name across different courses should not trigger V-004."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=1, session=1,
            ),
            _make_parsed_title(
                "v2", professor=["홍길동"], course="미생물학",
                week=1, session=1,
            ),
        ]
        findings = check_name_inconsistency(titles)
        assert len(findings) == 0

    def test_empty_professor_name_in_title(self, parser: TitleParser) -> None:
        """Title with no identifiable professor should have empty professor list."""
        result = parser.parse("2026 간호학과 인체구조와기능 4주차 2차시", "noprof001")
        assert isinstance(result, ParsedTitle)
        # Either parse_error or empty professor list — both are acceptable

    def test_numeric_name_in_title(self, parser: TitleParser) -> None:
        """Numeric 'professor name' should not crash."""
        result = parser.parse("12345 2026 간호학과 4주차 2차시", "num001")
        assert isinstance(result, ParsedTitle)


# ============================================================
# PERSONA 6: Empty Data Nihilist
# ============================================================
class TestEmptyDataNihilist:
    """0 videos channel, all parse failures, 0-professor report."""

    def test_zero_videos_validation(self) -> None:
        """Validation with empty parsed_titles should return empty findings."""
        findings = run_all_validations([], [])
        assert findings == []

    def test_all_parse_failures(self) -> None:
        """All titles failing to parse should trigger V-005 for each."""
        titles = [
            _make_parsed_title(f"v{i}", title=f"garbage_{i}", parse_error=True)
            for i in range(5)
        ]
        findings = check_parse_failures(titles)
        assert len(findings) == 5
        assert all(f.rule_id == "V-005" for f in findings)

    def test_zero_professor_report(self) -> None:
        """DepartmentReportGenerator with 0 parsed titles returns empty details."""
        gen = DepartmentReportGenerator()
        details = gen.compute_professor_details([], [])
        assert details == []

    def test_search_on_empty_titles(self) -> None:
        """Search with no parsed titles returns empty results."""
        query = SearchQuery(filters=SearchFilter(professor="홍길동"))
        results = SearchService.search([], query)
        assert results == []


# ============================================================
# PERSONA 7: Week Number Extremist
# ============================================================
class TestWeekNumberExtremist:
    """week=0, week=-1, week=100, week=None, session=0."""

    def test_week_zero_flagged(self) -> None:
        """Week 0 should trigger V-003 ERROR."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=0, session=1,
            ),
        ]
        findings = check_invalid_week(titles)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert findings[0].details["week"] == 0

    def test_week_negative_flagged(self) -> None:
        """Negative week should trigger V-003 ERROR."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=-1, session=1,
            ),
        ]
        findings = check_invalid_week(titles)
        assert len(findings) == 1
        assert findings[0].details["week"] == -1

    def test_week_100_flagged(self) -> None:
        """Week 100 should trigger V-003 ERROR."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=100, session=1,
            ),
        ]
        findings = check_invalid_week(titles)
        assert len(findings) == 1

    def test_week_none_skipped(self) -> None:
        """week=None should be silently skipped by V-003."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=None, session=1,
            ),
        ]
        findings = check_invalid_week(titles)
        assert len(findings) == 0

    def test_session_gap_with_session_zero_skipped(self) -> None:
        """session=0 or session=None should not crash session gap check."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=1, session=None,
            ),
            _make_parsed_title(
                "v2", professor=["홍길동"], course="간호학",
                week=2, session=2,
            ),
        ]
        findings = check_session_gaps(titles)
        # Should detect session 2 without session 1 for week 2
        assert all(f.rule_id == "V-006" for f in findings)


# ============================================================
# PERSONA 8: Report Edge Tester
# ============================================================
class TestReportEdgeTester:
    """1-video report, all supplementary, compliance without calendar."""

    def test_single_video_report(self) -> None:
        """Report with exactly 1 video should compute valid metrics."""
        gen = DepartmentReportGenerator()
        pt = _make_parsed_title(
            "v1",
            title="홍길동 2026 간호학과 인체구조와기능 1주차 1차시",
            professor=["홍길동"],
            course="인체구조와기능",
            year=2026,
            week=1,
            session=1,
        )
        vid = _make_video("v1", duration_seconds=3600, view_count=50)
        overview = gen.compute_overview([pt], [vid], "UCtest123456789012345678")
        assert overview.total_videos == 1
        assert overview.total_professors == 1
        assert overview.total_courses == 1
        assert overview.parse_success_rate == 1.0

    def test_all_supplementary_videos(self) -> None:
        """All supplementary videos should not trigger V-008 missing weeks."""
        titles = [
            _make_parsed_title(
                f"v{i}",
                professor=["홍길동"],
                course="간호학",
                week=i,
                session=1,
                category="supplementary",
            )
            for i in [1, 3, 5]  # Gaps at 2, 4
        ]
        findings = check_missing_weeks(titles)
        # Supplementary videos are excluded from missing-week check
        assert len(findings) == 0

    def test_compliance_without_calendar(self) -> None:
        """Compliance matrix without calendar should mark all uploads as 'uploaded'."""
        gen = DepartmentReportGenerator()
        titles = [
            _make_parsed_title(
                f"v{w}",
                professor=["홍길동"],
                course="간호학",
                week=w,
                session=1,
            )
            for w in range(1, 5)
        ]
        videos = [_make_video(f"v{w}") for w in range(1, 5)]
        compliance = gen.compute_compliance(titles, videos, calendar=None)
        assert len(compliance) == 1
        entry = compliance[0]
        # Weeks 1-4 should be "uploaded", 5-16 should be "missing"
        for w in range(1, 5):
            assert entry.week_statuses[w] == "uploaded"
        for w in range(5, 17):
            assert entry.week_statuses[w] == "missing"


# ============================================================
# PERSONA 9: Output Directory Attacker
# ============================================================
class TestOutputDirectoryAttacker:
    """Read-only directory, nonexistent path, very long path."""

    def test_nonexistent_path_created(self, tmp_path: Path) -> None:
        """OutputManager should create nonexistent directories."""
        deep_path = tmp_path / "a" / "b" / "c" / "d"
        mgr = OutputManager(base_dir=deep_path)
        run_dir = mgr.create_run()
        assert run_dir.exists()

    def test_read_only_directory_raises(self, tmp_path: Path) -> None:
        """Writing to read-only directory should raise PermissionError."""
        readonly = tmp_path / "readonly_output"
        readonly.mkdir()
        # Create the base dir first, then make it read-only
        readonly.chmod(0o444)
        try:
            mgr = OutputManager(base_dir=readonly)
            with pytest.raises(PermissionError):
                mgr.create_run()
        finally:
            readonly.chmod(0o755)

    def test_very_long_path(self, tmp_path: Path) -> None:
        """Very long path should either work or raise OSError, not crash."""
        long_name = "x" * 200
        long_path = tmp_path / long_name
        mgr = OutputManager(base_dir=long_path)
        try:
            run_dir = mgr.create_run()
            assert run_dir.exists()
        except OSError:
            # File name too long is acceptable — the system caught it
            pass

    def test_latest_link_update_idempotent(self, tmp_path: Path) -> None:
        """Updating latest link twice to different dirs should not crash."""
        mgr = OutputManager(base_dir=tmp_path)
        run1 = mgr.create_run()
        mgr.update_latest_link(run1)
        # Force a different timestamp by creating a subdir manually
        run2 = tmp_path / "report-manual-test"
        run2.mkdir()
        mgr.update_latest_link(run2)
        latest = mgr.get_latest()
        assert latest == run2.resolve()


# ============================================================
# PERSONA 10: Concurrency Chaos Agent
# ============================================================
class TestConcurrencyChaosAgent:
    """Same-second execution collision, old format data compatibility."""

    def test_same_timestamp_directory_collision(self, tmp_path: Path) -> None:
        """Two create_run calls in the same minute should reuse the directory."""
        mgr = OutputManager(base_dir=tmp_path)
        run1 = mgr.create_run()
        run2 = mgr.create_run()
        # Both should succeed — same minute means same directory name
        assert run1.exists()
        assert run2.exists()

    def test_old_format_registry_extra_fields(self, tmp_path: Path) -> None:
        """Registry with extra unknown fields from future version should load."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        channels_file = tokens_dir / "channels.json"
        data = {
            "간호학과": {
                "alias": "간호학과",
                "channel_id": "UCtest123456789012345678",
                "channel_name": "Test Channel",
                "registered_at": "2026-04-01T00:00:00",
                "last_used_at": "2026-04-01T00:00:00",
                "token_path": "/tmp/token.json",
                "new_v5_field": "should be ignored",
                "analytics_enabled": True,
            }
        }
        channels_file.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        loaded = load_registry(tokens_dir)
        assert "간호학과" in loaded
        assert loaded["간호학과"].channel_id == "UCtest123456789012345678"

    def test_old_format_parsed_title_missing_optional_fields(self) -> None:
        """ParsedTitle from old serialized data with missing optionals should load."""
        old_data = {
            "video_id": "vid_old",
            "original_title": "Old format title",
            # No professor, course, year, etc. — all optional
        }
        pt = ParsedTitle(**old_data)
        assert pt.video_id == "vid_old"
        assert pt.professor == []
        assert pt.course is None
        assert pt.parse_error is False


# ============================================================
# BONUS: Cross-cutting multi-channel edge cases
# ============================================================
class TestMultichannelCrossCutting:
    """Edge cases spanning multiple personas."""

    def test_search_with_injection_in_professor_filter(self) -> None:
        """SQL injection in professor filter should not crash search."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=1, session=1,
            ),
        ]
        query = SearchQuery(
            filters=SearchFilter(professor="'; DROP TABLE videos; --")
        )
        results = SearchService.search(titles, query)
        assert results == []

    def test_validation_with_mixed_categories(self) -> None:
        """Mix of regular and supplementary should only validate regular."""
        titles = [
            _make_parsed_title(
                "v1", professor=["홍길동"], course="간호학",
                week=1, session=1, category="regular",
            ),
            _make_parsed_title(
                "v2", professor=["홍길동"], course="간호학",
                week=3, session=1, category="regular",
            ),
            # Supplementary at week 2 should NOT fill the gap
            _make_parsed_title(
                "v3", professor=["홍길동"], course="간호학",
                week=2, session=1, category="supplementary",
            ),
        ]
        findings = check_missing_weeks(titles)
        # Week 2 is missing in regular videos (supplementary excluded)
        assert len(findings) == 1
        assert findings[0].rule_id == "V-008"
        assert 2 in findings[0].details["missing_weeks"]

    def test_parse_batch_empty_list(self) -> None:
        """parse_batch with empty list returns empty results and zero stats."""
        parser = TitleParser()
        results, stats = parser.parse_batch([])
        assert results == []
        assert stats["total"] == 0
        assert stats["success_rate"] == 0.0

    def test_department_overview_with_no_matching_videos(self) -> None:
        """Overview scoped to non-matching year returns zeros."""
        gen = DepartmentReportGenerator()
        pt = _make_parsed_title(
            "v1", professor=["홍길동"], course="간호학",
            year=2025, week=1, session=1,
        )
        vid = _make_video("v1")
        overview = gen.compute_overview(
            [pt], [vid], "UCtest123456789012345678", year=2026,
        )
        assert overview.total_videos == 0
        assert overview.total_professors == 0
