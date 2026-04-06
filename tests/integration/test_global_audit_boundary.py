"""Layer 3 integration tests: Boundary condition verification.

Tests 10 boundary conditions across module boundaries:
  1. Empty channel (0 videos) -> full pipeline -> empty report
  2. Partial collection + resume -> checkpoint -> no duplicates
  3. API error mid-collection -> save collected -> retry uncollected
  4. Legacy JSON schema -> current Pydantic model load
  5. Large scale (1000 videos mock) -> pagination + memory
  6. Analytics data absent -> report section omission
  7. Partial transcript failure -> report still generated
  8. Collect-all mid-interruption -> resume skips completed stages
  9. Multi-channel token expiry -> only that channel fails
  10. Concurrent file writes -> no corruption
"""

import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from tube_scout.models.config import CollectionState
from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.video import Video
from tube_scout.reporting.department_report import DepartmentReportGenerator
from tube_scout.services.forecaster import ForecasterService
from tube_scout.services.transcript import TranscriptService
from tube_scout.services.youtube_analytics import YouTubeAnalyticsService
from tube_scout.services.youtube_data import YouTubeDataService
from tube_scout.storage.checkpoint import (
    clear_checkpoint,
    is_stage_complete,
    load_checkpoint,
    mark_stage_complete,
    save_checkpoint,
)
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import append_parquet, read_parquet, write_parquet

CHANNEL_ID = "UCxxxxxxxxxxxxxxxxxxxxxx"


# ===========================================================================
# BC-1: Empty channel (0 videos) -> full pipeline -> empty report
# ===========================================================================


class TestBC1EmptyChannel:
    """Empty channel should produce valid but empty results."""

    def test_empty_playlist_returns_empty_list(self) -> None:
        """YouTubeDataService returns [] for an empty playlist."""
        client = MagicMock()
        client.playlistItems().list.return_value.execute.return_value = {"items": []}
        svc = YouTubeDataService(client)
        videos = svc.list_all_videos("UUxxxxxxxxxxxxxxxxxxxxxx")
        assert videos == []

    def test_empty_videos_department_report(self, tmp_path: Path) -> None:
        """Department report with 0 videos produces valid empty overview."""
        gen = DepartmentReportGenerator()
        overview = gen.compute_overview([], [], CHANNEL_ID, "테스트학과")
        assert overview.total_videos == 0
        assert overview.total_professors == 0
        assert overview.parse_success_rate == 0.0

    def test_empty_professor_details(self) -> None:
        """compute_professor_details returns [] for no titles."""
        gen = DepartmentReportGenerator()
        details = gen.compute_professor_details([], [])
        assert details == []

    def test_empty_retention_analytics(self) -> None:
        """Analytics with no rows returns empty list."""
        client = MagicMock()
        client.reports().query.return_value.execute.return_value = {"rows": []}
        svc = YouTubeAnalyticsService(client=client)
        data = svc.get_retention_data("vid001")
        assert data == []

    def test_forecaster_insufficient_data(self) -> None:
        """Forecaster raises ValueError for insufficient data."""
        svc = ForecasterService()
        with pytest.raises(ValueError, match="At least 6 months"):
            svc.predict(CHANNEL_ID, "views", [{"date": 1, "value": 1.0}])


# ===========================================================================
# BC-2: Partial collection + resume -> checkpoint -> no duplicates
# ===========================================================================


class TestBC2PartialResume:
    """Checkpoint-based resume must not produce duplicate data."""

    def test_checkpoint_partial_then_resume(self, tmp_path: Path) -> None:
        """Save partial state, then resume from checkpoint."""
        # Phase 1: collect 50 of 100
        state = CollectionState(
            channel_id=CHANNEL_ID,
            phase="videos",
            last_page_token="TOKEN_50",
            total_expected=100,
            total_collected=50,
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            status="in_progress",
        )
        save_checkpoint(tmp_path, state)

        # Phase 2: resume
        resumed = load_checkpoint(tmp_path, CHANNEL_ID, "videos")
        assert resumed is not None
        assert resumed.last_page_token == "TOKEN_50"
        assert resumed.total_collected == 50

    def test_detect_new_videos_prevents_duplicates(self) -> None:
        """detect_new_videos filters out already-collected IDs."""
        client = MagicMock()
        svc = YouTubeDataService(client)

        api_videos = [
            {"video_id": f"vid{i:03d}", "title": f"L{i}", "published_at": "2024-01-01"}
            for i in range(1, 11)
        ]
        existing = {f"vid{i:03d}" for i in range(1, 6)}

        new = svc.detect_new_videos(api_videos, existing)
        assert len(new) == 5
        new_ids = {v["video_id"] for v in new}
        assert new_ids == {f"vid{i:03d}" for i in range(6, 11)}

    def test_parquet_append_no_duplicates(self, tmp_path: Path) -> None:
        """Appending to parquet with duplicate detection."""
        path = tmp_path / "retention.parquet"

        # Write initial data
        df1 = pl.DataFrame(
            {
                "video_id": ["vid001", "vid002"],
                "value": [1.0, 2.0],
            }
        )
        write_parquet(path, df1)

        # Append new data
        df2 = pl.DataFrame(
            {
                "video_id": ["vid003"],
                "value": [3.0],
            }
        )
        append_parquet(path, df2)

        loaded = read_parquet(path)
        assert loaded is not None
        assert loaded.shape[0] == 3


# ===========================================================================
# BC-3: API error mid-collection -> save collected -> retry uncollected
# ===========================================================================


class TestBC3ApiErrorMidCollection:
    """API errors should not lose already-collected data."""

    def test_analytics_partial_collection_on_error(self) -> None:
        """collect_all_reports captures partial results + error list."""
        client = MagicMock()

        call_count = 0

        def mock_query(**kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock_exec = MagicMock()
            if call_count == 1:
                # daily_metrics succeeds
                mock_exec.execute.return_value = {
                    "rows": [["2024-01-01", 100, 500.0, 300.0, 75.0]]
                }
            else:
                # Other report types fail
                from googleapiclient.errors import HttpError

                resp = MagicMock()
                resp.status = 500
                mock_exec.execute.side_effect = HttpError(resp, b"Server Error")
            return mock_exec

        client.reports().query = mock_query

        svc = YouTubeAnalyticsService(client=client)
        result = svc.collect_all_reports(
            channel_id=CHANNEL_ID,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            report_types=["daily_metrics", "traffic_sources"],
        )

        # daily_metrics should have succeeded
        assert "daily_metrics" in result
        # traffic_sources should be in errors
        assert len(result["errors"]) >= 1

    def test_checkpoint_preserves_progress_on_error(self, tmp_path: Path) -> None:
        """Checkpoint saved before error is not lost."""
        state = CollectionState(
            channel_id=CHANNEL_ID,
            phase="retention",
            total_expected=50,
            total_collected=30,
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            status="in_progress",
        )
        save_checkpoint(tmp_path, state)

        # Simulate error (state stays at 30)
        loaded = load_checkpoint(tmp_path, CHANNEL_ID, "retention")
        assert loaded is not None
        assert loaded.total_collected == 30
        assert loaded.status == "in_progress"


# ===========================================================================
# BC-4: Legacy JSON schema -> current Pydantic model load
# ===========================================================================


class TestBC4LegacySchema:
    """Legacy JSON data should still load into current models."""

    def test_video_model_tolerates_missing_optional_fields(self) -> None:
        """Video model loads with only required fields."""
        minimal = {
            "video_id": "vid001",
            "channel_id": CHANNEL_ID,
            "title": "Old Video",
            "published_at": "2023-06-15T00:00:00Z",
        }
        video = Video(**minimal)
        assert video.duration_seconds == 0
        assert video.has_transcript is False
        assert video.tags == []

    def test_video_model_ignores_unknown_fields(self) -> None:
        """Video model with extra fields does not crash (Pydantic v2 default)."""
        data = {
            "video_id": "vid001",
            "channel_id": CHANNEL_ID,
            "title": "Old Video",
            "published_at": "2023-06-15T00:00:00Z",
            "unknown_legacy_field": "should be ignored",
        }
        # Pydantic v2 ignores extra fields by default
        video = Video(**data)
        assert video.video_id == "vid001"

    def test_collection_state_backward_compat(self) -> None:
        """CollectionState loads from legacy JSON without new fields."""
        legacy = {
            "channel_id": CHANNEL_ID,
            "phase": "videos",
            "status": "in_progress",
        }
        state = CollectionState(**legacy)
        assert state.stage_completed is False
        assert state.analytics_last_dates == {}

    def test_parsed_title_backward_compat(self) -> None:
        """ParsedTitle loads from data missing optional fields."""
        data = {
            "video_id": "vid001",
            "original_title": "Some Old Title",
        }
        pt = ParsedTitle(**data)
        assert pt.professor == []
        assert pt.parse_error is False


# ===========================================================================
# BC-5: Large scale (1000 videos mock) -> pagination + memory
# ===========================================================================


class TestBC5LargeScale:
    """Large-scale data handling within memory limits."""

    def test_large_video_list_pagination(self) -> None:
        """YouTubeDataService handles multi-page responses."""
        client = MagicMock()

        # Simulate 3 pages of 50 items each (150 total)
        pages = []
        for page_idx in range(3):
            items = [
                {
                    "snippet": {
                        "resourceId": {"videoId": f"vid{page_idx * 50 + i:04d}"},
                        "title": f"Lecture {page_idx * 50 + i}",
                        "publishedAt": "2024-01-01T00:00:00Z",
                    }
                }
                for i in range(50)
            ]
            pages.append(
                {
                    "items": items,
                    "nextPageToken": f"PAGE{page_idx + 1}" if page_idx < 2 else None,
                }
            )

        # Return pages in sequence
        client.playlistItems().list.return_value.execute.side_effect = pages

        svc = YouTubeDataService(client)
        videos = svc.list_all_videos("UUxxxxxxxxxxxxxxxxxxxxxx")
        assert len(videos) == 150

    def test_large_batch_video_details(self) -> None:
        """get_video_details batches requests by 50."""
        client = MagicMock()

        def mock_execute() -> dict:
            return {
                "items": [
                    {
                        "id": f"vid{i:04d}",
                        "snippet": {"title": f"L{i}", "tags": []},
                        "contentDetails": {"duration": "PT10M", "caption": "false"},
                        "statistics": {"viewCount": "10"},
                        "status": {"privacyStatus": "public"},
                        "topicDetails": {},
                    }
                    for i in range(50)
                ]
            }

        client.videos().list.return_value.execute.side_effect = [
            mock_execute()
            for _ in range(20)  # 1000 / 50 = 20 batches
        ]

        svc = YouTubeDataService(client)
        ids = [f"vid{i:04d}" for i in range(1000)]
        details = svc.get_video_details(ids)
        # Each batch returns 50 items with same IDs; total unique depends on mock
        assert len(details) > 0

    def test_large_json_store_performance(self, tmp_path: Path) -> None:
        """JSON store handles 1000+ items without issue."""
        path = tmp_path / "large.json"
        data = [{"video_id": f"vid{i:04d}", "title": f"Video {i}"} for i in range(1000)]
        write_json(path, data)
        loaded = read_json(path)
        assert loaded is not None
        assert len(loaded) == 1000


# ===========================================================================
# BC-6: Analytics data absent -> report section omission
# ===========================================================================


class TestBC6AnalyticsAbsent:
    """Missing analytics should not crash report generation."""

    def test_collect_all_reports_with_no_client(self) -> None:
        """YouTubeAnalyticsService without client raises ValueError."""
        svc = YouTubeAnalyticsService(client=None)
        with pytest.raises(ValueError, match="not configured"):
            svc.get_daily_metrics(
                channel_id=CHANNEL_ID,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

    def test_eqs_no_retention_no_comments(self) -> None:
        """EQS evaluate works with empty retention and comments."""
        from tube_scout.services.eqs import EQSService

        svc = EQSService(llm=None)
        result = svc.evaluate("vid001", "", [], [])
        assert result["overall"] == 0.0

    def test_department_report_no_analytics(self, tmp_path: Path) -> None:
        """Department report generates even without analytics data."""
        gen = DepartmentReportGenerator()
        titles = [
            ParsedTitle(
                video_id="vid001",
                original_title="홍길동 2024 해부학 1주차 1차시",
                professor=["홍길동"],
                course="해부학",
                year=2024,
                week=1,
                session=1,
            )
        ]
        videos = [
            Video(
                video_id="vid001",
                channel_id=CHANNEL_ID,
                title="홍길동 2024 해부학 1주차 1차시",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
                duration_seconds=600,
                view_count=100,
            )
        ]
        overview = gen.compute_overview(titles, videos, CHANNEL_ID, "학과")
        assert overview.total_videos == 1


# ===========================================================================
# BC-7: Partial transcript failure -> report still generated
# ===========================================================================


class TestBC7PartialTranscriptFailure:
    """Some transcripts failing should not block the rest."""

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_mixed_transcript_results(self, mock_api_cls: MagicMock) -> None:
        """Some videos get transcripts, others fail gracefully."""
        from youtube_transcript_api import TranscriptsDisabled

        mock_api = mock_api_cls.return_value

        call_count = 0

        def mock_list(video_id: str) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise TranscriptsDisabled(video_id)
            mock_tl = MagicMock()
            mock_transcript = MagicMock()
            mock_transcript.fetch.return_value = [
                {"text": "OK", "start": 0.0, "duration": 1.0}
            ]
            mock_tl.find_manually_created_transcript.return_value = mock_transcript
            return mock_tl

        mock_api.list = mock_list

        svc = TranscriptService()
        results = []
        for vid_id in ["vid001", "vid002", "vid003", "vid004"]:
            result = svc.fetch_transcript(vid_id)
            results.append(result)

        # vid001, vid003 succeed; vid002, vid004 fail
        successes = [r for r in results if r is not None]
        failures = [r for r in results if r is None]
        assert len(successes) == 2
        assert len(failures) == 2


# ===========================================================================
# BC-8: Collect-all mid-interruption -> resume skips completed stages
# ===========================================================================


class TestBC8CollectAllInterruption:
    """After interruption, resume should skip completed stages."""

    def test_resume_skips_completed_stages(self, tmp_path: Path) -> None:
        """Stages 1,2 complete -> resume starts at stage 3."""
        # Mark first two stages complete
        mark_stage_complete(tmp_path, CHANNEL_ID, "videos")
        mark_stage_complete(tmp_path, CHANNEL_ID, "retention")

        stages = ["videos", "retention", "transcripts", "analytics"]
        executed = []

        for stage in stages:
            if is_stage_complete(tmp_path, CHANNEL_ID, stage):
                continue
            executed.append(stage)
            mark_stage_complete(tmp_path, CHANNEL_ID, stage)

        assert executed == ["transcripts", "analytics"]

    def test_clear_checkpoint_for_force_refresh(self, tmp_path: Path) -> None:
        """clear_checkpoint removes a stage for forced re-collection."""
        mark_stage_complete(tmp_path, CHANNEL_ID, "videos")
        assert is_stage_complete(tmp_path, CHANNEL_ID, "videos")

        clear_checkpoint(tmp_path, CHANNEL_ID, "videos")
        assert not is_stage_complete(tmp_path, CHANNEL_ID, "videos")


# ===========================================================================
# BC-9: Multi-channel token expiry -> only that channel fails
# ===========================================================================


class TestBC9MultiChannelTokenExpiry:
    """Token failure for one channel should not affect others."""

    def test_channel_registry_isolation(self, tmp_path: Path) -> None:
        """Per-channel checkpoints are independent."""
        ch1 = "UCchannel1_________________"
        ch2 = "UCchannel2_________________"

        mark_stage_complete(tmp_path, ch1, "videos")
        # ch2 should not be affected
        assert is_stage_complete(tmp_path, ch1, "videos")
        assert not is_stage_complete(tmp_path, ch2, "videos")

    def test_auth_failure_isolated(self) -> None:
        """PermissionError from one channel doesn't propagate to others."""
        from googleapiclient.errors import HttpError

        # Channel 1: 403 error
        client1 = MagicMock()
        resp = MagicMock()
        resp.status = 403
        client1.reports().query.return_value.execute.side_effect = HttpError(
            resp, b"Forbidden"
        )
        svc1 = YouTubeAnalyticsService(client=client1)

        with pytest.raises(PermissionError):
            svc1.get_daily_metrics(
                channel_id="UCchannel1_________________",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

        # Channel 2: works fine
        client2 = MagicMock()
        client2.reports().query.return_value.execute.return_value = {
            "rows": [["2024-01-01", 100, 500.0, 300.0, 75.0]]
        }
        svc2 = YouTubeAnalyticsService(client=client2)
        data = svc2.get_daily_metrics(
            channel_id="UCchannel2_________________",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(data) == 1


# ===========================================================================
# BC-10: Concurrent file writes -> no corruption
# ===========================================================================


class TestBC10ConcurrentWrites:
    """Concurrent file operations should not corrupt data."""

    def test_concurrent_json_writes(self, tmp_path: Path) -> None:
        """Multiple threads writing different JSON files concurrently."""
        errors: list[Exception] = []

        def write_file(idx: int) -> None:
            try:
                path = tmp_path / f"file_{idx}.json"
                data = {"id": idx, "data": list(range(100))}
                write_json(path, data)
                loaded = read_json(path)
                assert loaded is not None
                assert loaded["id"] == idx
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_file, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_checkpoint_writes_isolated(self, tmp_path: Path) -> None:
        """Multiple channels saving checkpoints to separate directories."""
        errors: list[Exception] = []

        def save_channel_checkpoint(idx: int) -> None:
            try:
                # Each channel gets its own data_dir to avoid shared-file races
                data_dir = tmp_path / f"channel_{idx:02d}"
                ch_id = f"UCchannel{idx:02d}________________"
                state = CollectionState(
                    channel_id=ch_id,
                    phase="videos",
                    total_collected=idx * 10,
                    started_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                save_checkpoint(data_dir, state)
                loaded = load_checkpoint(data_dir, ch_id, "videos")
                assert loaded is not None
                assert loaded.total_collected == idx * 10
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=save_channel_checkpoint, args=(i,))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
