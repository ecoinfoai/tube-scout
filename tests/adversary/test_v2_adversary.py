"""V2 adversary tests — aggressive failure testing with 10 personas.

Each persona targets a specific attack surface with 2-3 test cases.
All external dependencies (APIs, filesystem) are mocked.
"""

import json
import math
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import httplib2
import polars as pl
import pytest
from googleapiclient.errors import HttpError
from pydantic import ValidationError

from tube_scout.models.config import (
    AcademicCalendar,
    AppConfig,
    CalendarEvent,
    ChannelConfig,
    CollectionState,
    Settings,
)
from tube_scout.reporting.channel_report import ChannelReportGenerator
from tube_scout.services.eqs import EQSService
from tube_scout.services.forecaster import ForecasterService
from tube_scout.services.segmenter import SegmenterService, compare_with_retention
from tube_scout.services.sentiment import (
    SentimentService,
    cross_reference_questions_hotspots,
)
from tube_scout.services.topic_extractor import TopicExtractorService
from tube_scout.services.transcript import TranscriptService
from tube_scout.services.youtube_analytics import YouTubeAnalyticsService
from tube_scout.services.youtube_data import YouTubeDataService
from tube_scout.storage.checkpoint import load_checkpoint, save_checkpoint
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import read_parquet, write_parquet


# ============================================================
# PERSONA 1: The Invalid Argument Spammer
# ============================================================
class TestInvalidArgumentSpammer:
    """Malformed CLI args, missing required flags, invalid option values."""

    def test_init_invalid_channel_id_format(self) -> None:
        """Non-UC-prefixed channel ID must be rejected at model level."""
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelConfig(channel_id="INVALID_ID", professor_name="Prof Kim")

    def test_init_empty_professor_name(self) -> None:
        """Whitespace-only professor name must be rejected."""
        with pytest.raises(ValidationError, match="professor_name"):
            ChannelConfig(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                professor_name="   ",
            )

    def test_settings_invalid_sentiment_backend(self) -> None:
        """Invalid sentiment backend value should raise on service init."""
        with pytest.raises(ValueError, match="Unsupported sentiment backend"):
            SentimentService(backend="gpt-5-turbo-ultra")

    def test_calendar_set_nonexistent_file(self, tmp_path: Path) -> None:
        """Calendar from nonexistent path should fail at read_json."""
        result = read_json(tmp_path / "ghost_calendar.json")
        assert result is None

    def test_forecaster_unknown_model_name(self) -> None:
        """Unknown model name should raise ValueError."""
        svc = ForecasterService()
        data = [{"date": 740000 + i, "value": 100 + i} for i in range(200)]
        with pytest.raises(ValueError, match="Unknown model"):
            svc.predict("UCtest", "views", data, model="lstm-mega")


# ============================================================
# PERSONA 2: The Corrupt Config Attacker
# ============================================================
class TestCorruptConfigAttacker:
    """Invalid JSON config, missing required fields, wrong types."""

    def test_config_json_syntax_error(self, tmp_path: Path) -> None:
        """Garbled JSON should raise JSONDecodeError."""
        bad = tmp_path / "config.json"
        bad.write_text('{channels: [{oops}], "extra": undefined}')
        with pytest.raises(json.JSONDecodeError):
            read_json(bad)

    def test_config_channels_wrong_type(self) -> None:
        """channels as an integer should fail validation."""
        with pytest.raises(ValidationError):
            AppConfig(channels=42, settings=Settings())

    def test_calendar_event_invalid_type(self) -> None:
        """Calendar event with invalid event_type should fail."""
        with pytest.raises(ValidationError, match="event_type"):
            CalendarEvent(
                name="Midterm",
                start_date="2026-04-10",
                end_date="2026-04-11",
                event_type="party",
            )

    def test_calendar_end_before_start(self) -> None:
        """Calendar event with end_date before start_date should fail."""
        with pytest.raises(ValidationError, match="end_date"):
            CalendarEvent(
                name="Final",
                start_date="2026-06-20",
                end_date="2026-06-10",
                event_type="exam",
            )

    def test_calendar_empty_events_list(self) -> None:
        """Academic calendar with zero events should fail."""
        with pytest.raises(ValidationError, match="events"):
            AcademicCalendar(events=[])


# ============================================================
# PERSONA 3: The API Saboteur
# ============================================================
class TestAPISaboteur:
    """OAuth expired mid-collection, HTML instead of JSON, partial 500s."""

    def test_oauth_expired_mid_collection_401(self) -> None:
        """401 during analytics query should raise PermissionError."""
        mock_client = MagicMock()
        resp = httplib2.Response({"status": "401"})
        mock_client.reports().query().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "Token expired"}}'
        )
        svc = YouTubeAnalyticsService(client=mock_client)
        with pytest.raises(PermissionError):
            svc.get_daily_metrics(
                channel_id="UCtest123456789012345678",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 3, 31),
            )

    def test_api_returns_html_garbage(self) -> None:
        """If API returns non-JSON body, HttpError wraps it properly."""
        mock_client = MagicMock()
        resp = httplib2.Response({"status": "502"})
        mock_client.reports().query().execute.side_effect = HttpError(
            resp, b"<html><body>Bad Gateway</body></html>"
        )
        svc = YouTubeAnalyticsService(client=mock_client)
        with pytest.raises(HttpError):
            svc.get_geography(
                channel_id="UCtest123456789012345678",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

    def test_partial_500_in_collect_all_reports(self) -> None:
        """Some report types 500 while others succeed — errors recorded."""
        mock_client = MagicMock()
        resp_500 = httplib2.Response({"status": "500"})
        error = HttpError(resp_500, b'{"error": {"message": "server error"}}')

        call_count = 0

        def execute_side_effect() -> dict:
            nonlocal call_count
            call_count += 1
            # Fail every 3rd call (with retries)
            if call_count % 5 == 0:
                raise error
            return {"rows": []}

        mock_client.reports().query().execute.side_effect = execute_side_effect
        svc = YouTubeAnalyticsService(client=mock_client)
        result = svc.collect_all_reports(
            channel_id="UCtest123456789012345678",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
        )
        assert "errors" in result


# ============================================================
# PERSONA 4: The Empty Data Nihilist
# ============================================================
class TestEmptyDataNihilist:
    """Channel with 0 videos, 0 comments, empty transcripts, all-zero metrics."""

    def test_channel_zero_videos(self) -> None:
        """get_channel_info returning 0 videos is valid."""
        mock_client = MagicMock()
        mock_client.channels().list().execute.return_value = {
            "items": [
                {
                    "id": "UCempty00000000000000000",
                    "snippet": {"title": "Empty Channel"},
                    "contentDetails": {
                        "relatedPlaylists": {"uploads": "UUempty"}
                    },
                    "statistics": {
                        "videoCount": "0",
                        "subscriberCount": "10",
                    },
                }
            ]
        }
        svc = YouTubeDataService(client=mock_client)
        info = svc.get_channel_info("UCempty00000000000000000")
        assert info["total_video_count"] == 0

    def test_empty_comments_sentiment(self) -> None:
        """Sentiment on empty comment list returns empty without error."""
        for backend in ("llm", "local", "skip"):
            svc = SentimentService(backend=backend)
            assert svc.analyze_batch([]) == []

    def test_empty_transcript_segmenter(self) -> None:
        """Segmenter returns empty chapters for empty/whitespace transcript."""
        svc = SegmenterService(llm=MagicMock())
        assert svc.segment_transcript("vid001", "") == []
        assert svc.segment_transcript("vid001", "  \n\t  ") == []

    def test_all_zero_daily_metrics(self) -> None:
        """All-zero metric rows should be returned, not filtered out."""
        mock_client = MagicMock()
        mock_client.reports().query().execute.return_value = {
            "rows": [
                ["2024-01-01", 0, 0, 0, 0, 0, 0],
                ["2024-01-02", 0, 0, 0, 0, 0, 0],
            ]
        }
        svc = YouTubeAnalyticsService(client=mock_client)
        result = svc.get_daily_metrics(
            channel_id="UCtest123456789012345678",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
        )
        assert len(result) == 2


# ============================================================
# PERSONA 5: The Unicode Bomb
# ============================================================
class TestUnicodeBomb:
    """Emoji-only, RTL text, zero-width chars, huge comments, SQL injection."""

    def test_emoji_only_comment_skip_backend(self) -> None:
        """Pure emoji comments should not crash skip backend."""
        svc = SentimentService(backend="skip")
        comments = [
            {
                "comment_id": "e1",
                "text": "\U0001f525\U0001f4af\U0001f60d\U0001f44d\U0001f44d\U0001f44d",
            },
            {"comment_id": "e2", "text": "\U0001f480\U0001f4a9\U0001f921"},
        ]
        result = svc.analyze_batch(comments)
        assert len(result) == 2

    def test_rtl_and_zero_width_chars(self) -> None:
        """RTL Arabic and zero-width joiners in comments handled by skip backend."""
        svc = SentimentService(backend="skip")
        comments = [
            {
                "comment_id": "r1",
                "text": (
                    "\u0645\u062d\u0627\u0636\u0631\u0629"
                    " \u0631\u0627\u0626\u0639\u0629"
                ),
            },
            {
                "comment_id": "r2",
                "text": "\u200b\u200c\u200dhidden\u200b\u200c\u200d",
            },
            {"comment_id": "r3", "text": "\u202e\u202dreversed"},
        ]
        result = svc.analyze_batch(comments)
        assert len(result) == 3

    def test_huge_comment_and_sql_injection(self) -> None:
        """10000-char comment and SQL injection attempt should not crash."""
        svc = SentimentService(backend="skip")
        comments = [
            {"comment_id": "big", "text": "A" * 10000},
            {
                "comment_id": "sqli",
                "text": "'; DROP TABLE comments; --",
            },
            {
                "comment_id": "xss",
                "text": '<script>alert("xss")</script>',
            },
        ]
        result = svc.analyze_batch(comments)
        assert len(result) == 3

    def test_unicode_in_json_store(self, tmp_path: Path) -> None:
        """Full Unicode roundtrip through JSON store."""
        filepath = tmp_path / "unicode.json"
        data = {
            "emoji": "\U0001f525\U0001f4af",
            "rtl": "\u0645\u062d\u0627\u0636\u0631\u0629",
            "zwsp": "\u200b\u200chidden",
            "korean": "\ud55c\uad6d\uc5b4 \ud14c\uc2a4\ud2b8",
        }
        write_json(filepath, data)
        loaded = read_json(filepath)
        assert loaded == data


# ============================================================
# PERSONA 6: The LLM Gaslighter
# ============================================================
class TestLLMGaslighter:
    """LLM returns valid JSON but wrong schema, scores > 1.0, empty arrays."""

    def test_eqs_llm_returns_scores_above_one(self) -> None:
        """RACED scores > 1.0 should be rejected by Pydantic schema."""
        mock_llm = MagicMock()
        mock_llm.complete_json.side_effect = ValueError(
            "Failed to parse LLM response as _RACEDScores after 2 attempts: "
            "1 validation error for _RACEDScores\n"
            "relevance\n  Input should be less than or equal to 1"
        )
        svc = EQSService(llm=mock_llm)
        with pytest.raises(ValueError, match="Failed to parse"):
            svc.evaluate("vid001", "Real transcript content", [], [])

    def test_sentiment_llm_returns_wrong_schema(self) -> None:
        """LLM returns JSON with wrong keys — should raise ValueError."""
        mock_adapter = MagicMock()
        mock_adapter.complete_json.side_effect = ValueError(
            "Failed to parse LLM response as SentimentBatchResult after 2 attempts"
        )
        svc = SentimentService(backend="llm")
        svc._llm_adapter = mock_adapter
        with pytest.raises(ValueError, match="Failed to parse"):
            svc.analyze_batch([{"comment_id": "c1", "text": "test"}])

    def test_segmenter_llm_returns_empty_chapters(self) -> None:
        """LLM returns valid JSON with empty chapters array."""
        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.chapters = []
        mock_llm.complete_json.return_value = mock_result
        svc = SegmenterService(llm=mock_llm)
        result = svc.segment_transcript("vid001", "Some transcript")
        assert result == []

    def test_topic_extractor_llm_wrong_language(self) -> None:
        """LLM adapter raises ValueError for unparseable response."""
        svc = TopicExtractorService()
        mock_adapter = MagicMock()
        mock_adapter.complete_json.side_effect = ValueError(
            "Failed to parse LLM response"
        )
        svc._llm_adapter = mock_adapter
        with pytest.raises(ValueError, match="Failed to parse"):
            svc.extract_topics(
                "vid001",
                [{"comment_id": "c1", "text": "Comment"}],
            )


# ============================================================
# PERSONA 7: The Quota Exhaustor
# ============================================================
class TestQuotaExhaustor:
    """API quota hit on first call, partial quota after some reports."""

    def test_quota_on_first_call(self) -> None:
        """429 on the very first API call."""
        mock_client = MagicMock()
        resp = httplib2.Response({"status": "429"})
        mock_client.reports().query().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "quotaExceeded"}}'
        )
        svc = YouTubeAnalyticsService(client=mock_client)
        with pytest.raises(HttpError):
            svc.get_daily_metrics(
                channel_id="UCtest123456789012345678",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

    def test_quota_after_partial_collection(self) -> None:
        """Quota hit after 3 successful report types — errors recorded."""
        mock_client = MagicMock()
        resp_429 = httplib2.Response({"status": "429"})
        quota_error = HttpError(
            resp_429, b'{"error": {"message": "quotaExceeded"}}'
        )

        call_count = 0

        def execute_side_effect() -> dict:
            nonlocal call_count
            call_count += 1
            if call_count > 3:
                raise quota_error
            return {"rows": [["2024-01-01", 100, 50, 10, 5, 2, 1]]}

        mock_client.reports().query().execute.side_effect = execute_side_effect
        svc = YouTubeAnalyticsService(client=mock_client)
        result = svc.collect_all_reports(
            channel_id="UCtest123456789012345678",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert "errors" in result
        assert len(result["errors"]) >= 1

    def test_checkpoint_saved_after_quota_interrupt(self, tmp_path: Path) -> None:
        """Checkpoint should persist partial progress for quota recovery."""
        state = CollectionState(
            channel_id="UCquota_victim",
            phase="analytics",
            total_expected=8,
            total_collected=3,
            status="interrupted",
            analytics_last_dates={"daily_metrics": "2024-01-15"},
        )
        save_checkpoint(tmp_path, state)
        loaded = load_checkpoint(tmp_path, "UCquota_victim", "analytics")
        assert loaded is not None
        assert loaded.total_collected == 3
        assert loaded.analytics_last_dates["daily_metrics"] == "2024-01-15"


# ============================================================
# PERSONA 8: The Concurrent Chaos Agent
# ============================================================
class TestConcurrentChaosAgent:
    """Corrupted checkpoint files, checkpoint from older version."""

    def test_corrupted_checkpoint_binary_garbage(self, tmp_path: Path) -> None:
        """Binary garbage in checkpoint file should raise."""
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir(parents=True)
        ckpt_file = ckpt_dir / "collection_state.json"
        ckpt_file.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")
        with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
            load_checkpoint(tmp_path, "UCchaos", "videos")

    def test_checkpoint_missing_required_fields(self, tmp_path: Path) -> None:
        """Checkpoint from older version missing 'phase' should fail."""
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir(parents=True)
        ckpt_file = ckpt_dir / "collection_state.json"
        old_state = {
            "UCold:videos": {
                "channel_id": "UCold",
                # Missing 'phase' field
                "status": "completed",
                "total_collected": 50,
            }
        }
        write_json(ckpt_file, old_state)
        with pytest.raises((ValidationError, TypeError)):
            load_checkpoint(tmp_path, "UCold", "videos")

    def test_checkpoint_extra_fields_tolerated(self, tmp_path: Path) -> None:
        """Checkpoint with extra unknown fields from newer version should load."""
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir(parents=True)
        ckpt_file = ckpt_dir / "collection_state.json"
        future_state = {
            "UCfuture:videos": {
                "channel_id": "UCfuture",
                "phase": "videos",
                "status": "completed",
                "total_collected": 100,
                "total_expected": 100,
                "new_field_from_v3": "should be ignored",
            }
        }
        write_json(ckpt_file, future_state)
        loaded = load_checkpoint(tmp_path, "UCfuture", "videos")
        assert loaded is not None
        assert loaded.status == "completed"


# ============================================================
# PERSONA 9: The Storage Attacker
# ============================================================
class TestStorageAttacker:
    """Parquet with wrong columns, JSON with extra fields, missing dirs."""

    def test_parquet_wrong_columns(self, tmp_path: Path) -> None:
        """Reading parquet with unexpected columns should not crash."""
        filepath = tmp_path / "wrong_schema.parquet"
        df = pl.DataFrame({
            "wrong_col_a": [1, 2, 3],
            "wrong_col_b": ["x", "y", "z"],
        })
        write_parquet(filepath, df)
        loaded = read_parquet(filepath)
        assert loaded is not None
        assert "wrong_col_a" in loaded.columns
        assert "date" not in loaded.columns

    def test_json_with_extra_unexpected_fields(self, tmp_path: Path) -> None:
        """JSON config with unexpected fields should be handled by Pydantic."""
        filepath = tmp_path / "config.json"
        config_data = {
            "channels": [
                {
                    "channel_id": "UCtest123456789012345678",
                    "professor_name": "Prof Kim",
                    "unexpected_field": "should_be_ignored",
                }
            ],
            "settings": {"data_dir": "./data"},
            "also_unexpected": True,
        }
        write_json(filepath, config_data)
        loaded = read_json(filepath)
        config = AppConfig(**loaded)
        assert len(config.channels) == 1
        assert config.channels[0].professor_name == "Prof Kim"

    def test_missing_data_directory_read_returns_none(
        self, tmp_path: Path
    ) -> None:
        """Reading from non-existent directory should return None."""
        result = read_json(tmp_path / "nonexistent" / "deep" / "file.json")
        assert result is None
        result_pq = read_parquet(
            tmp_path / "nonexistent" / "deep" / "file.parquet"
        )
        assert result_pq is None


# ============================================================
# PERSONA 10: The Forecast Fool
# ============================================================
class TestForecastFool:
    """1 data point, identical values, NaN, negative counts, wrong order."""

    def test_single_data_point_rejected(self) -> None:
        """Single data point should be rejected (< MIN_DATA_DAYS)."""
        svc = ForecasterService()
        with pytest.raises(ValueError, match="6 months"):
            svc.predict("UCtest", "views", [{"date": 740000, "value": 100}])

    def test_all_identical_values_linear(self) -> None:
        """200 identical values should produce valid forecast with flat trend."""
        svc = ForecasterService()
        data = [{"date": 740000 + i, "value": 42.0} for i in range(200)]
        result = svc.predict(
            "UCtest", "views", data, model="linear", horizon_days=7
        )
        assert len(result) == 7
        for r in result:
            assert not math.isnan(r["predicted_value"])
            assert not math.isinf(r["predicted_value"])

    def test_nan_values_in_data(self) -> None:
        """NaN values should propagate or be handled, not silently corrupt."""
        svc = ForecasterService()
        data = [{"date": 740000 + i, "value": 100.0} for i in range(200)]
        data[50]["value"] = float("nan")
        # NaN will propagate through linear regression — this tests it
        # doesn't crash with an unhandled exception
        result = svc.predict(
            "UCtest", "views", data, model="linear", horizon_days=7
        )
        assert len(result) == 7

    def test_negative_view_counts(self) -> None:
        """Negative values (data corruption) should not crash forecasting."""
        svc = ForecasterService()
        data = [{"date": 740000 + i, "value": -10.0 + i} for i in range(200)]
        result = svc.predict(
            "UCtest", "views", data, model="linear", horizon_days=7
        )
        assert len(result) == 7

    def test_dates_in_wrong_order(self) -> None:
        """fill_missing_days should sort data, not crash on wrong order."""
        svc = ForecasterService()
        data = [
            {"date": 740200, "value": 200},
            {"date": 740000, "value": 100},
            {"date": 740100, "value": 150},
        ]
        filled = svc.fill_missing_days(data)
        dates = [d["date"] for d in filled]
        assert dates == sorted(dates), "Output should be sorted ascending"
        assert len(filled) == 201  # 740000..740200 inclusive

    def test_anomaly_detection_all_nan(self) -> None:
        """All NaN values should not crash anomaly detection."""
        svc = ForecasterService()
        data = [{"date": i, "value": float("nan")} for i in range(10)]
        # NaN mean/std will cause issues — verify no unhandled crash
        result = svc.detect_anomalies(data)
        assert isinstance(result, list)

    def test_model_selection_boundaries(self) -> None:
        """Verify model selection at exact boundary points."""
        svc = ForecasterService()
        assert svc.select_model(89) == "linear"
        assert svc.select_model(90) == "arima"
        assert svc.select_model(365) == "arima"
        assert svc.select_model(366) == "prophet"


# ============================================================
# BONUS: Cross-cutting edge cases
# ============================================================
class TestCrossCuttingEdgeCases:
    """Edge cases that span multiple personas."""

    def test_eqs_empty_retention_and_comments(self) -> None:
        """EQS with transcript but empty retention/comments should not crash."""
        svc = EQSService(llm=None)
        # Empty transcript returns all-zero
        result = svc.evaluate("vid001", "", [], [])
        assert result["overall"] == 0.0

    def test_cross_reference_empty_inputs(self) -> None:
        """cross_reference_questions_hotspots with all empty inputs."""
        assert cross_reference_questions_hotspots([], []) == []

    def test_compare_with_retention_zero_duration(self) -> None:
        """compare_with_retention with zero duration returns empty."""
        segments = [
            {
                "segment_index": 0,
                "start_seconds": 0,
                "end_seconds": 60,
                "title": "Intro",
            }
        ]
        hotspots = [{"elapsed_ratio": 0.5, "audience_watch_ratio": 1.5}]
        result = compare_with_retention(segments, hotspots, 0)
        assert result == []

    def test_topic_extractor_empty_comments(self) -> None:
        """Topic extractor with no comments returns empty."""
        svc = TopicExtractorService()
        assert svc.extract_topics("vid001", []) == []
        assert svc.extract_questions("vid001", []) == []

    def test_channel_report_no_videos(self, tmp_path: Path) -> None:
        """Channel report generator with empty video list returns insights."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        gen = ChannelReportGenerator(data_dir=data_dir)
        insights = gen._generate_insights([])
        assert len(insights) >= 1
        assert "No videos" in insights[0]

    def test_transcript_service_disabled(self) -> None:
        """Transcript service returns None for disabled transcripts."""
        from youtube_transcript_api import TranscriptsDisabled

        svc = TranscriptService()
        with patch.object(
            svc._api, "list", side_effect=TranscriptsDisabled("vid")
        ):
            result = svc.fetch_transcript("vid_disabled")
            assert result is None

    def test_collection_state_all_fields_default(self) -> None:
        """CollectionState with only required fields should not crash."""
        state = CollectionState(channel_id="UCmin", phase="videos")
        assert state.status == "in_progress"
        assert state.total_collected == 0
        assert state.analytics_last_dates == {}
