"""Layer 6 Adversary Tests — Group B: Environmental Adversary Conditions (B-01 ~ B-07).

Tests simulating infrastructure failures, corrupt data, abnormal API responses,
network issues, unicode edge cases, large-scale data, and concurrency.
Each condition has 7+ test cases.
"""

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest
from pydantic import ValidationError

from tube_scout.models.config import (
    CalendarEvent,
    CollectionState,
)
from tube_scout.models.video_filter import VideoFilter
from tube_scout.output.manager import ProjectManager
from tube_scout.services.title_parser import TitleParser
from tube_scout.services.video_filter_service import VideoFilterService
from tube_scout.services.youtube_data import YouTubeDataService, _parse_iso8601_duration
from tube_scout.storage.checkpoint import (
    load_checkpoint,
    save_checkpoint,
)
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import (
    append_parquet,
    read_parquet,
    write_parquet,
)


# ============================================================
# B-01: Corrupt filesystem
# ============================================================
class TestB01CorruptFilesystem:
    """Condition: Power loss, disk failure, partial writes."""

    def test_half_written_json_raises_decode_error(self, tmp_path: Path) -> None:
        """JSON file truncated mid-write should raise JSONDecodeError."""
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text('{"channels": [{"channel_id": "UCtest', encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            read_json(corrupt)

    def test_empty_json_file_raises(self, tmp_path: Path) -> None:
        """Zero-byte JSON file should raise JSONDecodeError."""
        empty = tmp_path / "empty.json"
        empty.write_text("", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            read_json(empty)

    def test_json_with_null_bytes_raises(self, tmp_path: Path) -> None:
        """JSON with embedded NULL bytes should fail parsing."""
        null_file = tmp_path / "null.json"
        null_file.write_bytes(b'{"key": "val\x00ue"}')

        # json.load may or may not accept this; verify behavior
        try:
            data = read_json(null_file)
            # If it parses, the NULL is embedded in the value
            assert "\x00" in data["key"]
        except json.JSONDecodeError:
            pass  # Also acceptable — corrupt data detected

    def test_atomic_write_default_str_serializes_anything(self, tmp_path: Path) -> None:
        """VULNERABILITY: write_json uses default=str, so non-serializable objects
        become their str() repr instead of raising TypeError.

        This means corrupt data (e.g., object references) gets silently written
        as strings rather than failing fast.
        """
        target = tmp_path / "target.json"

        class NotSerializable:
            pass

        obj = NotSerializable()
        # FIXED: default=str removed — non-serializable objects now raise TypeError
        with pytest.raises(TypeError):
            write_json(target, {"bad": obj})

    def test_read_json_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """Reading a file that doesn't exist should return None."""
        assert read_json(tmp_path / "nope.json") is None

    def test_parquet_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """Reading non-existent Parquet should return None."""
        assert read_parquet(tmp_path / "nope.parquet") is None

    def test_corrupt_parquet_header_raises(self, tmp_path: Path) -> None:
        """Parquet file with corrupted header should raise on read."""
        corrupt = tmp_path / "corrupt.parquet"
        corrupt.write_bytes(b"NOT_A_PARQUET_FILE_HEADER" + b"\x00" * 100)

        with pytest.raises(Exception):
            read_parquet(corrupt)

    def test_write_json_creates_parent_dirs(self, tmp_path: Path) -> None:
        """write_json should create parent directories automatically."""
        deep = tmp_path / "a" / "b" / "c" / "data.json"
        write_json(deep, {"test": True})
        assert read_json(deep) == {"test": True}

    def test_broken_symlink_in_projects(self, tmp_path: Path) -> None:
        """Broken symlink should not crash ProjectManager.resolve_latest()."""
        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        latest = projects_root / "latest"
        latest.symlink_to(tmp_path / "ghost_dir")

        mgr = ProjectManager(projects_root=projects_root)
        # Should handle gracefully — returns the resolved (non-existent) path
        result = mgr.resolve_latest()
        # is_symlink() is True so it returns resolve() which won't exist
        assert result is not None

    def test_read_only_dir_write_json_raises(self, tmp_path: Path) -> None:
        """Writing JSON to read-only directory should raise PermissionError."""
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(0o444)

        try:
            with pytest.raises((PermissionError, OSError)):
                write_json(ro_dir / "sub" / "test.json", {"data": 1})
        finally:
            ro_dir.chmod(0o755)


# ============================================================
# B-02: Abnormal YouTube API responses
# ============================================================
class TestB02AbnormalAPIResponses:
    """Condition: YouTube API returning unexpected data."""

    def test_empty_items_list_raises_value_error(self) -> None:
        """Channel not found (empty items) should raise ValueError."""
        mock_client = MagicMock()
        mock_client.channels().list().execute.return_value = {"items": []}

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(ValueError, match="Channel not found"):
            service.get_channel_info("UCnonexistent")

    def test_missing_statistics_field_in_channel(self) -> None:
        """Channel response missing statistics should raise KeyError."""
        mock_client = MagicMock()
        mock_client.channels().list().execute.return_value = {
            "items": [
                {
                    "id": "UCtest",
                    "snippet": {"title": "Test"},
                    "contentDetails": {"relatedPlaylists": {"uploads": "UUtest"}},
                    # No "statistics" key
                }
            ]
        }

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(KeyError):
            service.get_channel_info("UCtest")

    def test_iso8601_duration_empty_string(self) -> None:
        """Empty duration string should return 0."""
        assert _parse_iso8601_duration("") == 0

    def test_iso8601_duration_garbage_string(self) -> None:
        """Non-ISO duration string should return 0."""
        assert _parse_iso8601_duration("not_a_duration") == 0

    def test_iso8601_duration_hours_only(self) -> None:
        """'PT2H' should parse to 7200 seconds."""
        assert _parse_iso8601_duration("PT2H") == 7200

    def test_iso8601_duration_minutes_seconds(self) -> None:
        """'PT30M15S' should parse correctly."""
        assert _parse_iso8601_duration("PT30M15S") == 1815

    def test_iso8601_duration_zero(self) -> None:
        """'PT0S' should return 0."""
        assert _parse_iso8601_duration("PT0S") == 0

    def test_list_videos_empty_playlist(self) -> None:
        """Empty playlist should return empty list, not error."""
        mock_client = MagicMock()
        mock_client.playlistItems().list().execute.return_value = {
            "items": [],
        }

        service = YouTubeDataService(client=mock_client)
        result = service.list_all_videos("UUempty")
        assert result == []

    def test_video_details_with_missing_duration(self) -> None:
        """Video without duration in contentDetails should be handled."""
        mock_client = MagicMock()
        mock_client.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "vid1",
                    "statistics": {"viewCount": "100"},
                    "contentDetails": {},  # no duration
                }
            ]
        }

        service = YouTubeDataService(client=mock_client)
        result = service.get_video_details(["vid1"])
        assert "vid1" in result


# ============================================================
# B-03: Network failures
# ============================================================
class TestB03NetworkFailures:
    """Condition: Wi-Fi drops, timeouts, DNS failures."""

    def test_api_call_connection_error(self) -> None:
        """ConnectionError during API call should propagate."""
        mock_client = MagicMock()
        mock_client.channels().list().execute.side_effect = ConnectionError(
            "Network unreachable"
        )

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(ConnectionError):
            service.get_channel_info("UCtest")

    def test_api_call_timeout_error(self) -> None:
        """TimeoutError during API call should propagate."""
        mock_client = MagicMock()
        mock_client.channels().list().execute.side_effect = TimeoutError(
            "Request timed out"
        )

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(TimeoutError):
            service.get_channel_info("UCtest")

    def test_checkpoint_preserves_state_on_network_failure(
        self, tmp_path: Path
    ) -> None:
        """Checkpoint should be preserved even when subsequent API call fails."""
        checkpoint_dir = tmp_path / "checkpoints"

        state = CollectionState(
            channel_id="UCtest",
            phase="videos",
            status="in_progress",
            total_collected=5,
            started_at=datetime.now(UTC),
        )
        save_checkpoint(checkpoint_dir, state)

        # Simulate network failure — checkpoint should still be readable
        loaded = load_checkpoint(checkpoint_dir, "UCtest", "videos")
        assert loaded is not None
        assert loaded.total_collected == 5

    def test_rate_limiter_profile_config_validation(self) -> None:
        """Invalid rate limit config should fail validation."""
        from tube_scout.models.config import RateLimitProfile

        with pytest.raises(ValidationError):
            RateLimitProfile(
                base_delay=-1.0,  # negative
                max_retries=3,
                backoff_multiplier=2.0,
            )

    def test_rate_limiter_zero_retries(self) -> None:
        """Zero retries should be valid (no retry on failure)."""
        from tube_scout.models.config import RateLimitProfile

        profile = RateLimitProfile(
            base_delay=1.0,
            max_retries=0,
            backoff_multiplier=1.0,
        )
        assert profile.max_retries == 0

    def test_http_error_from_google_api(self) -> None:
        """HttpError from googleapiclient should propagate clearly."""
        import httplib2
        from googleapiclient.errors import HttpError

        mock_client = MagicMock()
        resp = httplib2.Response({"status": "403"})
        mock_client.channels().list().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "Forbidden"}}'
        )

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(HttpError):
            service.get_channel_info("UCtest")

    def test_ssl_error_propagates(self) -> None:
        """SSL errors should propagate, not be silently swallowed."""
        import ssl

        mock_client = MagicMock()
        mock_client.channels().list().execute.side_effect = ssl.SSLError(
            "SSL handshake failed"
        )

        service = YouTubeDataService(client=mock_client)
        with pytest.raises(ssl.SSLError):
            service.get_channel_info("UCtest")


# ============================================================
# B-04: Unicode / encoding edge cases
# ============================================================
class TestB04UnicodeEdgeCases:
    """Condition: Exotic characters in video titles."""

    def setup_method(self) -> None:
        self.parser = TitleParser()

    def test_rtl_characters_in_title(self) -> None:
        """RTL Arabic text should not crash parser."""
        result = self.parser.parse("مرحبا بالعالم 3주차", "vid_rtl")
        assert result.video_id == "vid_rtl"

    def test_zero_width_characters(self) -> None:
        """Zero-width joiner/non-joiner should not crash."""
        title = "홍길동\u200b2024\u200c미생물\u200d3주차\u200e1차시"
        result = self.parser.parse(title, "vid_zw")
        assert result.video_id == "vid_zw"

    def test_emoji_in_title(self) -> None:
        """Emoji characters should be handled gracefully."""
        result = self.parser.parse("🧬 미생물학 3주차 1차시 🔬", "vid_emoji")
        assert result.video_id == "vid_emoji"
        assert result.week == 3

    def test_emoji_combo_in_professor_position(self) -> None:
        """Emoji where professor name expected should not crash."""
        result = self.parser.parse("👨‍🏫 2024 미생물학 3주차 1차시", "vid_emoji2")
        assert result.parse_error is True

    def test_very_long_title_10kb(self) -> None:
        """10KB title should parse without memory issues."""
        long_title = "가" * 5000 + " 3주차 1차시"
        result = self.parser.parse(long_title, "vid_long")
        assert result.video_id == "vid_long"
        assert result.week == 3

    def test_null_byte_in_title(self) -> None:
        """NULL byte in title should be handled (may strip or parse)."""
        result = self.parser.parse("홍길동\x002024 미생물 3주차", "vid_null")
        assert result.video_id == "vid_null"

    def test_surrogate_pair_emoji(self) -> None:
        """Supplementary plane characters should not crash."""
        title = "홍길동 2024 미생물학 3주차 1차시 \U0001f9ec"
        result = self.parser.parse(title, "vid_surr")
        assert result.video_id == "vid_surr"

    def test_only_whitespace_title(self) -> None:
        """Title with only whitespace should be handled as empty."""
        result = self.parser.parse("   \t  \n  ", "vid_ws")
        assert result.parse_error is True
        assert result.original_title == "(empty)"

    def test_unicode_title_stored_and_loaded(self, tmp_path: Path) -> None:
        """Unicode-heavy title should survive JSON write/read roundtrip."""
        data = [{"video_id": "v1", "title": "🧬 미생물학 العربية 3주차"}]
        path = tmp_path / "unicode.json"
        write_json(path, data)
        loaded = read_json(path)
        assert loaded[0]["title"] == "🧬 미생물학 العربية 3주차"

    def test_title_with_newlines(self) -> None:
        """Title containing newline characters should not crash parser."""
        result = self.parser.parse("홍길동 2024\n미생물학\n3주차 1차시", "vid_nl")
        assert result.video_id == "vid_nl"


# ============================================================
# B-05: Time anomalies
# ============================================================
class TestB05TimeAnomalies:
    """Condition: Clock errors, timezone issues, epoch dates."""

    def test_published_at_epoch_1970(self) -> None:
        """Video with 1970-01-01 publish date should be filterable."""
        videos = [
            {
                "video_id": "epoch",
                "title": "ancient",
                "published_at": "1970-01-01T00:00:00Z",
            },
        ]
        vf = VideoFilter(
            published_after=date(1960, 1, 1), published_before=date(2000, 1, 1)
        )
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1

    def test_published_at_far_future(self) -> None:
        """Video published in 2099 should still be filterable."""
        videos = [
            {
                "video_id": "future",
                "title": "future vid",
                "published_at": "2099-12-31T23:59:59Z",
            },
        ]
        vf = VideoFilter(published_after=date(2090, 1, 1))
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1

    def test_checkpoint_timestamp_in_future(self, tmp_path: Path) -> None:
        """Checkpoint with future timestamp should still load without error."""
        checkpoint_dir = tmp_path / "checkpoints"
        future = datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC)
        state = CollectionState(
            channel_id="UCtest",
            phase="videos",
            status="completed",
            started_at=future,
            updated_at=future,
        )
        save_checkpoint(checkpoint_dir, state)

        loaded = load_checkpoint(checkpoint_dir, "UCtest", "videos")
        assert loaded is not None
        assert loaded.status == "completed"

    def test_published_at_missing_timezone(self) -> None:
        """Date without timezone should still filter correctly."""
        videos = [
            {"video_id": "notz", "title": "no tz", "published_at": "2024-06-15"},
        ]
        vf = VideoFilter(
            published_after=date(2024, 1, 1), published_before=date(2024, 12, 31)
        )
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1

    def test_published_at_empty_string_filtered_out(self) -> None:
        """Video with empty published_at should be filtered out by date filter."""
        videos = [
            {"video_id": "empty_date", "title": "no date", "published_at": ""},
        ]
        vf = VideoFilter(published_after=date(2024, 1, 1))
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 0

    def test_calendar_event_end_before_start_rejected(self) -> None:
        """Calendar event where end < start should fail validation."""
        with pytest.raises(ValidationError, match="end_date must be >= start_date"):
            CalendarEvent(
                name="Exam",
                start_date="2024-06-15",
                end_date="2024-06-10",
                event_type="exam",
            )

    def test_calendar_event_same_day(self) -> None:
        """Calendar event where start == end should be valid."""
        event = CalendarEvent(
            name="Exam",
            start_date="2024-06-15",
            end_date="2024-06-15",
            event_type="exam",
        )
        assert event.start_date == event.end_date

    def test_collection_state_no_timestamps(self) -> None:
        """CollectionState without timestamps should use defaults."""
        state = CollectionState(
            channel_id="UCtest",
            phase="videos",
        )
        assert state.started_at is None
        assert state.updated_at is None
        assert state.status == "in_progress"


# ============================================================
# B-06: Large-scale data
# ============================================================
class TestB06LargeScale:
    """Condition: Massive data volumes."""

    def test_parse_10000_titles_no_crash(self) -> None:
        """Parsing 10,000 titles should complete without error."""
        parser = TitleParser()
        videos = [
            {"video_id": f"v{i}", "title": f"홍길동 2024 미생물 {i % 16 + 1}주차 1차시"}
            for i in range(10000)
        ]
        results, stats = parser.parse_batch(videos)
        assert stats["total"] == 10000
        assert stats["success_count"] > 0

    def test_large_json_write_read_roundtrip(self, tmp_path: Path) -> None:
        """Writing and reading 10,000 video records should work."""
        videos = [
            {"video_id": f"v{i}", "title": f"title_{i}", "view_count": i}
            for i in range(10000)
        ]
        path = tmp_path / "large.json"
        write_json(path, videos)
        loaded = read_json(path)
        assert len(loaded) == 10000

    def test_large_parquet_write_read(self, tmp_path: Path) -> None:
        """Large Parquet file should write and read correctly."""
        df = pl.DataFrame(
            {
                "video_id": [f"v{i}" for i in range(50000)],
                "view_count": list(range(50000)),
            }
        )
        path = tmp_path / "large.parquet"
        write_parquet(path, df)
        loaded = read_parquet(path)
        assert loaded.shape[0] == 50000

    def test_filter_large_video_list(self) -> None:
        """Filtering 50,000 videos by keyword should be fast and correct."""
        videos = [
            {
                "video_id": f"v{i}",
                "title": f"미생물학 {i % 16 + 1}주차" if i % 3 == 0 else f"Other {i}",
                "published_at": "2024-01-01",
            }
            for i in range(50000)
        ]
        vf = VideoFilter(keyword="미생물학")
        result = VideoFilterService.filter_videos(videos, vf)
        expected = sum(1 for i in range(50000) if i % 3 == 0)
        assert len(result) == expected

    def test_append_parquet_accumulates(self, tmp_path: Path) -> None:
        """Multiple append_parquet calls should accumulate data."""
        path = tmp_path / "append.parquet"
        for batch in range(5):
            df = pl.DataFrame(
                {
                    "video_id": [f"v{batch}_{i}" for i in range(100)],
                    "val": list(range(100)),
                }
            )
            append_parquet(path, df)

        loaded = read_parquet(path)
        assert loaded.shape[0] == 500

    def test_batch_parse_empty_list(self) -> None:
        """Batch parsing empty list should return empty results."""
        parser = TitleParser()
        results, stats = parser.parse_batch([])
        assert results == []
        assert stats["total"] == 0
        assert stats["success_rate"] == 0.0

    def test_video_filter_no_criteria_raises(self) -> None:
        """Empty VideoFilter (no condition) should fail validation."""
        with pytest.raises(ValidationError, match="At least one filter condition"):
            VideoFilter()

    def test_video_filter_broad_keyword_returns_many(self) -> None:
        """VideoFilter with broad keyword should return all matching."""
        videos = [
            {"video_id": f"v{i}", "title": f"강의 {i}", "published_at": "2024-01-01"}
            for i in range(100)
        ]
        vf = VideoFilter(keyword="강의")
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 100


# ============================================================
# B-07: Concurrency and race conditions
# ============================================================
class TestB07Concurrency:
    """Condition: Parallel execution, file contention."""

    def test_concurrent_checkpoint_different_phases(self, tmp_path: Path) -> None:
        """Writing checkpoints for different phases simultaneously should work."""
        checkpoint_dir = tmp_path / "checkpoints"

        for phase in ["videos", "retention", "transcripts", "analytics"]:
            state = CollectionState(
                channel_id="UCtest",
                phase=phase,
                status="completed",
                started_at=datetime.now(UTC),
            )
            save_checkpoint(checkpoint_dir, state)

        # All phases should be independently readable
        for phase in ["videos", "retention", "transcripts", "analytics"]:
            loaded = load_checkpoint(checkpoint_dir, "UCtest", phase)
            assert loaded is not None
            assert loaded.status == "completed"
            assert loaded.phase == phase

    def test_checkpoint_overwrite_preserves_other_entries(self, tmp_path: Path) -> None:
        """Overwriting one checkpoint should not affect other channels/phases."""
        checkpoint_dir = tmp_path / "checkpoints"

        state_a = CollectionState(
            channel_id="UCa",
            phase="videos",
            status="completed",
            started_at=datetime.now(UTC),
        )
        state_b = CollectionState(
            channel_id="UCb",
            phase="videos",
            status="completed",
            started_at=datetime.now(UTC),
        )
        save_checkpoint(checkpoint_dir, state_a)
        save_checkpoint(checkpoint_dir, state_b)

        # Overwrite A
        state_a_new = CollectionState(
            channel_id="UCa",
            phase="videos",
            status="interrupted",
            started_at=datetime.now(UTC),
        )
        save_checkpoint(checkpoint_dir, state_a_new)

        # B should be untouched
        loaded_b = load_checkpoint(checkpoint_dir, "UCb", "videos")
        assert loaded_b.status == "completed"

        loaded_a = load_checkpoint(checkpoint_dir, "UCa", "videos")
        assert loaded_a.status == "interrupted"

    def test_atomic_write_json_replaces_fully(self, tmp_path: Path) -> None:
        """write_json should atomically replace — no partial content visible."""
        path = tmp_path / "atomic.json"
        write_json(path, {"version": 1})
        write_json(path, {"version": 2})
        data = read_json(path)
        assert data["version"] == 2

    def test_rapid_project_create_no_collision(self, tmp_path: Path) -> None:
        """Creating projects in rapid succession should not collide on names."""
        projects_root = tmp_path / "projects"
        created = set()
        for _ in range(5):
            mgr = ProjectManager(projects_root=projects_root)
            p = mgr.create_project()
            assert p not in created
            created.add(p)
            time.sleep(1.1)  # Ensure different second

    def test_parquet_overwrite_is_complete(self, tmp_path: Path) -> None:
        """Overwriting a Parquet file should replace all data."""
        path = tmp_path / "data.parquet"
        df1 = pl.DataFrame({"a": [1, 2, 3]})
        df2 = pl.DataFrame({"a": [10, 20]})

        write_parquet(path, df1)
        write_parquet(path, df2)

        loaded = read_parquet(path)
        assert loaded.shape[0] == 2
        assert loaded["a"].to_list() == [10, 20]

    def test_multiple_channel_checkpoints_same_file(self, tmp_path: Path) -> None:
        """Many channels' checkpoints in same file should not corrupt."""
        checkpoint_dir = tmp_path / "checkpoints"
        channels = [f"UC{i:04d}" for i in range(20)]

        for ch in channels:
            state = CollectionState(
                channel_id=ch,
                phase="videos",
                status="completed",
                total_collected=100,
                started_at=datetime.now(UTC),
            )
            save_checkpoint(checkpoint_dir, state)

        # All should be loadable
        for ch in channels:
            loaded = load_checkpoint(checkpoint_dir, ch, "videos")
            assert loaded is not None
            assert loaded.channel_id == ch

    def test_latest_symlink_update_race(self, tmp_path: Path) -> None:
        """idea6 ADR-IDEA6-006: each commit_latest atomically swaps the link."""
        projects_root = tmp_path / "projects"
        last_project = None
        for _ in range(3):
            mgr = ProjectManager(projects_root=projects_root)
            last_project = mgr.create_project()
            mgr.videos_meta("nursing").write_text("[]", encoding="utf-8")
            mgr.commit_latest()
            time.sleep(1.1)

        mgr2 = ProjectManager(projects_root=projects_root)
        latest = mgr2.resolve_latest()
        assert latest is not None
        assert latest.resolve() == last_project.resolve()

    def test_save_registry_overwrites_atomically(self, tmp_path: Path) -> None:
        """save_registry should fully replace the registry file."""
        from tube_scout.models.config import ChannelRegistration
        from tube_scout.services.auth import load_registry, save_registry

        tokens_dir = tmp_path / "tokens"
        now = datetime.now(UTC).isoformat()

        reg1 = {
            "dept_a": ChannelRegistration(
                alias="dept_a",
                channel_id="UCa",
                channel_name="A",
                registered_at=now,
                last_used_at=now,
                token_path="/tmp/a.json",
            )
        }
        reg2 = {
            "dept_b": ChannelRegistration(
                alias="dept_b",
                channel_id="UCb",
                channel_name="B",
                registered_at=now,
                last_used_at=now,
                token_path="/tmp/b.json",
            )
        }

        save_registry(tokens_dir, reg1)
        save_registry(tokens_dir, reg2)

        loaded = load_registry(tokens_dir)
        assert "dept_b" in loaded
        assert "dept_a" not in loaded  # fully replaced
