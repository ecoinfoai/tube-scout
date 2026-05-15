"""Integration tests — ASR single-source path (T055-T058, US4).

FR-017: --source omitted → ASR auto-selected (default 'asr').
FR-018: --source youtube → exit 2 + deprecation message, ASR not invoked.
FR-019: mp4-absent video_id → ASR skip + audit reason=no_mp4_in_archive.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_PYTHON = sys.executable


# ---------------------------------------------------------------------------
# T056 — FR-018: --source youtube → exit 2 + deprecation stderr (RED first)
# ---------------------------------------------------------------------------


class TestYoutubeSourceDeprecated:
    """T056 — FR-018: --source youtube must exit 2 with deprecation message."""

    def test_source_youtube_exits_with_code_2(self, tmp_path: Path) -> None:
        """--source youtube must exit 2, not 0 or 1."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--channel", "test-channel", "--source", "youtube"],
        )
        assert result.exit_code == 2, (
            f"Expected exit code 2 for --source youtube, got {result.exit_code}. "
            f"output: {result.output!r}"
        )

    def test_source_youtube_stderr_contains_deprecation_message(
        self, tmp_path: Path
    ) -> None:
        """--source youtube output must contain '2026-05-12' deprecation text."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--channel", "test-channel", "--source", "youtube"],
        )
        assert "2026-05-12" in result.output, (
            f"Expected '2026-05-12' in deprecation message. "
            f"output: {result.output!r}"
        )

    def test_source_youtube_asr_not_invoked(self, tmp_path: Path) -> None:
        """ASR transcription must not be invoked when --source youtube is given."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        asr_called = []

        def mock_asr(**kwargs: object) -> None:
            asr_called.append(kwargs)

        runner = CliRunner()
        with patch(
            "tube_scout.cli.collect._collect_transcripts_asr",
            side_effect=mock_asr,
        ):
            result = runner.invoke(
                app,
                ["collect", "transcripts", "--channel", "test-channel", "--source", "youtube"],
            )

        assert asr_called == [], (
            f"ASR must not be invoked for --source youtube, "
            f"but got calls: {asr_called}"
        )
        assert result.exit_code == 2, (
            f"Expected exit code 2, got {result.exit_code}"
        )


# ---------------------------------------------------------------------------
# T055 — FR-017: --source omitted → resolved to 'asr' (not 'api')
# ---------------------------------------------------------------------------


class TestDefaultSourceIsAsr:
    """T055 — FR-017: default source must be 'asr', not 'api'."""

    def test_no_source_flag_resolves_to_asr(self) -> None:
        """Omitting --source must route to ASR dispatch, not API dispatch."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        api_called = []
        asr_called = []

        def mock_api(**kwargs: object) -> None:
            api_called.append(kwargs)

        def mock_asr(**kwargs: object) -> None:
            asr_called.append(kwargs)
            raise SystemExit(0)

        runner = CliRunner()
        with (
            patch("tube_scout.cli.collect.dispatch_transcript_source", side_effect=mock_api),
            patch("tube_scout.cli.collect._collect_transcripts_asr", side_effect=mock_asr),
            patch(
                "tube_scout.cli.collect.resolve_alias_to_channel_id",
                return_value="UCfake",
            ),
        ):
            runner.invoke(
                app,
                ["collect", "transcripts", "--channel", "test-channel"],
            )

        assert api_called == [], (
            f"API dispatch must NOT be called when --source is omitted. "
            f"Got calls: {api_called}"
        )
        assert len(asr_called) > 0, (
            "ASR dispatch must be called when --source is omitted (default=asr)"
        )

    def test_explicit_source_asr_routes_to_asr(self) -> None:
        """Explicit --source asr must also route to ASR dispatch."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        asr_called = []

        def mock_asr(**kwargs: object) -> None:
            asr_called.append(kwargs)
            raise SystemExit(0)

        runner = CliRunner()
        with (
            patch("tube_scout.cli.collect._collect_transcripts_asr", side_effect=mock_asr),
            patch(
                "tube_scout.cli.collect.resolve_alias_to_channel_id",
                return_value="UCfake",
            ),
        ):
            runner.invoke(
                app,
                ["collect", "transcripts", "--channel", "test-channel", "--source", "asr"],
            )

        assert len(asr_called) > 0, (
            "ASR dispatch must be called for --source asr"
        )


# ---------------------------------------------------------------------------
# T057 — FR-019: mp4-absent video → ASR skip + audit reason=no_mp4_in_archive
# ---------------------------------------------------------------------------


class TestMp4AbsentAudit:
    """T057 — FR-019: mp4-absent video_id skips ASR and records audit row."""

    def test_no_mp4_video_skipped_with_audit_row(self, tmp_path: Path) -> None:
        """video_id with no mp4 symlink must be skipped; audit must record it."""
        import csv
        from unittest.mock import patch

        from tube_scout.services.takeout_ingest import ingest_takeout

        # Build minimal takeout archive with 1 video but NO mp4
        yt = tmp_path / "archive" / "Takeout" / "YouTube 및 YouTube Music"
        channel_dir = yt / "채널"
        meta_dir = yt / "동영상 메타데이터"
        video_dir = yt / "동영상"
        for d in (channel_dir, meta_dir, video_dir):
            d.mkdir(parents=True)

        channel_id = "UCfakeAuditTest0000000001"
        (channel_dir / "채널.csv").write_text(
            f"채널 ID,채널 국가,채널 태그 1,채널 제목(원본),채널 공개 상태\n"
            f"{channel_id},KR,태그,Audit Test Channel,공개\n",
            encoding="utf-8",
        )
        (meta_dir / "동영상.csv").write_text(
            "동영상 ID,근사치 길이(밀리초),동영상 오디오 언어,동영상 카테고리,"
            "동영상 설명(원본) 언어,채널 ID,동영상 제목(원본),동영상 제목(원본) 언어,"
            "개인 정보 보호,동영상 상태,동영상 생성 타임스탬프\n"
            f"vid-no-mp4,3600000,ko,교육,ko,{channel_id},No MP4 Video,ko,"
            "일부 공개,처리됨,2026-04-01T09:00:00+00:00\n",
            encoding="utf-8",
        )
        # No mp4 files created in video_dir

        work_root = tmp_path / "work"
        db_path = work_root / "content_reuse.db"
        mock_reg = MagicMock()
        mock_reg.channel_id = channel_id

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"test-ch": mock_reg},
        ):
            result = ingest_takeout(
                takeout_dir=tmp_path / "archive",
                channel_alias="test-ch",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )

        # Ingest should record no_mp4_in_archive for vid-no-mp4
        assert result.mp4_absent_count == 1, (
            f"Expected mp4_absent_count=1, got {result.mp4_absent_count}"
        )

        audit_csv = work_root / "test-ch" / "01_collect" / "takeout_ingest_audit.csv"
        assert audit_csv.exists(), f"Audit CSV not found: {audit_csv}"
        with audit_csv.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        no_mp4_rows = [r for r in rows if r.get("reason") == "no_mp4_in_archive"]
        assert len(no_mp4_rows) == 1, (
            f"Expected 1 no_mp4_in_archive audit row, got {len(no_mp4_rows)}: {no_mp4_rows}"
        )
        assert no_mp4_rows[0]["video_id"] == "vid-no-mp4"


# ---------------------------------------------------------------------------
# T058 — Contract: exit code matrix (FR-017/018 + --channel required)
# ---------------------------------------------------------------------------


class TestCollectTranscriptsContract:
    """T058 — contracts/collect-transcripts.md exit code matrix."""

    def test_source_youtube_exit_2(self) -> None:
        """--source youtube → exit 2 (FR-018 deprecation)."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--channel", "any-alias", "--source", "youtube"],
        )
        assert result.exit_code == 2, (
            f"--source youtube must exit 2, got {result.exit_code}"
        )

    def test_missing_channel_exits_nonzero(self) -> None:
        """--channel omitted → non-zero exit (typer required argument)."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--source", "asr"],
        )
        assert result.exit_code != 0, (
            f"Missing --channel must exit non-zero, got {result.exit_code}"
        )
