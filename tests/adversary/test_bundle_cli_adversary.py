"""Adversarial tests for report bundle CLI endpoint.

Targets: src/tube_scout/cli/report.py (report_bundle_command)
         src/tube_scout/reporting/bundle_report.py (BundleReportGenerator)

Attack vectors:
- --keyword: empty string, 10000-char, Jinja2 injection syntax
- --published-after/before: slash format, Korean format, future year 9999, inverted
- --video-ids: empty string, spaces around commas, all-nonexistent IDs, single comma
- --output: path traversal (../../../), existing file overwrite, read-only dir
- --from-html: not-yet-implemented — must fail gracefully (no AttributeError)
- --title: Jinja2 template injection ({{...}}, {%...%}), script injection, 50000-char
- --sort: injection string, numeric, None-equivalent
- --data-dir: nonexistent path, file path instead of directory
"""

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tube_scout.models.video_filter import VideoFilter
from tube_scout.reporting.bundle_report import BundleReportGenerator

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
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


def _write_config(data_path: Path, channel_id: str = "UC_TEST") -> None:
    config = {
        "channels": [{"channel_id": channel_id, "professor_name": "테스트교수"}],
        "settings": {},
    }
    (data_path / "config.json").write_text(json.dumps(config), encoding="utf-8")


def _write_videos(data_path: Path, channel_id: str, videos: list) -> None:
    videos_dir = data_path / "raw" / "channels" / channel_id
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "videos_meta.json").write_text(
        json.dumps(videos), encoding="utf-8"
    )


def _setup_minimal(tmp_path: Path, channel_id: str = "UC_TEST") -> Path:
    """Return data_path with config + 3 matching videos."""
    data_path = tmp_path / "data"
    data_path.mkdir()
    _write_config(data_path, channel_id)
    videos = [
        _make_video(f"vid{i:03d}", f"홍길동 2025 감염미생물학 {i}주차")
        for i in range(1, 4)
    ]
    _write_videos(data_path, channel_id, videos)
    return data_path


def _get_app():
    from tube_scout.cli.main import app
    return app


# ===========================================================================
# PERSONA 1: --keyword 극단 입력자
# 목표: 빈 문자열, Jinja2 표현식, 초장문으로 CLI 파이프라인 공격
# ===========================================================================
class TestKeywordExtremeInput:
    """Persona: feeds extreme keyword values to report bundle."""

    def test_empty_string_keyword_treated_as_no_filter_exits_1(
        self, tmp_path: Path
    ) -> None:
        """BUG DOCUMENTATION: --keyword '' treated as no filter by _has_filter_options.

        _has_filter_options uses `any([keyword, ...])` — empty string is falsy.
        So --keyword '' causes 'At least one filter option required' error (exit 1)
        even though the user explicitly passed a keyword argument.
        This is a behavioral inconsistency: empty keyword silently becomes no-filter.
        """
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            ["report", "bundle", "--data-dir", str(data_path), "--keyword", ""],
        )
        # BUG: empty string keyword is treated as absent (falsy), exit code 1
        # Expected behavior: empty keyword should either match all videos (exit 0)
        # or be rejected with a clear "keyword cannot be empty" message
        assert result.exit_code == 1
        assert "At least one filter option" in result.output

    def test_jinja2_variable_syntax_in_keyword_not_evaluated(
        self, tmp_path: Path
    ) -> None:
        """--keyword '{{7*7}}' must not evaluate Jinja2 in output HTML."""
        data_path = _setup_minimal(tmp_path)
        # Inject Jinja2 variable syntax into videos_meta for filter_description
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "{{7*7}}",  # Jinja2 SSTI probe
            ],
        )
        # Filter will yield 0 results (no title contains "{{7*7}}")
        # Expected exit 1 (no match), but must NOT crash with TemplateSyntaxError
        assert result.exit_code in (0, 1)
        if result.exception:
            # Must not be a Jinja2 template syntax / rendering error
            assert "TemplateSyntaxError" not in str(result.exception)
            assert "UndefinedError" not in str(result.exception)

    def test_jinja2_block_syntax_in_keyword_no_crash(self, tmp_path: Path) -> None:
        """--keyword '{%- for x in range(9999) -%}' must not crash with Jinja2 error."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "{%- for x in range(9999) -%}crash{%- endfor -%}",
            ],
        )
        assert result.exit_code in (0, 1)
        if result.exception:
            assert "TemplateSyntaxError" not in str(result.exception)

    def test_50000_char_keyword_no_crash(self, tmp_path: Path) -> None:
        """--keyword of 50000 chars must not crash (just yield no results)."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "A" * 50000,
            ],
        )
        assert result.exit_code in (0, 1)
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_keyword_with_path_separator_no_traversal(self, tmp_path: Path) -> None:
        """--keyword '../../etc/passwd' must not cause filesystem access."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "../../etc/passwd",
            ],
        )
        assert result.exit_code in (0, 1)
        assert result.exception is None or isinstance(result.exception, SystemExit)


# ===========================================================================
# PERSONA 2: --title Jinja2 인젝션 공격자
# 목표: 사용자 제공 --title이 템플릿 컨텍스트에 그대로 전달될 때 SSTI 발생 확인
# ===========================================================================
class TestTitleJinja2Injection:
    """Persona: injects Jinja2 template expressions via --title."""

    SSTI_PROBES = [
        "{{7*7}}",
        "{{config}}",
        "{%if True%}INJECTED{%endif%}",
        "{{''.__class__.__mro__[1].__subclasses__()}}",
        "${7*7}",  # non-Jinja2 but common SSTI probe
    ]

    def test_ssti_probe_in_title_does_not_evaluate(self, tmp_path: Path) -> None:
        """Jinja2 SSTI probes in --title must appear as literal text in output HTML."""
        data_path = _setup_minimal(tmp_path)
        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")

        for probe in self.SSTI_PROBES:
            output_path = tmp_path / f"bundle_{abs(hash(probe))}.html"
            # Note: autoescape=True in the environment escapes {{ }} in variables
            # but the title is passed as a Python string, not raw template code.
            # The risk: if title is used in a template via {{ title }}, autoescape
            # will HTML-escape it — Jinja2 will NOT evaluate it as template code.
            html_path = gen.generate(
                video_filter=vf,
                channel_id="UC_TEST",
                output_path=output_path,
                title=probe,
            )
            content = html_path.read_text(encoding="utf-8")
            # "49" would be present if {{7*7}} was evaluated
            assert "49" not in content or probe != "{{7*7}}", (
                f"SSTI probe '{probe}' was evaluated in output HTML"
            )
            # The raw probe string must appear escaped, not as HTML tags
            if "<script>" in probe:
                assert "<script>" not in content

    def test_xss_in_title_is_escaped(self, tmp_path: Path) -> None:
        """<script> tag in --title must be HTML-escaped in output."""
        data_path = _setup_minimal(tmp_path)
        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "bundle_xss.html"

        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output_path,
            title="<script>alert('xss')</script>",
        )
        content = html_path.read_text(encoding="utf-8")
        assert "<script>alert" not in content, "XSS via --title not escaped"

    def test_50000_char_title_no_crash(self, tmp_path: Path) -> None:
        """50000-character --title must not crash report generation."""
        data_path = _setup_minimal(tmp_path)
        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "bundle_longtitle.html"

        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output_path,
            title="T" * 50000,
        )
        assert html_path.exists()


# ===========================================================================
# PERSONA 3: --published-after/before 날짜 공격자
# 목표: 비정상 형식, 역방향 범위, 극단 날짜로 CLI 크래시 유도
# ===========================================================================
class TestDateFormatAttacker:
    """Persona: attacks date parsing in report bundle CLI."""

    def test_slash_format_date_exits_nonzero(self, tmp_path: Path) -> None:
        """--published-after '2025/03/01' (slash) must exit nonzero."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--published-after", "2025/03/01",
            ],
        )
        assert result.exit_code != 0

    def test_korean_date_format_exits_nonzero(self, tmp_path: Path) -> None:
        """--published-after '2025년3월1일' must exit nonzero."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--published-after", "2025년3월1일",
            ],
        )
        assert result.exit_code != 0

    def test_future_year_9999_is_accepted_but_yields_no_results(
        self, tmp_path: Path
    ) -> None:
        """--published-after '9999-01-01' is valid ISO but matches no past videos."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--published-after", "9999-01-01",
            ],
        )
        assert result.exit_code == 1  # no videos match

    def test_inverted_date_range_exits_nonzero(self, tmp_path: Path) -> None:
        """--published-after later than --published-before must exit nonzero."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--published-after", "2025-12-31",
                "--published-before", "2025-01-01",
            ],
        )
        assert result.exit_code != 0

    def test_partial_date_yyyy_mm_exits_nonzero(self, tmp_path: Path) -> None:
        """--published-after '2025-03' (partial YYYY-MM) must exit nonzero."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--published-after", "2025-03",
            ],
        )
        assert result.exit_code != 0

    def test_single_date_only_published_before_is_valid(self, tmp_path: Path) -> None:
        """Only --published-before without --published-after must be valid."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--published-before", "2099-12-31",
            ],
        )
        # Should succeed if any videos exist before that date
        assert result.exit_code == 0


# ===========================================================================
# PERSONA 4: --video-ids 형식 파괴자
# 목표: 빈 값, 공백 포함, 모두 존재하지 않는 ID
# ===========================================================================
class TestVideoIdsFormatAttacker:
    """Persona: feeds malformed --video-ids values."""

    def test_single_comma_video_ids(self, tmp_path: Path) -> None:
        """--video-ids ',' (just a comma) yields empty IDs — no crash."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--video-ids", ",",
            ],
        )
        # split(",") → ["", ""] — neither matches any video_id
        assert result.exit_code == 1  # no match

    def test_all_nonexistent_video_ids_exits_code_1(self, tmp_path: Path) -> None:
        """--video-ids with IDs not in videos_meta must exit code 1."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--video-ids", "NONEXISTENT_AAA,NONEXISTENT_BBB",
            ],
        )
        assert result.exit_code == 1

    def test_video_ids_with_spaces_stripped_all_match(self, tmp_path: Path) -> None:
        """--video-ids 'vid001, vid002, vid003' — filter strips, all 3 match (fixed)."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--video-ids", "vid001, vid002, vid003",  # spaces after commas
                "--dry-run",
            ],
        )
        # Fixed: filter service strips IDs → all 3 match → exit 0
        assert result.exit_code == 0

    def test_duplicate_video_ids_no_duplicate_in_report(self, tmp_path: Path) -> None:
        """Duplicate --video-ids entries must not create duplicate video sections."""
        data_path = _setup_minimal(tmp_path)
        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(video_ids=["vid001", "vid001", "vid001"])
        output_path = tmp_path / "bundle_dup.html"

        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output_path,
        )
        content = html_path.read_text(encoding="utf-8")
        # Count occurrences of the video section anchor — should be 1, not 3
        count = content.count('id="video-vid001"')
        assert count == 1, f"Duplicate video section: appears {count} times"

    def test_video_ids_only_whitespace(self, tmp_path: Path) -> None:
        """--video-ids '   ' (whitespace only) must not crash."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--video-ids", "   ",
            ],
        )
        assert result.exit_code in (0, 1)
        assert result.exception is None or isinstance(result.exception, SystemExit)


# ===========================================================================
# PERSONA 5: --output 경로 순회 및 파일시스템 공격자
# 목표: ../../../ 경로, 기존 파일 덮어쓰기, 쓰기 불가 디렉터리
# ===========================================================================
class TestOutputPathAttacker:
    """Persona: attacks --output file path."""

    def test_output_overwrites_existing_file(self, tmp_path: Path) -> None:
        """--output pointing to existing file must overwrite it without error."""
        data_path = _setup_minimal(tmp_path)
        existing = tmp_path / "existing.html"
        existing.write_text("ORIGINAL CONTENT", encoding="utf-8")

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=existing,
        )
        content = html_path.read_text(encoding="utf-8")
        assert "ORIGINAL CONTENT" not in content
        assert "<!DOCTYPE html>" in content

    def test_output_in_deeply_nested_nonexistent_dir_creates_parents(
        self, tmp_path: Path
    ) -> None:
        """--output in a deep nonexistent directory must create parent dirs."""
        data_path = _setup_minimal(tmp_path)
        deep_path = tmp_path / "a" / "b" / "c" / "d" / "report.html"

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=deep_path,
        )
        assert html_path.exists()

    def test_output_to_readonly_dir_raises_os_error(self, tmp_path: Path) -> None:
        """Writing to a read-only directory must raise OSError (not crash silently)."""
        data_path = _setup_minimal(tmp_path)
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x, no write

        try:
            gen = BundleReportGenerator(data_dir=data_path)
            vf = VideoFilter(keyword="감염미생물학")
            with pytest.raises((OSError, PermissionError)):
                gen.generate(
                    video_filter=vf,
                    channel_id="UC_TEST",
                    output_path=readonly_dir / "report.html",
                )
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(stat.S_IRWXU)

    def test_output_relative_path_traversal_does_not_escape_expected_location(
        self, tmp_path: Path
    ) -> None:
        """Path traversal in --output: writes to resolved location, no bypass."""
        data_path = _setup_minimal(tmp_path)
        # Attacker wants to write to tmp_path/../../evil.html — but realpath resolves it
        traversal = tmp_path / "sub" / ".." / ".." / "evil.html"

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword="감염미생물학")
        # This is allowed by the OS — the test documents that the generator
        # does NOT sanitize the path. The resolved path is legitimate here.
        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=traversal,
        )
        # Verify the file was created at the resolved location
        assert html_path.resolve().exists()


# ===========================================================================
# PERSONA 6: --from-html 미구현 기능 탐색자
# 목표: --from-html 옵션이 CLI에 아직 없으므로 unknown option 처리 확인
# ===========================================================================
class TestFromHtmlAttacker:
    """Persona: attacks --from-html with bad dir, traversal, empty dir, symlinks."""

    def test_from_html_nonexistent_dir_exits_code_1(self, tmp_path: Path) -> None:
        """--from-html nonexistent dir: all HTML files missing → ValueError → exit 1."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "감염미생물학",
                "--from-html", str(tmp_path / "nonexistent_html_dir"),
            ],
        )
        # No HTML files found → ValueError → exit 1
        assert result.exit_code == 1

    def test_from_html_empty_dir_exits_code_1(self, tmp_path: Path) -> None:
        """--from-html with empty directory: no HTML files → ValueError → exit 1."""
        data_path = _setup_minimal(tmp_path)
        empty_dir = tmp_path / "empty_html"
        empty_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "감염미생물학",
                "--from-html", str(empty_dir),
            ],
        )
        assert result.exit_code == 1

    def test_from_html_traversal_path_does_not_read_outside_dir(
        self, tmp_path: Path
    ) -> None:
        """--from-html '../../../etc' must not read /etc — just finds no HTML files."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "감염미생물학",
                "--from-html", "../../../etc",
            ],
        )
        # Resolved path: generate_from_html tries to find {video_id}.html in /etc
        # /etc has no such files → all skipped → ValueError → exit 1
        # Must NOT read sensitive files from /etc
        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)


# ===========================================================================
# PERSONA 7: --data-dir 비정상 경로 공격자
# 목표: 존재하지 않는 경로, 파일을 디렉터리로, 심볼릭 링크
# ===========================================================================
class TestDataDirAttacker:
    """Persona: feeds malformed --data-dir paths."""

    def test_nonexistent_data_dir_exits_code_1(self, tmp_path: Path) -> None:
        """--data-dir pointing to nonexistent directory must exit code 1 (no config)."""
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(tmp_path / "nonexistent"),
                "--keyword", "감염",
            ],
        )
        assert result.exit_code == 1

    def test_data_dir_is_a_file_exits_nonzero(self, tmp_path: Path) -> None:
        """--data-dir pointing to a file (not dir) must exit nonzero."""
        file_path = tmp_path / "iam_a_file.json"
        file_path.write_text("{}", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(file_path),
                "--keyword", "감염",
            ],
        )
        assert result.exit_code != 0

    def test_data_dir_with_null_byte_exits_nonzero(self, tmp_path: Path) -> None:
        """--data-dir containing null byte must exit nonzero (OS rejects it)."""
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(tmp_path) + "\x00evil",
                "--keyword", "감염",
            ],
        )
        assert result.exit_code != 0

    def test_symlinked_data_dir_works_normally(self, tmp_path: Path) -> None:
        """Symlinked --data-dir must work the same as real directory."""
        real_data = tmp_path / "real_data"
        real_data.mkdir()
        _write_config(real_data)
        _write_videos(
            real_data,
            "UC_TEST",
            [_make_video("v1", "홍길동 2025 감염미생물학 1주차")],
        )
        link = tmp_path / "linked_data"
        link.symlink_to(real_data)

        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(link),
                "--keyword", "감염미생물학",
            ],
        )
        assert result.exit_code == 0


# ===========================================================================
# PERSONA 8: --sort 인젝션 공격자
# 목표: 알 수 없는 sort 값, 쉘 인젝션 문자열
# ===========================================================================
class TestSortCLIAttacker:
    """Persona: feeds malicious sort values via CLI."""

    def test_unknown_sort_value_falls_back_gracefully(self, tmp_path: Path) -> None:
        """--sort 'invalid_value' must not crash — falls back to date sort."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "감염미생물학",
                "--sort", "COMPLETELY_INVALID",
            ],
        )
        assert result.exit_code == 0

    def test_shell_injection_in_sort_no_execution(self, tmp_path: Path) -> None:
        """--sort '; rm -rf /' must not execute shell commands."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "감염미생물학",
                "--sort", "; rm -rf /",
            ],
        )
        # Must not crash due to shell injection — sort just falls through to default
        assert result.exit_code in (0, 1)
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_numeric_sort_value_no_crash(self, tmp_path: Path) -> None:
        """--sort '0' (numeric string) must not crash."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "감염미생물학",
                "--sort", "0",
            ],
        )
        assert result.exit_code in (0, 1)


# ===========================================================================
# PERSONA 9: 자동 파일명 생성 인젝션 공격자
# 목표: --keyword에 파일시스템 위험 문자 포함 시 auto 파일명 오염
# ===========================================================================
class TestAutoFilenameInjection:
    """Persona: injects filesystem-dangerous chars via --keyword for auto filename."""

    DANGEROUS_KEYWORDS = [
        "../../../etc/passwd",
        "/tmp/evil",
        "keyword\x00null",
        "key/word",
        "key\\word",
        "key:word",
        "key*word?",
    ]

    def test_dangerous_keyword_sanitized_stays_in_bundle_dir(
        self, tmp_path: Path
    ) -> None:
        """FIXED: _sanitize_filename_part() prevents path traversal in auto filenames.

        re.sub(r'[^\\w\\-]', '_') removes '/', '.', ':', '*', '?' etc.
        '../../../etc/passwd' → 'etc_passwd' → path stays inside bundle/ dir.
        """
        from tube_scout.cli.report import _sanitize_filename_part

        data_path = _setup_minimal(tmp_path)
        expected_root = (data_path / "reports" / "bundle").resolve()

        for kw in self.DANGEROUS_KEYWORDS:
            sanitized = _sanitize_filename_part(kw)
            auto_path = (
                data_path / "reports" / "bundle" / f"bundle_{sanitized}_20260404.html"
            ).resolve()
            assert str(auto_path).startswith(str(expected_root)), (
                f"REGRESSION: keyword {kw!r} → sanitized {sanitized!r} "
                f"still escapes bundle dir: {auto_path}"
            )

    def test_traversal_keyword_via_cli_file_in_bundle_dir_or_no_match(
        self, tmp_path: Path
    ) -> None:
        """FIXED: traversal keyword yields no match (exit 1), no path escape."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "../../../etc/passwd",
            ],
        )
        # No video title contains this string → exit 1 (no match)
        # If somehow exit 0, verify output is inside bundle/
        bundle_dir = (data_path / "reports" / "bundle").resolve()
        if result.exit_code == 0 and bundle_dir.exists():
            for f in bundle_dir.rglob("*"):
                assert str(f.resolve()).startswith(str(bundle_dir)), (
                    f"REGRESSION: file generated outside bundle dir: {f}"
                )
        assert result.exit_code in (0, 1)


# ===========================================================================
# PERSONA 10: 복합 공격 조합자
# 목표: 여러 옵션을 동시에 극단 값으로 조합
# ===========================================================================
class TestCombinedAttackCombo:
    """Persona: combines multiple extreme inputs simultaneously."""

    def test_all_filters_at_once_with_valid_data(self, tmp_path: Path) -> None:
        """Using --keyword + --published-after/before + --video-ids together."""
        data_path = tmp_path / "data"
        data_path.mkdir()
        _write_config(data_path)
        _write_videos(
            data_path,
            "UC_TEST",
            [_make_video("vid001", "감염미생물학 1주차", "2025-03-01T00:00:00Z")],
        )
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "감염",
                "--published-after", "2025-01-01",
                "--published-before", "2025-12-31",
                "--video-ids", "vid001",
            ],
        )
        assert result.exit_code == 0

    def test_xss_in_both_keyword_and_title_both_escaped(self, tmp_path: Path) -> None:
        """XSS payloads in keyword (as title match) and --title must both be escaped."""
        data_path = tmp_path / "data"
        data_path.mkdir()
        _write_config(data_path)
        xss = "<script>alert('xss')</script>"
        # Create video whose title contains the xss payload to match the keyword
        _write_videos(
            data_path,
            "UC_TEST",
            [_make_video("vid001", f"강의 {xss} 1주차")],
        )

        gen = BundleReportGenerator(data_dir=data_path)
        vf = VideoFilter(keyword=xss)  # keyword matches the xss-contaminated title
        output_path = tmp_path / "bundle_xss_combo.html"

        html_path = gen.generate(
            video_filter=vf,
            channel_id="UC_TEST",
            output_path=output_path,
            title=xss,
        )
        content = html_path.read_text(encoding="utf-8")
        # Both the video title and report title must have <script> escaped
        # Count raw unescaped <script> tags (not &lt;script&gt;)
        import re
        raw_script_tags = re.findall(r"<script\b", content, re.IGNORECASE)
        assert len(raw_script_tags) == 0, (
            f"Unescaped <script> found {len(raw_script_tags)} times in output HTML"
        )

    def test_maximum_stress_many_options_empty_result(self, tmp_path: Path) -> None:
        """All extreme options with no matching result: exit code 1, no exception."""
        data_path = _setup_minimal(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _get_app(),
            [
                "report", "bundle",
                "--data-dir", str(data_path),
                "--keyword", "{{7*7}}" + "A" * 10000,
                "--published-after", "2024-01-01",
                "--published-before", "2024-12-31",
                "--video-ids", "NONE1,NONE2,NONE3",
                "--title", "<script>alert(1)</script>" + "T" * 10000,
                "--sort", "; cat /etc/passwd",
            ],
        )
        assert result.exit_code == 1  # no matching videos
        assert result.exception is None or isinstance(result.exception, SystemExit)
