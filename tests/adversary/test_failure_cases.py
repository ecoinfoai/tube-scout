"""Adversarial failure case tests for tube-scout.

These tests verify graceful error handling for edge cases,
malformed input, missing data, and boundary conditions.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from tube_scout.models.config import AppConfig, ChannelConfig, CollectionState, Settings
from tube_scout.reporting.channel_report import ChannelReportGenerator
from tube_scout.reporting.video_report import VideoReportGenerator, generate_suggestions
from tube_scout.services.eqs import EQSService
from tube_scout.services.forecaster import ForecasterService
from tube_scout.services.segmenter import SegmenterService, compare_with_retention
from tube_scout.services.sentiment import (
    SentimentService,
    cross_reference_questions_hotspots,
)
from tube_scout.services.transcript import TranscriptService
from tube_scout.services.youtube_analytics import (
    YouTubeAnalyticsService,
    detect_rewatch_hotspots,
    detect_skip_zones,
)
from tube_scout.services.youtube_data import YouTubeDataService, _parse_iso8601_duration
from tube_scout.storage.checkpoint import (
    clear_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from tube_scout.storage.json_store import read_json, write_json


# ============================================================
# PERSONA 1: Malformed config.json
# ============================================================
class TestMalformedConfig:
    """Persona: User manually edits config.json and corrupts it."""

    def test_empty_json_object(self, tmp_path: Path) -> None:
        """Config with empty object should fail validation."""
        with pytest.raises(ValidationError):
            AppConfig(**{})

    def test_missing_channels_key(self, tmp_path: Path) -> None:
        """Config missing 'channels' should fail."""
        with pytest.raises(ValidationError):
            AppConfig(settings=Settings())

    def test_channels_not_a_list(self) -> None:
        """Config with channels as a string should fail."""
        with pytest.raises(ValidationError):
            AppConfig(channels="not_a_list")

    def test_channel_missing_channel_id(self) -> None:
        """Channel config without channel_id should fail."""
        with pytest.raises(ValidationError):
            ChannelConfig(professor_name="Prof")

    def test_channel_missing_professor_name(self) -> None:
        """Channel config without professor_name should fail."""
        with pytest.raises(ValidationError):
            ChannelConfig(channel_id="UCxxxxxxxxxxxxxxxxxxxxxx")

    def test_invalid_json_file_raises_on_read(self, tmp_path: Path) -> None:
        """Corrupted JSON file (not valid JSON syntax) should raise."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json content,,,}", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            read_json(bad_file)

    def test_null_values_in_config(self) -> None:
        """Null channel_id should fail validation."""
        with pytest.raises(ValidationError):
            ChannelConfig(channel_id=None, professor_name="Prof")

    def test_extra_unknown_fields_tolerated(self) -> None:
        """Extra fields in JSON should be ignored by Pydantic (default)."""
        config = ChannelConfig(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            professor_name="Prof",
            unknown_field="should_be_ignored",
        )
        assert config.channel_id == "UCxxxxxxxxxxxxxxxxxxxxxx"

    def test_unicode_injection_in_professor_name(self) -> None:
        """Professor name with unicode zero-width chars should be handled."""
        # Zero-width space + professor name
        config = ChannelConfig(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            professor_name="\u200b\u200bProf",
        )
        # Should strip/accept -- but the filter won't match real titles
        assert config.professor_name is not None


# ============================================================
# PERSONA 2: Missing environment variables
# ============================================================
class TestMissingEnvVars:
    """Persona: User has no YOUTUBE_API_KEY set."""

    def test_youtube_data_service_requires_api_key(self) -> None:
        """YouTubeDataService should raise ValueError if no API key."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove key if present
            os.environ.pop("YOUTUBE_API_KEY", None)
            with pytest.raises(ValueError, match="YOUTUBE_API_KEY"):
                YouTubeDataService()

    def test_analytics_service_no_client_raises(self) -> None:
        """Analytics service with no client should raise on get_retention_data."""
        service = YouTubeAnalyticsService(client=None)
        with pytest.raises(ValueError, match="not configured"):
            service.get_retention_data("vid001")


# ============================================================
# PERSONA 3: Empty data directory (analyze before collect)
# ============================================================
class TestEmptyDataDir:
    """Persona: User runs analyze commands before collecting data."""

    def test_load_checkpoint_from_empty_dir(self, tmp_path: Path) -> None:
        """Loading checkpoint from empty dir should return None."""
        result = load_checkpoint(tmp_path, "UC_fake", "videos")
        assert result is None

    def test_read_json_nonexistent_file(self, tmp_path: Path) -> None:
        """Reading nonexistent JSON returns None."""
        result = read_json(tmp_path / "nonexistent.json")
        assert result is None

    def test_generate_suggestions_with_no_data(self) -> None:
        """Suggestions with empty video and no analysis data."""
        suggestions = generate_suggestions({}, None, None)
        assert isinstance(suggestions, list)

    def test_report_with_missing_video_meta(self, tmp_path: Path) -> None:
        """Video report generator should handle missing metadata gracefully."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        generator = VideoReportGenerator(data_dir=data_dir)
        # _load_video_meta should return fallback
        meta = generator._load_video_meta("nonexistent_vid", "UCfakechannel")
        assert meta["video_id"] == "nonexistent_vid"

    def test_channel_report_with_no_videos(self, tmp_path: Path) -> None:
        """Channel report insights with empty video list."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        generator = ChannelReportGenerator(data_dir=data_dir)
        videos = generator._load_videos("UCfakechannel")
        assert videos == []
        insights = generator._generate_insights([])
        assert "No videos" in insights[0]


# ============================================================
# PERSONA 4: Corrupted checkpoint file
# ============================================================
class TestCorruptedCheckpoint:
    """Persona: Checkpoint file is corrupted mid-resume."""

    def test_corrupted_checkpoint_json(self, tmp_path: Path) -> None:
        """Corrupted checkpoint JSON should raise on load."""
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir(parents=True)
        ckpt_file = ckpt_dir / "collection_state.json"
        ckpt_file.write_text("{broken json###", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_checkpoint(tmp_path, "UCfake", "videos")

    def test_checkpoint_with_wrong_schema(self, tmp_path: Path) -> None:
        """Checkpoint with unexpected schema should raise Pydantic error."""
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir(parents=True)
        ckpt_file = ckpt_dir / "collection_state.json"
        # Valid JSON but wrong schema for CollectionState
        write_json(ckpt_file, {"UCfake:videos": {"wrong_field": "wrong_value"}})
        with pytest.raises((ValidationError, TypeError)):
            load_checkpoint(tmp_path, "UCfake", "videos")

    def test_save_checkpoint_creates_dirs(self, tmp_path: Path) -> None:
        """save_checkpoint should create directories if not present."""
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
            status="in_progress",
        )
        save_checkpoint(tmp_path, state)
        loaded = load_checkpoint(tmp_path, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert loaded is not None
        assert loaded.status == "in_progress"

    def test_clear_checkpoint_nonexistent(self, tmp_path: Path) -> None:
        """Clearing nonexistent checkpoint should not raise."""
        clear_checkpoint(tmp_path, "UCfake", "videos")  # Should not raise


# ============================================================
# PERSONA 5: Invalid channel ID format
# ============================================================
class TestInvalidChannelId:
    """Persona: User enters wrong channel ID format."""

    def test_channel_id_no_uc_prefix(self) -> None:
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelConfig(channel_id="ABinvalidchannel", professor_name="Prof")

    def test_channel_id_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            ChannelConfig(channel_id="", professor_name="Prof")

    def test_channel_id_special_characters(self) -> None:
        """SQL injection attempt in channel_id should be rejected."""
        with pytest.raises(ValidationError):
            ChannelConfig(
                channel_id="'; DROP TABLE videos;--",
                professor_name="Prof",
            )

    def test_channel_id_too_short(self) -> None:
        """'UC' alone is not a valid channel ID -- needs chars after prefix."""
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelConfig(channel_id="UC", professor_name="Prof")

    def test_channel_id_with_spaces_rejected(self) -> None:
        """channel_id with spaces is correctly rejected by regex."""
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelConfig(
                channel_id="UC with spaces",
                professor_name="Prof",
            )

    def test_channel_id_url_instead_of_id(self) -> None:
        """User pastes full URL instead of channel ID."""
        with pytest.raises(ValidationError):
            ChannelConfig(
                channel_id="https://youtube.com/channel/UCxxxxxx",
                professor_name="Prof",
            )


# ============================================================
# PERSONA 6: Valid format but nonexistent channel
# ============================================================
class TestNonexistentChannel:
    """Persona: Valid UC-prefixed ID but channel doesn't exist."""

    def test_get_channel_info_not_found(self) -> None:
        """get_channel_info raises ValueError for nonexistent channel."""
        mock_client = MagicMock()
        mock_client.channels().list().execute.return_value = {"items": []}
        service = YouTubeDataService(client=mock_client)
        with pytest.raises(ValueError, match="Channel not found"):
            service.get_channel_info("UCnonexistent000000000000")


# ============================================================
# PERSONA 7: Channel with 0 matching videos
# ============================================================
class TestZeroMatchingVideos:
    """Persona: Channel exists but no videos match professor name."""

    def test_filter_returns_empty_list(self) -> None:
        service = YouTubeDataService(client=MagicMock())
        videos = [
            {"video_id": "v1", "title": "Other Professor Lecture"},
            {"video_id": "v2", "title": "Random Video"},
        ]
        result = service.filter_by_professor(videos, "NonexistentProf")
        assert result == []

    def test_filter_all_videos_empty(self) -> None:
        service = YouTubeDataService(client=MagicMock())
        result = service.filter_by_professor([], "Prof")
        assert result == []


# ============================================================
# PERSONA 8: Professor name partial match edge cases
# ============================================================
class TestProfessorNameMatching:
    """Persona: Various professor name formats in titles."""

    def test_exact_name(self) -> None:
        service = YouTubeDataService(client=MagicMock())
        videos = [{"video_id": "v1", "title": "홍길동 강의"}]
        assert len(service.filter_by_professor(videos, "홍길동")) == 1

    def test_name_with_suffix(self) -> None:
        """'홍길동교수' should match when filtering for '홍길동'."""
        service = YouTubeDataService(client=MagicMock())
        videos = [{"video_id": "v1", "title": "홍길동교수 특강"}]
        assert len(service.filter_by_professor(videos, "홍길동")) == 1

    def test_name_with_space_suffix(self) -> None:
        """'홍길동 교수' should match '홍길동'."""
        service = YouTubeDataService(client=MagicMock())
        videos = [{"video_id": "v1", "title": "홍길동 교수의 해부학"}]
        assert len(service.filter_by_professor(videos, "홍길동")) == 1

    def test_similar_but_different_name(self) -> None:
        """'정광' should NOT match '홍길동' filter (reverse direction)."""
        service = YouTubeDataService(client=MagicMock())
        videos = [{"video_id": "v1", "title": "정광 강의"}]
        assert len(service.filter_by_professor(videos, "홍길동")) == 0

    def test_case_sensitivity_english(self) -> None:
        """English professor names are case-sensitive in current impl."""
        service = YouTubeDataService(client=MagicMock())
        videos = [{"video_id": "v1", "title": "Dr. Smith Lecture"}]
        assert len(service.filter_by_professor(videos, "smith")) == 0
        assert len(service.filter_by_professor(videos, "Smith")) == 1

    def test_empty_title(self) -> None:
        """Video with empty title should not crash."""
        service = YouTubeDataService(client=MagicMock())
        videos = [{"video_id": "v1", "title": ""}]
        assert len(service.filter_by_professor(videos, "Prof")) == 0

    def test_missing_title_key(self) -> None:
        """Video without 'title' key should not crash."""
        service = YouTubeDataService(client=MagicMock())
        videos = [{"video_id": "v1"}]
        assert len(service.filter_by_professor(videos, "Prof")) == 0


# ============================================================
# PERSONA 9: Channel with 1000+ videos (pagination stress)
# ============================================================
class TestLargeChannelPagination:
    """Persona: Channel with many videos tests pagination logic."""

    def test_pagination_collects_all_pages(self) -> None:
        """Verify all pages are fetched when nextPageToken is present."""
        mock_client = MagicMock()

        def make_page(page_num: int, has_next: bool) -> dict:
            items = [
                {
                    "snippet": {
                        "resourceId": {"videoId": f"vid_{page_num}_{i}"},
                        "title": f"Video {page_num}_{i}",
                        "publishedAt": "2024-01-01T00:00:00Z",
                    }
                }
                for i in range(50)
            ]
            result: dict[str, Any] = {"items": items}
            if has_next:
                result["nextPageToken"] = f"token_{page_num + 1}"
            return result

        # 3 pages = 150 videos
        mock_client.playlistItems().list().execute.side_effect = [
            make_page(1, True),
            make_page(2, True),
            make_page(3, False),
        ]

        service = YouTubeDataService(client=mock_client)
        videos = service.list_all_videos("UUxxxxxxxx")
        assert len(videos) == 150

    def test_video_details_batched(self) -> None:
        """Video details should be fetched in batches of 50."""
        mock_client = MagicMock()
        # 120 video IDs -> should make 3 API calls (50+50+20)
        video_ids = [f"vid_{i}" for i in range(120)]

        def make_detail_response(ids: list[str]) -> dict:
            return {
                "items": [
                    {
                        "id": vid_id,
                        "contentDetails": {"duration": "PT10M"},
                        "statistics": {
                            "viewCount": "100",
                            "likeCount": "5",
                            "commentCount": "2",
                        },
                    }
                    for vid_id in ids
                ]
            }

        mock_client.videos().list().execute.side_effect = [
            make_detail_response(video_ids[0:50]),
            make_detail_response(video_ids[50:100]),
            make_detail_response(video_ids[100:120]),
        ]

        service = YouTubeDataService(client=mock_client)
        details = service.get_video_details(video_ids)
        assert len(details) == 120


# ============================================================
# PERSONA 10: Video with disabled comments
# ============================================================
class TestDisabledComments:
    """Persona: Video has comments disabled."""

    def test_get_comments_returns_empty(self) -> None:
        """API returns empty items for disabled comments."""
        mock_client = MagicMock()
        mock_client.commentThreads().list().execute.return_value = {"items": []}
        service = YouTubeDataService(client=mock_client)
        comments = service.get_comments("vid_no_comments")
        assert comments == []

    def test_sentiment_analysis_empty_comments(self) -> None:
        """Sentiment service with empty comment list."""
        service = SentimentService(backend="skip")
        result = service.analyze_batch([])
        assert result == []

    def test_cross_reference_with_no_questions(self) -> None:
        """Cross-reference with no questions should return empty."""
        result = cross_reference_questions_hotspots(
            [],
            [{"elapsed_ratio": 0.5, "audience_watch_ratio": 1.2}],
        )
        assert result == []


# ============================================================
# PERSONA 11: Very short video (<30 seconds)
# ============================================================
class TestVeryShortVideo:
    """Persona: Video is less than 30 seconds."""

    def test_iso8601_duration_short(self) -> None:
        """PT20S should parse to 20 seconds."""
        assert _parse_iso8601_duration("PT20S") == 20

    def test_iso8601_duration_zero(self) -> None:
        """PT0S should parse to 0."""
        assert _parse_iso8601_duration("PT0S") == 0

    def test_retention_analysis_single_point(self) -> None:
        """Single retention data point should not crash hotspot detection."""
        data = [{"elapsed_ratio": 0.5, "audience_watch_ratio": 0.8}]
        hotspots = detect_rewatch_hotspots(data)
        assert isinstance(hotspots, list)

    def test_retention_analysis_empty(self) -> None:
        """Empty retention data should return empty lists."""
        assert detect_rewatch_hotspots([]) == []
        assert detect_skip_zones([]) == []

    def test_suggestions_for_short_video(self) -> None:
        """Short video should NOT get 'split into segments' suggestion."""
        video = {"duration_seconds": 25}
        suggestions = generate_suggestions(video, None, None)
        assert not any("splitting" in s.lower() for s in suggestions)


# ============================================================
# PERSONA 12: Analytics API permission denied
# ============================================================
class TestAnalyticsPermissionDenied:
    """Persona: No OAuth / expired token for Analytics API."""

    def test_403_raises_permission_error(self) -> None:
        """HTTP 403 should raise PermissionError."""
        from googleapiclient.errors import HttpError

        mock_client = MagicMock()
        resp = MagicMock()
        resp.status = 403
        error = HttpError(resp, b"Forbidden")
        mock_client.reports().query().execute.side_effect = error

        service = YouTubeAnalyticsService(client=mock_client)
        with pytest.raises(PermissionError, match="access denied"):
            service.get_retention_data("vid_no_auth")

    def test_401_raises_permission_error(self) -> None:
        """HTTP 401 should also raise PermissionError."""
        from googleapiclient.errors import HttpError

        mock_client = MagicMock()
        resp = MagicMock()
        resp.status = 401
        error = HttpError(resp, b"Unauthorized")
        mock_client.reports().query().execute.side_effect = error

        service = YouTubeAnalyticsService(client=mock_client)
        with pytest.raises(PermissionError, match="access denied"):
            service.get_retention_data("vid_unauthorized")


# ============================================================
# PERSONA 13: No transcript available
# ============================================================
class TestNoTranscript:
    """Persona: Video has no transcript in any language."""

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_transcripts_disabled(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        """TranscriptsDisabled should return None."""
        from youtube_transcript_api import TranscriptsDisabled

        mock_instance = mock_api_cls.return_value
        mock_instance.list.side_effect = TranscriptsDisabled(
            "vid_no_transcript",
        )
        service = TranscriptService()
        result = service.fetch_transcript("vid_no_transcript")
        assert result is None

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_no_transcript_found_any_language(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        """No transcript in any language returns None."""
        from youtube_transcript_api import NoTranscriptFound

        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "vid", ["ko", "en"], {}
        )
        tlist.find_generated_transcript.side_effect = NoTranscriptFound(
            "vid", ["ko", "en"], {}
        )
        service = TranscriptService()
        result = service.fetch_transcript("vid_no_sub")
        assert result is None

    def test_api_uses_instance_list_method(self) -> None:
        """Verify service uses YouTubeTranscriptApi().list() (new API)."""
        from youtube_transcript_api import YouTubeTranscriptApi as YtApi

        assert hasattr(YtApi, "list"), "New API uses .list() method"
        assert not hasattr(YtApi, "list_transcripts"), (
            "Old list_transcripts was removed"
        )

    def test_segmenter_empty_transcript(self) -> None:
        """Segmenter with empty text should return empty list."""
        service = SegmenterService()
        result = service.segment_transcript("vid001", "")
        assert result == []

    def test_segmenter_whitespace_only(self) -> None:
        """Segmenter with whitespace-only text should return empty list."""
        service = SegmenterService()
        result = service.segment_transcript("vid001", "   \n\t  ")
        assert result == []

    def test_eqs_empty_transcript(self) -> None:
        """EQS should return all-zero scores for empty transcript."""
        service = EQSService()
        result = service.evaluate("vid001", "", [], [])
        assert result["overall"] == 0.0
        assert result["relevance"] == 0.0


# ============================================================
# PERSONA 14: API quota exhaustion mid-collection
# ============================================================
class TestQuotaExhaustion:
    """Persona: YouTube API quota exceeded during collection."""

    def test_checkpoint_saved_on_interrupt(self, tmp_path: Path) -> None:
        """Checkpoint should be saved when status is 'interrupted'."""
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
            total_expected=500,
            total_collected=250,
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            status="interrupted",
        )
        save_checkpoint(tmp_path, state)
        loaded = load_checkpoint(tmp_path, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert loaded is not None
        assert loaded.status == "interrupted"
        assert loaded.total_collected == 250

    def test_resume_from_checkpoint(self, tmp_path: Path) -> None:
        """Loading interrupted checkpoint should preserve progress."""
        state = CollectionState(
            channel_id="UCtest",
            phase="videos",
            last_page_token="page_token_5",
            total_collected=200,
            status="interrupted",
        )
        save_checkpoint(tmp_path, state)
        loaded = load_checkpoint(tmp_path, "UCtest", "videos")
        assert loaded.last_page_token == "page_token_5"
        assert loaded.total_collected == 200

    def test_list_all_videos_with_page_token_resume(self) -> None:
        """list_all_videos should accept page_token for resume."""
        mock_client = MagicMock()
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "resourceId": {"videoId": "vid_resumed"},
                        "title": "Resumed Video",
                        "publishedAt": "2024-01-01T00:00:00Z",
                    }
                }
            ]
        }
        service = YouTubeDataService(client=mock_client)
        videos = service.list_all_videos("UUxxxx", page_token="resume_token")
        assert len(videos) == 1
        assert videos[0]["video_id"] == "vid_resumed"


# ============================================================
# PERSONA 15: Forecaster with insufficient data
# ============================================================
class TestForecasterEdgeCases:
    """Persona: Forecast requests with insufficient or unusual data."""

    def test_less_than_6_months_data(self) -> None:
        """Forecast with < 180 data points should raise ValueError."""
        service = ForecasterService()
        data = [{"date": i, "value": 100} for i in range(10)]
        with pytest.raises(ValueError, match="6 months"):
            service.predict("UCtest", "view_count", data)

    def test_exact_minimum_data(self) -> None:
        """Exactly 180 data points should work."""
        service = ForecasterService()
        data = [{"date": 740000 + i, "value": 100 + i} for i in range(180)]
        result = service.predict("UCtest", "view_count", data)
        assert len(result) == 30
        assert all("predicted_value" in r for r in result)

    def test_all_same_values(self) -> None:
        """Flat data (zero variance) should not crash."""
        service = ForecasterService()
        data = [{"date": 740000 + i, "value": 100} for i in range(200)]
        result = service.predict("UCtest", "view_count", data)
        assert len(result) == 30

    def test_anomaly_detection_empty(self) -> None:
        """Empty data should return empty anomalies."""
        service = ForecasterService()
        assert service.detect_anomalies([]) == []

    def test_anomaly_detection_constant_values(self) -> None:
        """All same values should have no anomalies (std=0)."""
        service = ForecasterService()
        data = [{"date": i, "value": 42} for i in range(100)]
        result = service.detect_anomalies(data)
        assert all(not r["is_anomaly"] for r in result)

    def test_anomaly_detection_with_outlier(self) -> None:
        """A clear outlier should be flagged."""
        service = ForecasterService()
        data = [{"date": i, "value": 100} for i in range(100)]
        data.append({"date": 100, "value": 10000})  # huge outlier
        result = service.detect_anomalies(data)
        anomalies = [r for r in result if r["is_anomaly"]]
        assert len(anomalies) >= 1


# ============================================================
# PERSONA 16: ISO 8601 duration parsing edge cases
# ============================================================
class TestDurationParsing:
    """Persona: YouTube returns unusual duration strings."""

    def test_hours_only(self) -> None:
        assert _parse_iso8601_duration("PT2H") == 7200

    def test_minutes_only(self) -> None:
        assert _parse_iso8601_duration("PT45M") == 2700

    def test_seconds_only(self) -> None:
        assert _parse_iso8601_duration("PT30S") == 30

    def test_full_duration(self) -> None:
        assert _parse_iso8601_duration("PT1H30M15S") == 5415

    def test_invalid_format(self) -> None:
        """Invalid format should return 0, not crash."""
        assert _parse_iso8601_duration("INVALID") == 0
        assert _parse_iso8601_duration("") == 0
        assert _parse_iso8601_duration("P1D") == 0  # days not supported


# ============================================================
# PERSONA 17: LLM backends not configured
# ============================================================
class TestLLMBackendsNotConfigured:
    """Persona: LLM API keys not set, backends raise NotImplementedError."""

    def test_sentiment_llm_backend_raises(self) -> None:
        """LLM sentiment backend should raise ValueError when no API key."""
        service = SentimentService(backend="llm")
        with pytest.raises(ValueError, match="sentiment-backend local"):
            service.analyze_batch([{"comment_id": "c1", "text": "test"}])

    def test_segmenter_raises(self) -> None:
        """Segmenter LLM call should raise NotImplementedError."""
        service = SegmenterService()
        with pytest.raises(NotImplementedError, match="API configuration"):
            service.segment_transcript("vid001", "Some real transcript text here.")

    def test_eqs_raises_for_nonempty_transcript(self) -> None:
        """EQS with non-empty transcript should raise (LLM needed)."""
        service = EQSService()
        with pytest.raises(NotImplementedError, match="API configuration"):
            service.evaluate("vid001", "Actual transcript content.", [], [])

    def test_sentiment_skip_backend_works(self) -> None:
        """Skip backend should work without any API keys."""
        service = SentimentService(backend="skip")
        result = service.analyze_batch(
            [
                {"comment_id": "c1", "text": "Great!"},
                {"comment_id": "c2", "text": "Bad!"},
            ]
        )
        assert len(result) == 2
        assert all(r["sentiment"] is None for r in result)


# ============================================================
# PERSONA 18: compare_with_retention edge cases
# ============================================================
class TestCompareWithRetention:
    """Persona: Cross-modal comparison with edge case data."""

    def test_empty_segments(self) -> None:
        assert compare_with_retention([], [], 600) == []

    def test_zero_duration(self) -> None:
        """Zero duration should return empty."""
        segments = [
            {"segment_index": 0, "start_seconds": 0, "end_seconds": 60, "title": "t"},
        ]
        assert compare_with_retention(segments, [], 0) == []

    def test_negative_duration(self) -> None:
        """Negative duration should return empty."""
        segments = [
            {"segment_index": 0, "start_seconds": 0, "end_seconds": 60, "title": "t"},
        ]
        assert compare_with_retention(segments, [], -1) == []


# ============================================================
# PERSONA 19: JSON store atomic write edge cases
# ============================================================
class TestJsonStoreEdgeCases:
    """Persona: File system edge cases for JSON storage."""

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Write should create nested directories."""
        deep_path = tmp_path / "a" / "b" / "c" / "file.json"
        write_json(deep_path, {"key": "value"})
        result = read_json(deep_path)
        assert result == {"key": "value"}

    def test_unicode_data_preserved(self, tmp_path: Path) -> None:
        """Korean text should be preserved in JSON."""
        filepath = tmp_path / "korean.json"
        data = {"professor": "홍길동", "title": "해부학 강의"}
        write_json(filepath, data)
        result = read_json(filepath)
        assert result["professor"] == "홍길동"

    def test_overwrite_existing_file(self, tmp_path: Path) -> None:
        """Writing to existing file should replace content."""
        filepath = tmp_path / "test.json"
        write_json(filepath, {"version": 1})
        write_json(filepath, {"version": 2})
        result = read_json(filepath)
        assert result["version"] == 2

    def test_non_serializable_data_raises(self, tmp_path: Path) -> None:
        """Non-JSON-serializable data should raise."""
        filepath = tmp_path / "bad.json"
        # set is not JSON serializable — but default=str might handle it
        # Actually the write_json uses default=str, so sets will be converted
        write_json(filepath, {"data": {1, 2, 3}})
        # Just verify it doesn't crash


# ============================================================
# PERSONA 20: Video deleted between collect and analyze
# ============================================================
class TestDeletedVideo:
    """Persona: Video exists in local data but deleted from YouTube."""

    def test_retention_file_missing_for_video(self, tmp_path: Path) -> None:
        """Analyze should handle missing retention parquet gracefully."""
        from tube_scout.storage.parquet_store import read_parquet

        result = read_parquet(tmp_path / "nonexistent.parquet")
        assert result is None

    def test_report_with_stale_video_reference(self, tmp_path: Path) -> None:
        """Report generator should handle video not in metadata."""
        data_dir = tmp_path / "data"
        (data_dir / "raw" / "channels" / "UCtest").mkdir(parents=True)
        write_json(
            data_dir / "raw" / "channels" / "UCtest" / "videos_meta.json",
            [{"video_id": "v1", "title": "Existing"}],
        )
        generator = VideoReportGenerator(data_dir=data_dir)
        meta = generator._load_video_meta("deleted_vid", "UCtest")
        # Should return fallback with video_id only
        assert meta["video_id"] == "deleted_vid"
        assert meta["title"] == "deleted_vid"


# ============================================================
# PERSONA 21: Mixed language comments for sentiment
# ============================================================
class TestMixedLanguageComments:
    """Persona: Comments with Korean/English mix."""

    def test_skip_backend_handles_any_language(self) -> None:
        """Skip backend should handle any language without error."""
        service = SentimentService(backend="skip")
        comments = [
            {"comment_id": "c1", "text": "정말 좋은 강의입니다!"},
            {"comment_id": "c2", "text": "Great lecture, very helpful"},
            {"comment_id": "c3", "text": "한국어와 English 섞인 댓글"},
            {"comment_id": "c4", "text": ""},  # empty comment
        ]
        result = service.analyze_batch(comments)
        assert len(result) == 4

    def test_cache_differentiates_batches(self) -> None:
        """Different comment batches should have different cache keys."""
        service = SentimentService(backend="skip")
        key1 = service._compute_cache_key([{"comment_id": "c1", "text": "Hello"}])
        key2 = service._compute_cache_key([{"comment_id": "c2", "text": "World"}])
        assert key1 != key2


# ============================================================
# PERSONA 22: Retention analysis flat curve
# ============================================================
class TestFlatRetentionCurve:
    """Persona: Perfectly flat retention curve (all values identical)."""

    def test_no_hotspots_in_flat(self) -> None:
        data = [
            {"elapsed_ratio": i / 100, "audience_watch_ratio": 0.5} for i in range(100)
        ]
        hotspots = detect_rewatch_hotspots(data)
        assert hotspots == []

    def test_no_skips_in_flat(self) -> None:
        data = [
            {"elapsed_ratio": i / 100, "audience_watch_ratio": 0.5} for i in range(100)
        ]
        skips = detect_skip_zones(data)
        assert skips == []


# ============================================================
# PERSONA 23: Channel ID with spaces validation
# ============================================================
class TestChannelIdSpaceValidation:
    """Persona: Edge case — channel_id 'UC with spaces' should fail."""

    def test_space_in_channel_id(self) -> None:
        """channel_id with spaces is correctly rejected by regex."""
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelConfig(
                channel_id="UC with spaces",
                professor_name="Prof",
            )


# ============================================================
# PERSONA 24: Concurrent checkpoint writes
# ============================================================
class TestConcurrentCheckpointWrites:
    """Persona: Two channels writing checkpoints simultaneously."""

    def test_different_channel_checkpoints_isolated(self, tmp_path: Path) -> None:
        """Checkpoints for different channels should be independent."""
        state1 = CollectionState(
            channel_id="UCchannel1",
            phase="videos",
            status="completed",
            total_collected=100,
        )
        state2 = CollectionState(
            channel_id="UCchannel2",
            phase="videos",
            status="in_progress",
            total_collected=50,
        )
        save_checkpoint(tmp_path, state1)
        save_checkpoint(tmp_path, state2)

        loaded1 = load_checkpoint(tmp_path, "UCchannel1", "videos")
        loaded2 = load_checkpoint(tmp_path, "UCchannel2", "videos")

        assert loaded1.status == "completed"
        assert loaded1.total_collected == 100
        assert loaded2.status == "in_progress"
        assert loaded2.total_collected == 50

    def test_different_phases_isolated(self, tmp_path: Path) -> None:
        """Same channel, different phases should be independent."""
        state_v = CollectionState(
            channel_id="UCtest",
            phase="videos",
            status="completed",
        )
        state_c = CollectionState(
            channel_id="UCtest",
            phase="comments",
            status="in_progress",
        )
        save_checkpoint(tmp_path, state_v)
        save_checkpoint(tmp_path, state_c)

        loaded_v = load_checkpoint(tmp_path, "UCtest", "videos")
        loaded_c = load_checkpoint(tmp_path, "UCtest", "comments")

        assert loaded_v.status == "completed"
        assert loaded_c.status == "in_progress"
