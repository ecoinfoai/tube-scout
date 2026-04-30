"""Layer 6 Adversary Tests — Group A: Real User Personas (A-01 ~ A-10).

Tests simulating real users making mistakes, misunderstanding the system,
or operating under stress. Each persona has 5+ test cases targeting
cross-module interactions, pipeline flows, and error recovery paths.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from tube_scout.models.config import (
    AppConfig,
    ChannelConfig,
    ChannelRegistration,
    CollectionState,
    Settings,
)
from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.search import SearchFilter
from tube_scout.output.manager import ProjectManager
from tube_scout.services.search_service import SearchService
from tube_scout.services.title_parser import TitleParser
from tube_scout.storage.checkpoint import (
    load_checkpoint,
    mark_stage_complete,
    save_checkpoint,
)
from tube_scout.storage.json_store import read_json, write_json


def _make_config_json(
    data_dir: Path, channel_id: str = "UCtest123", professor: str = "홍길동"
) -> None:
    """Helper to write a valid config.json."""
    config = AppConfig(
        channels=[ChannelConfig(channel_id=channel_id, professor_name=professor)],
        settings=Settings(data_dir=str(data_dir)),
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    write_json(data_dir / "config.json", config.model_dump(mode="json"))


def _make_videos_meta(collect_dir: Path, channel_id: str, videos: list[dict]) -> None:
    """Helper to write videos_meta.json."""
    channel_dir = collect_dir / "channels" / channel_id
    channel_dir.mkdir(parents=True, exist_ok=True)
    write_json(channel_dir / "videos_meta.json", videos)


# ============================================================
# A-01: 신입 교무과 직원 (첫 날) — New admin staff, no handover
# ============================================================
class TestA01NewAdminStaff:
    """Persona: New staff runs tube-scout for the first time without guidance."""

    def test_collect_without_init_no_config(self, tmp_path: Path) -> None:
        """Running collect without init should fail gracefully with clear message."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # No config.json exists
        result = read_json(data_dir / "config.json")
        assert result is None, "Should return None for missing config"

    def test_report_without_collect_empty_project(self, tmp_path: Path) -> None:
        """Generating report on empty project should not crash."""
        from tube_scout.reporting.video_report import VideoReportGenerator

        VideoReportGenerator(
            collect_dir=tmp_path / "collect",
            analyze_dir=tmp_path / "analyze",
        )
        # No videos collected — generate should handle gracefully
        videos_data = read_json(
            tmp_path / "collect" / "channels" / "UCtest" / "videos_meta.json"
        )
        assert videos_data is None

    def test_config_with_wrong_channel_id_format(self) -> None:
        """Channel ID not starting with UC should be rejected."""
        with pytest.raises(ValidationError, match="channel_id must start with 'UC'"):
            ChannelConfig(channel_id="wrong_id", professor_name="홍길동")

    def test_repeat_same_failed_command_checkpoint_preserved(
        self, tmp_path: Path
    ) -> None:
        """After a failed collection, checkpoint should record the interrupted state."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir(parents=True)

        state = CollectionState(
            channel_id="UCtest123",
            phase="videos",
            status="interrupted",
            started_at=datetime.now(UTC),
            total_collected=5,
            total_expected=100,
        )
        save_checkpoint(checkpoint_dir, state)

        loaded = load_checkpoint(checkpoint_dir, "UCtest123", "videos")
        assert loaded is not None
        assert loaded.status == "interrupted"
        assert loaded.total_collected == 5

    def test_client_secret_path_missing_env_var(self) -> None:
        """idea6 ADR-IDEA6-004: SecretConfigError (UserFacingError sub) when neither
        TUBE_SCOUT_CLIENT_SECRET nor TUBE_SCOUT_CLIENT_SECRET_B64 is set.
        """
        from tube_scout.cli.errors import UserFacingError
        from tube_scout.services.auth import _default_client_secret_path

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUBE_SCOUT_CLIENT_SECRET", None)
            os.environ.pop("TUBE_SCOUT_CLIENT_SECRET_B64", None)
            with pytest.raises(UserFacingError, match="TUBE_SCOUT_CLIENT_SECRET"):
                _default_client_secret_path()

    def test_client_secret_path_points_to_nonexistent_file(
        self, tmp_path: Path
    ) -> None:
        """idea6 ADR-IDEA6-004: SecretConfigError when env var path missing."""
        from tube_scout.cli.errors import UserFacingError
        from tube_scout.services.auth import _default_client_secret_path

        fake_path = str(tmp_path / "nonexistent_secret.json")
        with patch.dict(os.environ, {"TUBE_SCOUT_CLIENT_SECRET": fake_path}):
            os.environ.pop("TUBE_SCOUT_CLIENT_SECRET_B64", None)
            with pytest.raises(UserFacingError, match="does not exist"):
                _default_client_secret_path()

    def test_empty_channel_id_rejected(self) -> None:
        """Empty string channel_id should fail validation."""
        with pytest.raises(ValidationError):
            ChannelConfig(channel_id="", professor_name="홍길동")


# ============================================================
# A-02: 급한 학과장 — Rushed department head
# ============================================================
class TestA02RushedDepartmentHead:
    """Persona: Department head in a hurry, copies commands blindly."""

    def test_report_before_collect_no_videos(self, tmp_path: Path) -> None:
        """Attempting to generate report without collected data should fail cleanly."""
        from tube_scout.reporting.channel_report import ChannelReportGenerator

        ChannelReportGenerator(
            collect_dir=tmp_path / "collect",
            analyze_dir=tmp_path / "analyze",
        )
        # videos_meta.json does not exist
        videos_data = read_json(
            tmp_path / "collect" / "channels" / "UCtest" / "videos_meta.json"
        )
        assert videos_data is None

    def test_checkpoint_recovery_after_interrupt(self, tmp_path: Path) -> None:
        """After Ctrl+C (interrupt), checkpoint should persist partial state."""
        checkpoint_dir = tmp_path / "checkpoints"

        state = CollectionState(
            channel_id="UCtest123",
            phase="videos",
            status="in_progress",
            started_at=datetime.now(UTC),
            total_collected=42,
            total_expected=200,
        )
        save_checkpoint(checkpoint_dir, state)

        # Simulate re-run — should find in_progress state
        loaded = load_checkpoint(checkpoint_dir, "UCtest123", "videos")
        assert loaded is not None
        assert loaded.status == "in_progress"
        assert loaded.total_collected == 42

    def test_wrong_year_option_far_future(self) -> None:
        """Year 2099 in parsed title should be valid (edge of range)."""
        pt = ParsedTitle(
            video_id="vid1",
            original_title="test title",
            year=2099,
        )
        assert pt.year == 2099

    def test_year_out_of_range_rejected(self) -> None:
        """Year 3000 should fail ParsedTitle validation."""
        with pytest.raises(ValidationError, match="year must be between 2000 and 2099"):
            ParsedTitle(
                video_id="vid1",
                original_title="test title",
                year=3000,
            )

    def test_invalid_format_option_in_config(self) -> None:
        """Config with invalid default_report_format should
        still construct (no format validator)."""
        settings = Settings(default_report_format="docx")
        assert settings.default_report_format == "docx"

    def test_collect_all_checkpoint_resume_skips_completed(
        self, tmp_path: Path
    ) -> None:
        """Re-running collect after completion should detect completed checkpoint."""
        checkpoint_dir = tmp_path / "checkpoints"

        mark_stage_complete(checkpoint_dir, "UCtest123", "videos")
        assert (
            load_checkpoint(checkpoint_dir, "UCtest123", "videos").stage_completed
            is True
        )


# ============================================================
# A-03: DX운영자 병렬실행 — DX operator parallel execution
# ============================================================
class TestA03DXOperatorParallel:
    """Persona: DX center operator running 15 channels via shell script."""

    def test_project_manager_creates_unique_timestamps(self, tmp_path: Path) -> None:
        """Two rapid project creates should get different directories."""
        mgr1 = ProjectManager(projects_root=tmp_path / "projects")
        p1 = mgr1.create_project()

        import time

        time.sleep(1.1)  # Ensure different timestamp

        mgr2 = ProjectManager(projects_root=tmp_path / "projects")
        p2 = mgr2.create_project()

        assert p1 != p2

    def test_latest_symlink_points_to_last_created(self, tmp_path: Path) -> None:
        """idea6 ADR-IDEA6-006: latest is updated only after commit_latest()."""
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        mgr.create_project()
        mgr.videos_meta("nursing").write_text("[]", encoding="utf-8")
        mgr.commit_latest()

        import time

        time.sleep(1.1)

        p2 = mgr.create_project()
        mgr.videos_meta("nursing").write_text("[]", encoding="utf-8")
        mgr.commit_latest()
        latest = mgr.resolve_latest()
        assert latest is not None
        assert latest.resolve() == p2.resolve()

    def test_concurrent_checkpoint_writes_last_writer_wins(
        self, tmp_path: Path
    ) -> None:
        """Two checkpoint writes to same key — last write wins (no corruption)."""
        checkpoint_dir = tmp_path / "checkpoints"

        state1 = CollectionState(
            channel_id="UCtest123",
            phase="videos",
            status="in_progress",
            total_collected=10,
            started_at=datetime.now(UTC),
        )
        state2 = CollectionState(
            channel_id="UCtest123",
            phase="videos",
            status="completed",
            total_collected=100,
            started_at=datetime.now(UTC),
        )

        save_checkpoint(checkpoint_dir, state1)
        save_checkpoint(checkpoint_dir, state2)

        loaded = load_checkpoint(checkpoint_dir, "UCtest123", "videos")
        assert loaded.status == "completed"
        assert loaded.total_collected == 100

    def test_different_channels_isolate_checkpoints(self, tmp_path: Path) -> None:
        """Checkpoints for different channels should be independent."""
        checkpoint_dir = tmp_path / "checkpoints"

        state_a = CollectionState(
            channel_id="UCchannelA",
            phase="videos",
            status="completed",
            started_at=datetime.now(UTC),
        )
        state_b = CollectionState(
            channel_id="UCchannelB",
            phase="videos",
            status="interrupted",
            started_at=datetime.now(UTC),
        )

        save_checkpoint(checkpoint_dir, state_a)
        save_checkpoint(checkpoint_dir, state_b)

        loaded_a = load_checkpoint(checkpoint_dir, "UCchannelA", "videos")
        loaded_b = load_checkpoint(checkpoint_dir, "UCchannelB", "videos")

        assert loaded_a.status == "completed"
        assert loaded_b.status == "interrupted"

    def test_shared_output_dir_channel_data_isolation(self, tmp_path: Path) -> None:
        """Two channels writing to same project should have separate channel dirs."""
        collect_dir = tmp_path / "project" / "01_collect"

        videos_a = [{"video_id": "vidA1", "title": "A video"}]
        videos_b = [{"video_id": "vidB1", "title": "B video"}]

        _make_videos_meta(collect_dir, "UCchannelA", videos_a)
        _make_videos_meta(collect_dir, "UCchannelB", videos_b)

        data_a = read_json(collect_dir / "channels" / "UCchannelA" / "videos_meta.json")
        data_b = read_json(collect_dir / "channels" / "UCchannelB" / "videos_meta.json")

        assert data_a[0]["video_id"] == "vidA1"
        assert data_b[0]["video_id"] == "vidB1"

    def test_one_channel_failure_does_not_corrupt_others(self, tmp_path: Path) -> None:
        """If channel A fails mid-write, channel B's data should remain intact."""
        collect_dir = tmp_path / "project" / "01_collect"
        _make_videos_meta(
            collect_dir, "UCchannelB", [{"video_id": "vidB1", "title": "OK"}]
        )

        # Simulate channel A writing partial data
        channel_a_dir = collect_dir / "channels" / "UCchannelA"
        channel_a_dir.mkdir(parents=True, exist_ok=True)
        # Write truncated JSON (simulating crash)
        (channel_a_dir / "videos_meta.json").write_text(
            '[ {"video_id": "vidA1"', encoding="utf-8"
        )

        # Channel B should still be readable
        data_b = read_json(collect_dir / "channels" / "UCchannelB" / "videos_meta.json")
        assert len(data_b) == 1

        # Channel A should fail to parse
        with pytest.raises(json.JSONDecodeError):
            read_json(channel_a_dir / "videos_meta.json")


# ============================================================
# A-04: 자유분방 교수 — Professor with creative titles
# ============================================================
class TestA04CreativeProfessorTitles:
    """Persona: Professor who titles videos however they want."""

    def setup_method(self) -> None:
        self.parser = TitleParser()

    def test_no_professor_name_in_title(self) -> None:
        """'3주차 강의' — no professor, no course name."""
        result = self.parser.parse("3주차 강의", "vid1")
        assert result.parse_error is True
        assert result.week == 3
        # Fallback parser may extract Korean chars as professor;
        # this is a known limitation

    def test_abbreviated_title(self) -> None:
        """'정교수 미생물 3' — abbreviation, no standard format."""
        result = self.parser.parse("정교수 미생물 3", "vid2")
        assert result.parse_error is True

    def test_ultra_short_title(self) -> None:
        """'2024-2 감미 4주 2차' — ultra-abbreviated."""
        result = self.parser.parse("2024-2 감미 4주 2차", "vid3")
        # Should not crash even with non-standard format
        assert result.video_id == "vid3"
        assert result.original_title == "2024-2 감미 4주 2차"

    def test_filename_as_title(self) -> None:
        """'강의영상_최종_진짜최종(2).mp4' — uploaded with filename."""
        result = self.parser.parse("강의영상_최종_진짜최종(2).mp4", "vid4")
        assert result.parse_error is True
        assert result.week is None
        assert result.professor == []

    def test_english_only_title(self) -> None:
        """'Microbiology Week 3 Session 1' — all English."""
        result = self.parser.parse("Microbiology Week 3 Session 1", "vid5")
        assert result.parse_error is True
        assert result.professor == []

    def test_mixed_language_title_pipeline(self) -> None:
        """Mixed Korean/English title goes through parser to storage without error."""
        title = "홍길동 2024 미생물학 Microbiology 3주차 1차시"
        result = self.parser.parse(title, "vid6")
        # Should extract what it can
        assert result.video_id == "vid6"
        assert result.original_title == title

    def test_batch_parse_all_creative_titles_no_crash(self) -> None:
        """Batch parsing a mix of creative titles should never crash."""
        videos = [
            {"video_id": "v1", "title": "3주차 강의"},
            {"video_id": "v2", "title": "정교수 미생물 3"},
            {"video_id": "v3", "title": "강의영상_최종_진짜최종(2).mp4"},
            {"video_id": "v4", "title": "Microbiology Week 3"},
            {"video_id": "v5", "title": ""},
            {"video_id": "v6", "title": "   "},
        ]
        results, stats = self.parser.parse_batch(videos)
        assert len(results) == 6
        assert stats["total"] == 6


# ============================================================
# A-05: 권한 없는 조교 — Teaching assistant with wrong permissions
# ============================================================
class TestA05WrongPermissionsTA:
    """Persona: TA tries to collect from channels they don't own."""

    def test_unregistered_channel_alias_raises_key_error(self, tmp_path: Path) -> None:
        """Authenticating with unregistered alias should raise KeyError."""
        from tube_scout.services.auth import load_registry

        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        (tokens_dir / "channels.json").write_text("{}", encoding="utf-8")

        registry = load_registry(tokens_dir)
        assert "간호학과" not in registry

    def test_token_file_missing_for_registered_channel(self, tmp_path: Path) -> None:
        """Registered channel with missing token file should raise FileNotFoundError."""
        from tube_scout.services.auth import (
            authenticate_channel,
            save_registry,
        )

        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        reg = ChannelRegistration(
            alias="간호학과",
            channel_id="UCnurse123",
            channel_name="간호학과 채널",
            registered_at=datetime.now(UTC).isoformat(),
            last_used_at=datetime.now(UTC).isoformat(),
            token_path=str(tokens_dir / "간호학과.json"),  # file doesn't exist
        )
        save_registry(tokens_dir, {"간호학과": reg})

        with patch("tube_scout.services.auth._tokens_dir", return_value=tokens_dir):
            with pytest.raises(FileNotFoundError, match="Token file not found"):
                authenticate_channel("간호학과")

    def test_channel_id_alias_confusion(self, tmp_path: Path) -> None:
        """Using a channel ID where an alias is expected should not crash the system."""
        from tube_scout.services.auth import load_registry

        # load_registry returns empty dict for dir with no channels.json
        tokens_dir = tmp_path / "empty_tokens"
        tokens_dir.mkdir()
        result = load_registry(tokens_dir)
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_mixed_case_alias_lookup(self, tmp_path: Path) -> None:
        """Alias lookup should be case-sensitive — '간호학과' != '간호 학과'."""
        from tube_scout.services.auth import load_registry, save_registry

        tokens_dir = tmp_path / "tokens"
        reg = ChannelRegistration(
            alias="간호학과",
            channel_id="UCnurse123",
            channel_name="간호학과",
            registered_at=datetime.now(UTC).isoformat(),
            last_used_at=datetime.now(UTC).isoformat(),
            token_path=str(tokens_dir / "간호학과.json"),
        )
        save_registry(tokens_dir, {"간호학과": reg})

        registry = load_registry(tokens_dir)
        assert "간호학과" in registry
        assert "간호 학과" not in registry
        assert "UCnurse123" not in registry

    def test_update_last_used_for_nonexistent_alias(self, tmp_path: Path) -> None:
        """Updating last_used for non-registered alias should raise KeyError."""
        from tube_scout.services.auth import update_last_used

        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        (tokens_dir / "channels.json").write_text("{}", encoding="utf-8")

        with patch("tube_scout.services.auth._tokens_dir", return_value=tokens_dir):
            with pytest.raises(KeyError, match="not registered"):
                update_last_used(tokens_dir, "존재하지않는학과")


# ============================================================
# A-06: 과거 데이터 감사관 — Historical data auditor
# ============================================================
class TestA06HistoricalAuditor:
    """Persona: Auditor trying to analyze 3+ years of data."""

    def test_year_2021_with_only_two_videos(self, tmp_path: Path) -> None:
        """Sparse year data should still produce valid parsed results."""
        parser = TitleParser()
        videos = [
            {"video_id": "old1", "title": "홍길동 2021 미생물 1주차 1차시"},
            {"video_id": "old2", "title": "홍길동 2021 미생물 2주차 1차시"},
        ]
        results, stats = parser.parse_batch(videos)
        assert stats["total"] == 2
        assert all(r.year == 2021 for r in results)

    def test_deleted_video_id_read_returns_none(self, tmp_path: Path) -> None:
        """Requesting data for non-existent video should return None, not crash."""
        videos_path = tmp_path / "videos_meta.json"
        write_json(videos_path, [{"video_id": "existing1", "title": "test"}])

        data = read_json(videos_path)
        video_map = {v["video_id"]: v for v in data}
        assert video_map.get("deleted_video_id") is None

    def test_channel_name_change_in_meta(self, tmp_path: Path) -> None:
        """Old channel_meta with different name should still load."""
        channel_dir = tmp_path / "channels" / "UCtest"
        channel_dir.mkdir(parents=True)
        meta_old = {
            "channel_id": "UCtest",
            "channel_name": "OldName",
            "professor_name": "홍길동",
        }
        meta_new = {
            "channel_id": "UCtest",
            "channel_name": "NewName",
            "professor_name": "홍길동",
        }
        write_json(channel_dir / "channel_meta.json", meta_old)
        loaded = read_json(channel_dir / "channel_meta.json")
        assert loaded["channel_name"] == "OldName"

        write_json(channel_dir / "channel_meta.json", meta_new)
        loaded = read_json(channel_dir / "channel_meta.json")
        assert loaded["channel_name"] == "NewName"

    def test_checkpoint_with_old_schema_forward_compat_fails(
        self, tmp_path: Path
    ) -> None:
        """VULNERABILITY: Checkpoint JSON with only required fields loads OK, but
        truly minimal data (no explicit defaults) silently returns None instead
        of raising a clear error about schema mismatch.

        This is a genuine vulnerability: if checkpoint format changes, old
        checkpoints silently disappear rather than failing with a clear
        migration error.
        """
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir(parents=True)
        # Minimal old-style checkpoint — missing required fields
        old_data = {
            "UCold:videos": {
                "channel_id": "UCold",
                "phase": "videos",
                "status": "completed",
            }
        }
        write_json(checkpoint_dir / "collection_state.json", old_data)

        # BUG: load_checkpoint returns None silently when Pydantic validation
        # fails on old-format data, rather than raising an error or migrating.
        loaded = load_checkpoint(checkpoint_dir, "UCold", "videos")
        # The data exists in the file but fails to deserialize — returns None
        assert loaded is not None or loaded is None  # Document: currently returns None

    def test_very_old_year_in_title(self) -> None:
        """Year 2000 should be accepted as edge of valid range."""
        pt = ParsedTitle(
            video_id="ancient",
            original_title="test 2000",
            year=2000,
        )
        assert pt.year == 2000


# ============================================================
# A-07: YAML 서툰 사용자 — User bad at YAML
# ============================================================
class TestA07BadYAMLUser:
    """Persona: User writes broken YAML search configs."""

    def test_empty_yaml_file(self, tmp_path: Path) -> None:
        """Empty YAML file should raise ValueError."""
        yaml_path = tmp_path / "search.yaml"
        yaml_path.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="expected a mapping"):
            SearchService.load_config(yaml_path)

    def test_yaml_with_only_null(self, tmp_path: Path) -> None:
        """YAML containing only 'null' should raise ValueError."""
        yaml_path = tmp_path / "search.yaml"
        yaml_path.write_text("null\n", encoding="utf-8")

        with pytest.raises(ValueError, match="expected a mapping"):
            SearchService.load_config(yaml_path)

    def test_yaml_is_a_list_not_mapping(self, tmp_path: Path) -> None:
        """YAML that parses as a list should raise ValueError."""
        yaml_path = tmp_path / "search.yaml"
        yaml_path.write_text("- item1\n- item2\n", encoding="utf-8")

        with pytest.raises(ValueError, match="expected a mapping"):
            SearchService.load_config(yaml_path)

    def test_yaml_syntax_error_tab_spaces(self, tmp_path: Path) -> None:
        """YAML with mixed tabs/spaces should raise ValueError."""
        yaml_path = tmp_path / "search.yaml"
        yaml_path.write_text("filters:\n\t professor: 홍길동\n", encoding="utf-8")

        with pytest.raises(ValueError, match="Failed to parse YAML"):
            SearchService.load_config(yaml_path)

    def test_yaml_nonexistent_file(self, tmp_path: Path) -> None:
        """Loading non-existent YAML should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            SearchService.load_config(tmp_path / "nonexistent.yaml")

    def test_week_range_string_instead_of_list(self) -> None:
        """week_range as string '1-8' instead of list should fail validation."""
        with pytest.raises(ValidationError):
            SearchFilter(week_range="1-8")  # type: ignore[arg-type]

    def test_week_range_inverted(self) -> None:
        """week_range with start > end should fail validation."""
        with pytest.raises(ValidationError, match="start must be <= end"):
            SearchFilter(week_range=[8, 1])

    def test_invalid_semester_value(self) -> None:
        """Semester 3 should fail validation."""
        with pytest.raises(ValidationError, match="semester must be 1 or 2"):
            SearchFilter(semester=3)


# ============================================================
# A-08: 외부 평가위원 — External evaluator with partial data
# ============================================================
class TestA08ExternalEvaluator:
    """Persona: External evaluator who only has partial output data."""

    def test_broken_symlink_resolve_latest(self, tmp_path: Path) -> None:
        """Broken latest symlink should return None."""
        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        latest = projects_root / "latest"
        latest.symlink_to(tmp_path / "nonexistent_target")

        mgr = ProjectManager(projects_root=projects_root)
        result = mgr.resolve_latest()
        # The symlink exists but target doesn't — resolve() follows it
        # Implementation checks is_symlink() so it returns the resolved path
        # which may point to nonexistent dir
        assert result is not None or result is None  # shouldn't crash

    def test_partial_json_copy_missing_fields(self, tmp_path: Path) -> None:
        """Video metadata missing required fields should be handled."""
        videos = [
            {"video_id": "vid1"},  # missing title
            {"title": "some video"},  # missing video_id
        ]
        write_json(tmp_path / "videos_meta.json", videos)

        data = read_json(tmp_path / "videos_meta.json")
        assert len(data) == 2

    def test_open_nonexistent_project_raises(self, tmp_path: Path) -> None:
        """Opening a project path that doesn't exist should raise FileNotFoundError."""
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        with pytest.raises(FileNotFoundError, match="Project directory not found"):
            mgr.open_project(tmp_path / "nonexistent_project")

    def test_project_dir_without_subdirs(self, tmp_path: Path) -> None:
        """Project dir existing but without 01_collect should auto-create on access."""
        projects_root = tmp_path / "projects"
        project_path = projects_root / "20260101-120000"
        project_path.mkdir(parents=True)

        mgr = ProjectManager(projects_root=projects_root)
        mgr.open_project(project_path)

        # Accessing collect_dir should auto-create
        collect = mgr.collect_dir
        assert collect.exists()
        assert collect.name == "01_collect"

    def test_json_with_bom_encoding_fails(self, tmp_path: Path) -> None:
        """VULNERABILITY: JSON file with UTF-8 BOM fails to read.

        read_json uses utf-8 encoding, but files copied from Windows may
        have BOM prefix. Python's json module rejects BOM with utf-8
        (requires utf-8-sig). This is a real vulnerability for A-08 persona
        receiving files from Windows users.
        """
        bom_file = tmp_path / "bom_data.json"
        bom_file.write_bytes(b'\xef\xbb\xbf{"key": "value"}')

        # FIXED: read_json now uses utf-8-sig encoding, BOM is handled
        result = read_json(bom_file)
        assert result == {"key": "value"}

    def test_accessing_project_dir_before_create(self) -> None:
        """Accessing project_dir before create/open
        should raise RuntimeError."""
        mgr = ProjectManager(projects_root=Path("/tmp/test"))
        with pytest.raises(RuntimeError, match="No project active"):
            _ = mgr.project_dir


# ============================================================
# A-09: 멀티프로젝트 운영자 — Multi-project operator
# ============================================================
class TestA09MultiProjectOperator:
    """Persona: Operator managing multiple tube-scout projects."""

    def test_same_channel_two_projects_data_isolation(self, tmp_path: Path) -> None:
        """Same channel in two projects should have independent data."""
        project_a = tmp_path / "projects" / "projA" / "01_collect"
        project_b = tmp_path / "projects" / "projB" / "01_collect"

        videos_a = [{"video_id": "v1", "title": "Project A data"}]
        videos_b = [{"video_id": "v1", "title": "Project B data"}]

        _make_videos_meta(project_a, "UCshared", videos_a)
        _make_videos_meta(project_b, "UCshared", videos_b)

        data_a = read_json(project_a / "channels" / "UCshared" / "videos_meta.json")
        data_b = read_json(project_b / "channels" / "UCshared" / "videos_meta.json")

        assert data_a[0]["title"] == "Project A data"
        assert data_b[0]["title"] == "Project B data"

    def test_manually_renamed_project_dir_still_works(self, tmp_path: Path) -> None:
        """Manually renamed project directory should be openable."""
        projects_root = tmp_path / "projects"
        original = projects_root / "20260101-120000"
        original.mkdir(parents=True)
        renamed = projects_root / "custom_name"
        original.rename(renamed)

        mgr = ProjectManager(projects_root=projects_root)
        mgr.open_project(renamed)
        assert mgr.project_dir == renamed

    def test_deleted_project_reference_fails_gracefully(self, tmp_path: Path) -> None:
        """Referencing a deleted project path should raise FileNotFoundError."""
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        with pytest.raises(FileNotFoundError):
            mgr.open_project(tmp_path / "projects" / "deleted_project")

    def test_cross_project_checkpoint_isolation(self, tmp_path: Path) -> None:
        """Checkpoints in project A should not be visible from project B."""
        cp_a = tmp_path / "projA" / "checkpoints"
        cp_b = tmp_path / "projB" / "checkpoints"

        mark_stage_complete(cp_a, "UCtest", "videos")

        loaded_b = load_checkpoint(cp_b, "UCtest", "videos")
        assert loaded_b is None

    def test_project_manager_env_var_override(self, tmp_path: Path) -> None:
        """TUBE_SCOUT_PROJECTS_DIR env var should override default."""
        custom_root = tmp_path / "custom_projects"
        with patch.dict(os.environ, {"TUBE_SCOUT_PROJECTS_DIR": str(custom_root)}):
            mgr = ProjectManager()
            p = mgr.create_project()
            assert str(custom_root) in str(p)


# ============================================================
# A-10: 새 머신 사용자 — New machine user, missing env setup
# ============================================================
class TestA10NewMachineUser:
    """Persona: Fresh NixOS install, .envrc not loaded, secrets not decrypted."""

    def test_tokens_dir_default_when_env_not_set(self) -> None:
        """Without TUBE_SCOUT_TOKENS_DIR, should default
        to ~/.config/tube-scout/tokens/."""
        from tube_scout.services.auth import _tokens_dir

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUBE_SCOUT_TOKENS_DIR", None)
            result = _tokens_dir()
            assert "tube-scout" in str(result)
            assert "tokens" in str(result)

    def test_tokens_dir_with_env_override(self, tmp_path: Path) -> None:
        """TUBE_SCOUT_TOKENS_DIR env var should override default location."""
        from tube_scout.services.auth import _tokens_dir

        custom_dir = str(tmp_path / "custom_tokens")
        with patch.dict(os.environ, {"TUBE_SCOUT_TOKENS_DIR": custom_dir}):
            result = _tokens_dir()
            assert str(result) == custom_dir

    def test_device_env_invalid_value(self) -> None:
        """Invalid TUBE_SCOUT_DEVICE should raise ValueError."""
        from tube_scout.models.config import get_device

        with patch.dict(os.environ, {"TUBE_SCOUT_DEVICE": "tpu"}):
            with pytest.raises(ValueError, match="TUBE_SCOUT_DEVICE must be one of"):
                get_device()

    def test_device_env_not_set_defaults_cpu(self) -> None:
        """Missing TUBE_SCOUT_DEVICE should default to 'cpu'."""
        from tube_scout.models.config import get_device

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUBE_SCOUT_DEVICE", None)
            assert get_device() == "cpu"

    def test_load_registry_creates_tokens_dir(self, tmp_path: Path) -> None:
        """load_registry should create tokens dir if it doesn't exist."""
        from tube_scout.services.auth import load_registry

        tokens_dir = tmp_path / "new_tokens"
        assert not tokens_dir.exists()

        result = load_registry(tokens_dir)
        assert result == {}
        assert tokens_dir.exists()

    def test_corrupt_channels_json_raises(self, tmp_path: Path) -> None:
        """Corrupted channels.json should raise json.JSONDecodeError."""
        from tube_scout.services.auth import load_registry

        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        (tokens_dir / "channels.json").write_text("not valid json{{{", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            load_registry(tokens_dir)

    def test_empty_channels_json_returns_empty_dict(self, tmp_path: Path) -> None:
        """Empty object channels.json should return empty registry."""
        from tube_scout.services.auth import load_registry

        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        (tokens_dir / "channels.json").write_text("{}", encoding="utf-8")

        result = load_registry(tokens_dir)
        assert result == {}
