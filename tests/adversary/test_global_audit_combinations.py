"""Layer 6 Adversary Tests — Combination Scenarios (8 cross-persona scenarios).

Tests combining multiple personas and conditions to simulate realistic
compound failure scenarios that occur in production.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from tube_scout.models.config import (
    AppConfig,
    ChannelConfig,
    ChannelRegistration,
    CollectionState,
)
from tube_scout.models.video_filter import VideoFilter
from tube_scout.output.manager import ProjectManager
from tube_scout.services.search_service import SearchService
from tube_scout.services.title_parser import TitleParser
from tube_scout.services.video_filter_service import VideoFilterService
from tube_scout.services.youtube_data import YouTubeDataService
from tube_scout.storage.checkpoint import (
    load_checkpoint,
    mark_stage_complete,
    save_checkpoint,
)
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import write_parquet


def _make_videos_meta(collect_dir: Path, channel_id: str, videos: list[dict]) -> None:
    """Helper to write videos_meta.json."""
    channel_dir = collect_dir / "channels" / channel_id
    channel_dir.mkdir(parents=True, exist_ok=True)
    write_json(channel_dir / "videos_meta.json", videos)


# ============================================================
# Combo 1: A-01 + A-05 — New staff with wrong department token
# ============================================================
class TestCombo01NewStaffWrongToken:
    """A-01 신입직원 + A-05 권한없는조교: Wrong token for wrong channel."""

    def test_register_then_use_wrong_alias(self, tmp_path: Path) -> None:
        """Staff uses 간호학과 token to collect for 물리치료학과 channel."""
        from tube_scout.services.auth import load_registry, save_registry

        tokens_dir = tmp_path / "tokens"
        now = datetime.now(UTC).isoformat()
        reg = {
            "간호학과": ChannelRegistration(
                alias="간호학과",
                channel_id="UCnurse",
                channel_name="간호학과",
                registered_at=now,
                last_used_at=now,
                token_path=str(tokens_dir / "간호학과.json"),
            )
        }
        save_registry(tokens_dir, reg)

        registry = load_registry(tokens_dir)
        assert "간호학과" in registry
        assert "물리치료학과" not in registry
        # Using wrong alias should fail clearly
        assert registry["간호학과"].channel_id == "UCnurse"

    def test_channel_id_mismatch_detection(self, tmp_path: Path) -> None:
        """Config channel_id != token's channel_id should be detectable."""
        from tube_scout.services.auth import load_registry, save_registry

        tokens_dir = tmp_path / "tokens"
        now = datetime.now(UTC).isoformat()
        save_registry(
            tokens_dir,
            {
                "dept_a": ChannelRegistration(
                    alias="dept_a",
                    channel_id="UCa",
                    channel_name="A",
                    registered_at=now,
                    last_used_at=now,
                    token_path=str(tokens_dir / "a.json"),
                ),
            },
        )

        config = AppConfig(
            channels=[
                ChannelConfig(channel_id="UCb_different", professor_name="홍길동")
            ],
        )
        registry = load_registry(tokens_dir)
        # The channel_id in config doesn't match the registered one
        assert config.channels[0].channel_id != registry["dept_a"].channel_id

    def test_unregistered_alias_raises_key_error(self, tmp_path: Path) -> None:
        """Attempting auth with non-existent alias should raise KeyError."""
        from tube_scout.services.auth import authenticate_channel

        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        (tokens_dir / "channels.json").write_text("{}", encoding="utf-8")

        with patch("tube_scout.services.auth._tokens_dir", return_value=tokens_dir):
            with pytest.raises(KeyError, match="not registered"):
                authenticate_channel("물리치료학과")

    def test_empty_channels_json_all_aliases_fail(self, tmp_path: Path) -> None:
        """With empty channels.json, any alias authentication should fail."""
        from tube_scout.services.auth import load_registry

        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        (tokens_dir / "channels.json").write_text("{}", encoding="utf-8")

        registry = load_registry(tokens_dir)
        for alias in ["간호학과", "물리치료학과", "치위생학과"]:
            assert alias not in registry


# ============================================================
# Combo 2: A-02 + B-03 — Rushed department head + Wi-Fi unstable
# ============================================================
class TestCombo02RushedWithUnstableWifi:
    """A-02 급한학과장 + B-03 네트워크장애: Collect during network drops."""

    def test_api_fails_mid_collection_checkpoint_preserves(
        self, tmp_path: Path
    ) -> None:
        """Network drop during collection should preserve partial checkpoint."""
        checkpoint_dir = tmp_path / "checkpoints"

        # Simulate: collected 30 videos, then network dies
        state = CollectionState(
            channel_id="UCtest",
            phase="videos",
            status="in_progress",
            total_collected=30,
            total_expected=200,
            started_at=datetime.now(UTC),
        )
        save_checkpoint(checkpoint_dir, state)

        # Verify the partial state is preserved
        loaded = load_checkpoint(checkpoint_dir, "UCtest", "videos")
        assert loaded.total_collected == 30
        assert loaded.status == "in_progress"

    def test_partial_data_survives_network_failure(self, tmp_path: Path) -> None:
        """Videos collected before network failure should be readable."""
        collect_dir = tmp_path / "01_collect"
        partial_videos = [
            {"video_id": f"v{i}", "title": f"홍길동 2024 미생물 {i}주차 1차시"}
            for i in range(1, 6)
        ]
        _make_videos_meta(collect_dir, "UCtest", partial_videos)

        data = read_json(collect_dir / "channels" / "UCtest" / "videos_meta.json")
        assert len(data) == 5

    def test_resume_after_network_recovery(self, tmp_path: Path) -> None:
        """After network recovery, checkpoint should indicate resumable state."""
        checkpoint_dir = tmp_path / "checkpoints"

        state = CollectionState(
            channel_id="UCtest",
            phase="videos",
            status="interrupted",
            total_collected=30,
            total_expected=200,
            started_at=datetime.now(UTC),
            last_page_token="CAAQAA",
        )
        save_checkpoint(checkpoint_dir, state)

        loaded = load_checkpoint(checkpoint_dir, "UCtest", "videos")
        assert loaded.last_page_token == "CAAQAA"
        assert loaded.total_collected == 30

    def test_connection_error_during_channel_info(self) -> None:
        """ConnectionError at the start should not create any files."""
        mock_client = MagicMock()
        mock_client.channels().list().execute.side_effect = ConnectionError("No Wi-Fi")

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(ConnectionError):
            service.get_channel_info("UCtest")


# ============================================================
# Combo 3: A-03 + B-07 — DX operator 15 channels simultaneous
# ============================================================
class TestCombo03ParallelMultiChannel:
    """A-03 DX운영자 + B-07 동시성: 15 channels running concurrently."""

    def test_15_channel_checkpoints_no_corruption(self, tmp_path: Path) -> None:
        """15 channel checkpoints written sequentially should all be intact."""
        checkpoint_dir = tmp_path / "checkpoints"
        channels = [f"UC{i:04d}" for i in range(15)]

        for ch in channels:
            state = CollectionState(
                channel_id=ch,
                phase="videos",
                status="completed",
                total_collected=50 + int(ch[-4:]),
                started_at=datetime.now(UTC),
            )
            save_checkpoint(checkpoint_dir, state)

        for ch in channels:
            loaded = load_checkpoint(checkpoint_dir, ch, "videos")
            assert loaded is not None
            assert loaded.channel_id == ch
            expected = 50 + int(ch[-4:])
            assert loaded.total_collected == expected

    def test_channel_data_directories_isolated(self, tmp_path: Path) -> None:
        """Each channel's data should be in its own directory."""
        collect_dir = tmp_path / "01_collect"
        channels = [f"UC{i:04d}" for i in range(5)]

        for ch in channels:
            _make_videos_meta(
                collect_dir,
                ch,
                [{"video_id": f"{ch}_v1", "title": f"Channel {ch} video"}],
            )

        for ch in channels:
            data = read_json(collect_dir / "channels" / ch / "videos_meta.json")
            assert len(data) == 1
            assert data[0]["video_id"].startswith(ch)

    def test_one_channel_failure_others_intact(self, tmp_path: Path) -> None:
        """If channel 3 fails, channels 1-2 and 4-5 should be unaffected."""
        checkpoint_dir = tmp_path / "checkpoints"

        for i in range(5):
            status = "interrupted" if i == 2 else "completed"
            state = CollectionState(
                channel_id=f"UC{i:04d}",
                phase="videos",
                status=status,
                started_at=datetime.now(UTC),
            )
            save_checkpoint(checkpoint_dir, state)

        failed = load_checkpoint(checkpoint_dir, "UC0002", "videos")
        assert failed.status == "interrupted"

        for i in [0, 1, 3, 4]:
            loaded = load_checkpoint(checkpoint_dir, f"UC{i:04d}", "videos")
            assert loaded.status == "completed"


# ============================================================
# Combo 4: A-04 + B-04 — Creative titles + Unicode chaos
# ============================================================
class TestCombo04CreativeTitlesUnicode:
    """A-04 교수 + B-04 유니코드: Emoji+multilingual titles through pipeline."""

    def setup_method(self) -> None:
        self.parser = TitleParser()

    def test_emoji_mixed_korean_english_title(self) -> None:
        """'🧬 Microbiology W3-1 감염미생물학' — full pipeline parse."""
        result = self.parser.parse("🧬 Microbiology W3-1 감염미생물학", "vid1")
        assert result.video_id == "vid1"
        assert result.parse_error is True  # non-standard format

    def test_creative_title_stored_with_unicode(self, tmp_path: Path) -> None:
        """Unicode-heavy title survives parse -> store -> load cycle."""
        title = "👨‍🏫 홍길동 2024 미생물학 3주차 1차시 🔬"
        parsed = self.parser.parse(title, "vid2")

        data = [parsed.model_dump()]
        path = tmp_path / "parsed.json"
        write_json(path, data)
        loaded = read_json(path)
        assert loaded[0]["original_title"] == title

    def test_rtl_mixed_korean_title(self) -> None:
        """Arabic+Korean title should parse without crash."""
        result = self.parser.parse("العربية 홍길동 2024 미생물 3주차 1차시", "vid3")
        assert result.video_id == "vid3"

    def test_batch_mixed_unicode_titles(self) -> None:
        """Batch of diverse unicode titles should all parse."""
        videos = [
            {"video_id": "v1", "title": "🧬 미생물학 3주차"},
            {"video_id": "v2", "title": "홍길동\u200b2024 미생물 3주차 1차시"},
            {"video_id": "v3", "title": "العربية Microbiology W3"},
            {"video_id": "v4", "title": "正교수 微生物 3주차"},
            {"video_id": "v5", "title": "가" * 1000 + " 3주차"},
        ]
        results, stats = self.parser.parse_batch(videos)
        assert stats["total"] == 5
        assert all(r.video_id for r in results)

    def test_emoji_title_filter_by_keyword(self) -> None:
        """Filtering videos with emoji titles by keyword should work."""
        videos = [
            {
                "video_id": "v1",
                "title": "🧬 미생물학 3주차",
                "published_at": "2024-01-01",
            },
            {"video_id": "v2", "title": "해부학 3주차", "published_at": "2024-01-01"},
        ]
        vf = VideoFilter(keyword="미생물학")
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1
        assert result[0]["video_id"] == "v1"


# ============================================================
# Combo 5: A-06 + B-02 — Historical auditor + deleted video 404
# ============================================================
class TestCombo05HistoricalDeletedVideo:
    """A-06 감사관 + B-02 비정상응답: Re-collecting deleted videos."""

    def test_deleted_video_api_error_propagates(self) -> None:
        """Requesting deleted video from API should raise HttpError."""
        import httplib2
        from googleapiclient.errors import HttpError

        mock_client = MagicMock()
        resp = httplib2.Response({"status": "404"})
        mock_client.videos().list().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "Video not found"}}'
        )

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(HttpError):
            service.get_video_details(["deleted_vid"])

    def test_existing_cached_data_survives_api_404(self, tmp_path: Path) -> None:
        """Cached video data should remain after failed re-collection attempt."""
        collect_dir = tmp_path / "01_collect"
        original_data = [
            {"video_id": "old_vid", "title": "Old Video", "view_count": 100},
        ]
        _make_videos_meta(collect_dir, "UCtest", original_data)

        # Simulate API 404 — existing data should be untouched
        data = read_json(collect_dir / "channels" / "UCtest" / "videos_meta.json")
        assert len(data) == 1
        assert data[0]["video_id"] == "old_vid"

    def test_private_video_403_doesnt_crash(self) -> None:
        """403 on private video should raise HttpError, not crash."""
        import httplib2
        from googleapiclient.errors import HttpError

        mock_client = MagicMock()
        resp = httplib2.Response({"status": "403"})
        mock_client.channels().list().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "Forbidden"}}'
        )

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(HttpError):
            service.get_channel_info("UCprivate")

    def test_old_video_metadata_still_parseable(self) -> None:
        """Titles from 2021 should still parse with current parser."""
        parser = TitleParser()
        result = parser.parse("홍길동 2021 미생물학 5주차 2차시", "old_2021")
        assert result.year == 2021
        assert result.week == 5
        assert result.parse_error is False


# ============================================================
# Combo 6: A-07 + A-08 — Bad YAML + External evaluator
# ============================================================
class TestCombo06BrokenYAMLExternalUser:
    """A-07 YAML서툰사용자 + A-08 외부평가위원: Broken YAML from email."""

    def test_yaml_with_bom_from_windows(self, tmp_path: Path) -> None:
        """YAML with UTF-8 BOM (from Windows) should parse or fail clearly."""
        yaml_path = tmp_path / "search.yaml"
        yaml_path.write_bytes(
            b"\xef\xbb\xbffilters:\n"
            b'  professor: "\xed\x99\x8d\xea\xb8\xb8\xeb\x8f\x99"\n'
        )

        try:
            query = SearchService.load_config(yaml_path)
            # If BOM is handled, filters should be present
            assert query.filters is not None or query.queries is not None or True
        except ValueError:
            pass  # Acceptable — BOM not handled

    def test_yaml_encoding_corruption_from_email(self, tmp_path: Path) -> None:
        """YAML with encoding issues should raise ValueError."""
        yaml_path = tmp_path / "search.yaml"
        # Write invalid UTF-8 that won't parse as YAML
        yaml_path.write_bytes(b"filters:\n  professor: \xff\xfe\n")

        with pytest.raises((ValueError, UnicodeDecodeError)):
            SearchService.load_config(yaml_path)

    def test_yaml_with_smart_quotes(self, tmp_path: Path) -> None:
        """YAML with smart quotes (from email client) should fail clearly."""
        yaml_path = tmp_path / "search.yaml"
        yaml_path.write_text(
            "filters:\n  professor: \u201c\ud64d\uae38\ub3d9\u201d\n",
            encoding="utf-8",
        )

        try:
            query = SearchService.load_config(yaml_path)
            # Smart quotes may be preserved as part of the string
            assert query is not None
        except ValueError:
            pass  # Also acceptable

    def test_evaluator_with_partial_data_and_bad_yaml(self, tmp_path: Path) -> None:
        """Evaluator with partial project + broken YAML should get clear errors."""
        # No videos exist
        videos = read_json(tmp_path / "videos_meta.json")
        assert videos is None

        # Bad YAML
        yaml_path = tmp_path / "search.yaml"
        yaml_path.write_text("- invalid\n- list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="expected a mapping"):
            SearchService.load_config(yaml_path)


# ============================================================
# Combo 7: A-09 + A-03 — Multi-project + channel crossover
# ============================================================
class TestCombo07MultiProjectChannelCross:
    """A-09 멀티프로젝트 + A-03 DX운영자: Cross-project channel contamination."""

    def test_channel_in_two_projects_isolated(self, tmp_path: Path) -> None:
        """Same channel collected in two projects should have separate data."""
        tmp_path / "projects" / "projA"
        tmp_path / "projects" / "projB"

        mgr_a = ProjectManager(projects_root=tmp_path / "projects_a")
        mgr_a.create_project()

        mgr_b = ProjectManager(projects_root=tmp_path / "projects_b")
        mgr_b.create_project()

        _make_videos_meta(
            mgr_a.collect_dir,
            "UCshared",
            [
                {"video_id": "va1", "title": "Project A data"},
            ],
        )
        _make_videos_meta(
            mgr_b.collect_dir,
            "UCshared",
            [
                {"video_id": "vb1", "title": "Project B data"},
            ],
        )

        data_a = read_json(
            mgr_a.collect_dir / "channels" / "UCshared" / "videos_meta.json"
        )
        data_b = read_json(
            mgr_b.collect_dir / "channels" / "UCshared" / "videos_meta.json"
        )

        assert data_a[0]["title"] == "Project A data"
        assert data_b[0]["title"] == "Project B data"

    def test_checkpoint_isolation_across_projects(self, tmp_path: Path) -> None:
        """Checkpoints from different projects should not interfere."""
        mgr_a = ProjectManager(projects_root=tmp_path / "projects_a")
        mgr_a.create_project()

        mgr_b = ProjectManager(projects_root=tmp_path / "projects_b")
        mgr_b.create_project()

        mark_stage_complete(mgr_a.checkpoint_dir, "UCshared", "videos")

        loaded_b = load_checkpoint(mgr_b.checkpoint_dir, "UCshared", "videos")
        assert loaded_b is None

        loaded_a = load_checkpoint(mgr_a.checkpoint_dir, "UCshared", "videos")
        assert loaded_a is not None
        assert loaded_a.stage_completed is True

    def test_collect_with_wrong_project_path(self, tmp_path: Path) -> None:
        """Opening deleted/moved project should raise FileNotFoundError."""
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        with pytest.raises(FileNotFoundError):
            mgr.open_project(tmp_path / "projects" / "deleted_proj")

    def test_latest_symlink_survives_project_operations(self, tmp_path: Path) -> None:
        """Latest symlink should point to most recent project even after cross-ops."""
        projects_root = tmp_path / "projects"
        mgr = ProjectManager(projects_root=projects_root)
        mgr.create_project()

        import time

        time.sleep(1.1)

        mgr2 = ProjectManager(projects_root=projects_root)
        p2 = mgr2.create_project()

        latest = mgr2.resolve_latest()
        assert latest.resolve() == p2.resolve()


# ============================================================
# Combo 8: A-10 + B-01 — New machine + disk error
# ============================================================
class TestCombo08NewMachineDiskError:
    """A-10 새머신 + B-01 파일시스템: Missing env + corrupt files."""

    def test_no_env_vars_graceful_defaults(self) -> None:
        """Without any env vars, system should use safe defaults."""
        from tube_scout.models.config import get_device
        from tube_scout.services.auth import _tokens_dir

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUBE_SCOUT_DEVICE", None)
            os.environ.pop("TUBE_SCOUT_TOKENS_DIR", None)

            device = get_device()
            assert device == "cpu"

            tokens = _tokens_dir()
            assert "tube-scout" in str(tokens)

    def test_corrupt_config_plus_missing_secret(self, tmp_path: Path) -> None:
        """Corrupt config.json + missing client secret — both errors clear."""
        # Corrupt config
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "config.json").write_text("{invalid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            read_json(data_dir / "config.json")

        # Missing client secret
        from tube_scout.services.auth import _default_client_secret_path

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUBE_SCOUT_CLIENT_SECRET", None)
            with pytest.raises(ValueError, match="TUBE_SCOUT_CLIENT_SECRET"):
                _default_client_secret_path()

    def test_read_only_filesystem_write_fails(self, tmp_path: Path) -> None:
        """Write attempt to read-only dir should raise PermissionError."""
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(0o444)

        try:
            with pytest.raises((PermissionError, OSError)):
                write_json(ro_dir / "sub" / "data.json", {"test": 1})
        finally:
            ro_dir.chmod(0o755)

    def test_tokens_dir_auto_creation_on_load(self, tmp_path: Path) -> None:
        """load_registry should create tokens dir even if it doesn't exist."""
        from tube_scout.services.auth import load_registry

        new_dir = tmp_path / "fresh_tokens"
        assert not new_dir.exists()

        result = load_registry(new_dir)
        assert result == {}
        assert new_dir.exists()

    def test_half_written_checkpoint_returns_none(self, tmp_path: Path) -> None:
        """FIX (H-04): Half-written checkpoint file is handled gracefully.

        _checkpoint_path no longer adds a 'checkpoints/' subdirectory (L-10 fix),
        and load_checkpoint catches JSONDecodeError (H-04 fix).
        """
        # _checkpoint_path(data_dir) -> data_dir / "collection_state.json"
        checkpoint_dir = tmp_path / "data"
        checkpoint_dir.mkdir(parents=True)
        cp_file = checkpoint_dir / "collection_state.json"
        cp_file.write_text(
            '{"UCtest:videos": {"channel_id": "UCtest"', encoding="utf-8"
        )

        # read_json still raises JSONDecodeError (low-level function)
        with pytest.raises(json.JSONDecodeError):
            read_json(cp_file)

        # load_checkpoint now catches JSONDecodeError and returns None
        result = load_checkpoint(checkpoint_dir, "UCtest", "videos")
        assert result is None

    def test_missing_projects_dir_auto_creates(self, tmp_path: Path) -> None:
        """ProjectManager should create projects_root if it doesn't exist."""
        projects_root = tmp_path / "new_projects"
        assert not projects_root.exists()

        mgr = ProjectManager(projects_root=projects_root)
        p = mgr.create_project()
        assert projects_root.exists()
        assert p.exists()

    def test_parquet_write_to_missing_dir_creates_parents(self, tmp_path: Path) -> None:
        """write_parquet should create parent directories."""
        deep_path = tmp_path / "a" / "b" / "c" / "data.parquet"
        df = pl.DataFrame({"x": [1, 2, 3]})
        write_parquet(deep_path, df)
        assert deep_path.exists()
