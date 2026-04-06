"""Layer 3 integration tests: Data flow path verification.

Tests 5 core data flow paths through the system:
  Path A: collect videos -> json_store -> youtube_data -> models/video -> storage
  Path B: collect retention -> youtube_analytics -> models/analytics -> parquet_store
  Path C: collect transcripts -> transcript service -> json_store
  Path D: analyze -> forecaster/sentiment/eqs -> models -> reporting -> HTML/Excel
  Path E: collect all -> [A+B+C+D] sequential -> checkpoint -> resume
"""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl

from tube_scout.models.analytics import AnalyticsReport
from tube_scout.models.config import CollectionState
from tube_scout.models.video import Forecast, Video, ViewingPattern
from tube_scout.services.forecaster import ForecasterService
from tube_scout.services.transcript import TranscriptService
from tube_scout.services.youtube_analytics import YouTubeAnalyticsService
from tube_scout.services.youtube_data import YouTubeDataService
from tube_scout.storage.checkpoint import (
    is_stage_complete,
    load_checkpoint,
    mark_stage_complete,
    save_checkpoint,
)
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import read_parquet, write_parquet

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHANNEL_ID = "UCxxxxxxxxxxxxxxxxxxxxxx"


def _make_video_dict(video_id: str, title: str, pub: str) -> dict[str, Any]:
    """Create a minimal video metadata dict."""
    return {
        "video_id": video_id,
        "title": title,
        "published_at": pub,
    }


def _make_video_detail(video_id: str) -> dict[str, Any]:
    """Create a video detail response dict."""
    return {
        "duration_seconds": 600,
        "view_count": 100,
        "like_count": 10,
        "comment_count": 2,
        "description": "Test desc",
        "tags": ["lecture"],
        "category_id": "27",
        "thumbnail_url": "https://example.com/thumb.jpg",
        "default_language": "ko",
        "privacy_status": "public",
        "topic_categories": [],
        "has_captions": True,
    }


def _mock_yt_client(
    channel_items: list[dict] | None = None,
    playlist_items: list[dict] | None = None,
    video_items: list[dict] | None = None,
) -> MagicMock:
    """Build a mock YouTube Data API client."""
    client = MagicMock()

    # channels().list().execute()
    channel_resp = {"items": channel_items or []}
    client.channels().list.return_value.execute.return_value = channel_resp

    # playlistItems().list().execute()
    playlist_resp = {"items": playlist_items or []}
    client.playlistItems().list.return_value.execute.return_value = playlist_resp

    # videos().list().execute()
    video_resp = {"items": video_items or []}
    client.videos().list.return_value.execute.return_value = video_resp

    return client


def _mock_analytics_client(rows: list[list[Any]] | None = None) -> MagicMock:
    """Build a mock YouTube Analytics API client."""
    client = MagicMock()
    resp = {"rows": rows or []}
    client.reports().query.return_value.execute.return_value = resp
    return client


# ===========================================================================
# Path A: collect videos -> json_store -> youtube_data -> models/video -> storage
# ===========================================================================


class TestPathAVideoCollection:
    """Verify the video collection data flow end-to-end."""

    def test_collect_videos_store_and_reload(self, tmp_path: Path) -> None:
        """Videos collected via API -> stored as JSON -> loaded as Video models."""
        # 1) Mock API client returns videos
        playlist_items = [
            {
                "snippet": {
                    "resourceId": {"videoId": f"vid{i:03d}"},
                    "title": f"홍길동 2024 해부학 {i}주차 1차시",
                    "publishedAt": f"2024-01-{i + 1:02d}T00:00:00Z",
                }
            }
            for i in range(1, 4)
        ]
        video_items = [
            {
                "id": f"vid{i:03d}",
                "snippet": {
                    "title": f"홍길동 2024 해부학 {i}주차 1차시",
                    "description": "lecture",
                    "tags": ["anatomy"],
                    "categoryId": "27",
                    "thumbnails": {"default": {"url": "http://example.com"}},
                    "defaultLanguage": "ko",
                },
                "contentDetails": {"duration": "PT10M0S", "caption": "true"},
                "statistics": {
                    "viewCount": "50",
                    "likeCount": "5",
                    "commentCount": "1",
                },
                "status": {"privacyStatus": "public"},
                "topicDetails": {"topicCategories": []},
            }
            for i in range(1, 4)
        ]

        client = _mock_yt_client(
            playlist_items=playlist_items,
            video_items=video_items,
        )
        svc = YouTubeDataService(client)

        # 2) List videos
        raw_videos = svc.list_all_videos("UUxxxxxxxxxxxxxxxxxxxxxx")
        assert len(raw_videos) == 3

        # 3) Get details
        ids = [v["video_id"] for v in raw_videos]
        details = svc.get_video_details(ids)
        assert len(details) == 3

        # 4) Store as JSON
        data_dir = tmp_path / "data"
        videos_path = data_dir / "channels" / CHANNEL_ID / "videos_meta.json"
        combined = []
        for rv in raw_videos:
            vid_id = rv["video_id"]
            d = details.get(vid_id, {})
            combined.append(
                {
                    "video_id": vid_id,
                    "channel_id": CHANNEL_ID,
                    "title": rv["title"],
                    "published_at": rv["published_at"],
                    **d,
                }
            )
        write_json(videos_path, combined)

        # 5) Reload and validate as Video models
        loaded = read_json(videos_path)
        assert loaded is not None
        assert len(loaded) == 3
        for item in loaded:
            video = Video(**item)
            assert video.video_id.startswith("vid")
            assert video.channel_id == CHANNEL_ID
            assert video.duration_seconds == 600

    def test_detect_new_videos_deduplication(self) -> None:
        """detect_new_videos correctly identifies only new entries."""
        client = _mock_yt_client()
        svc = YouTubeDataService(client)

        api_videos = [
            _make_video_dict("vid001", "Lec 1", "2024-01-01T00:00:00Z"),
            _make_video_dict("vid002", "Lec 2", "2024-01-02T00:00:00Z"),
            _make_video_dict("vid003", "Lec 3", "2024-01-03T00:00:00Z"),
        ]
        existing = {"vid001", "vid002"}

        new = svc.detect_new_videos(api_videos, existing)
        assert len(new) == 1
        assert new[0]["video_id"] == "vid003"

    def test_json_store_roundtrip_atomicity(self, tmp_path: Path) -> None:
        """JSON store write -> read preserves data faithfully."""
        path = tmp_path / "test.json"
        data = {
            "videos": [
                {"video_id": "v1", "title": "한국어 제목", "count": 0},
            ]
        }
        write_json(path, data)
        loaded = read_json(path)
        assert loaded == data

    def test_video_model_roundtrip(self) -> None:
        """Video model serializes and deserializes correctly."""
        v = Video(
            video_id="vid001",
            channel_id=CHANNEL_ID,
            title="테스트 강의",
            published_at=datetime(2024, 1, 1, tzinfo=UTC),
            duration_seconds=600,
            view_count=100,
        )
        dumped = v.model_dump(mode="json")
        restored = Video(**dumped)
        assert restored.video_id == v.video_id
        assert restored.duration_seconds == v.duration_seconds


# ===========================================================================
# Path B: collect retention -> youtube_analytics -> models/analytics -> parquet
# ===========================================================================


class TestPathBRetentionCollection:
    """Verify the retention/analytics data flow end-to-end."""

    def test_retention_collect_to_parquet(self, tmp_path: Path) -> None:
        """Retention data from Analytics API -> ViewingPattern -> Parquet."""
        rows = [
            [0.0, 1.0, 1.0],
            [0.25, 0.8, 0.9],
            [0.5, 0.6, 0.7],
            [0.75, 0.4, 0.5],
            [1.0, 0.2, 0.3],
        ]
        client = _mock_analytics_client(rows)
        svc = YouTubeAnalyticsService(client=client)
        data = svc.get_retention_data("vid001")

        assert len(data) == 5
        assert data[0]["elapsed_ratio"] == 0.0

        # Convert to ViewingPattern models
        patterns = [ViewingPattern(video_id="vid001", **row) for row in data]
        assert all(p.video_id == "vid001" for p in patterns)

        # Store as Parquet
        df = pl.DataFrame([p.model_dump() for p in patterns])
        parquet_path = tmp_path / "retention" / "vid001.parquet"
        write_parquet(parquet_path, df)

        # Reload and verify
        loaded = read_parquet(parquet_path)
        assert loaded is not None
        assert loaded.shape[0] == 5
        assert "elapsed_ratio" in loaded.columns

    def test_daily_metrics_to_analytics_report(self) -> None:
        """Daily metrics API -> AnalyticsReport model round-trip."""
        rows = [
            ["2024-01-01", 100, 500.0, 300.0, 75.0],
            ["2024-01-02", 120, 600.0, 310.0, 78.0],
        ]
        client = _mock_analytics_client(rows)
        svc = YouTubeAnalyticsService(client=client)
        data = svc.get_daily_metrics(
            channel_id=CHANNEL_ID,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
        )

        assert len(data) == 2
        assert data[0]["views"] == 100

        # Wrap in AnalyticsReport
        report = AnalyticsReport(
            report_type="daily_metrics",
            channel_id=CHANNEL_ID,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            rows=data,
        )
        assert report.report_type == "daily_metrics"
        assert len(report.rows) == 2

    def test_collect_all_reports_aggregation(self) -> None:
        """collect_all_reports aggregates multiple report types."""
        rows = [
            ["2024-01-01", 100, 500.0, 300.0, 75.0],
        ]
        client = _mock_analytics_client(rows)
        svc = YouTubeAnalyticsService(client=client)
        result = svc.collect_all_reports(
            channel_id=CHANNEL_ID,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            report_types=["daily_metrics"],
        )

        assert "daily_metrics" in result
        assert "errors" in result
        assert len(result["errors"]) == 0


# ===========================================================================
# Path C: collect transcripts -> transcript service -> json_store
# ===========================================================================


class TestPathCTranscriptCollection:
    """Verify the transcript collection data flow end-to-end."""

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_transcript_fetch_store_reload(
        self, mock_api_cls: MagicMock, tmp_path: Path
    ) -> None:
        """Transcript fetched -> stored JSON -> reloaded correctly."""
        # Setup mock
        mock_api = mock_api_cls.return_value
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"text": "안녕하세요", "start": 0.0, "duration": 3.0},
            {"text": "오늘 강의는", "start": 3.0, "duration": 2.5},
        ]
        mock_list = MagicMock()
        mock_list.find_manually_created_transcript.return_value = mock_transcript
        mock_api.list.return_value = mock_list

        svc = TranscriptService(languages=["ko", "en"])
        result = svc.fetch_transcript("vid001")

        assert result is not None
        assert result["transcript_type"] == "manual"
        assert len(result["segments"]) == 2

        # Store
        transcript_path = tmp_path / "transcripts" / "vid001.json"
        write_json(transcript_path, result)

        # Reload
        loaded = read_json(transcript_path)
        assert loaded is not None
        assert loaded["video_id"] == "vid001"
        assert len(loaded["segments"]) == 2

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_transcript_none_on_disabled(self, mock_api_cls: MagicMock) -> None:
        """TranscriptsDisabled -> returns None gracefully."""
        from youtube_transcript_api import TranscriptsDisabled

        mock_api = mock_api_cls.return_value
        mock_api.list.side_effect = TranscriptsDisabled("vid001")

        svc = TranscriptService()
        result = svc.fetch_transcript("vid001")
        assert result is None

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_transcript_auto_fallback(self, mock_api_cls: MagicMock) -> None:
        """Manual not found -> falls back to auto-generated transcript."""
        from youtube_transcript_api import NoTranscriptFound

        mock_api = mock_api_cls.return_value
        mock_list = MagicMock()

        # Manual raises NoTranscriptFound
        mock_list.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "vid001", ["ko"], None
        )
        # Auto succeeds
        mock_auto = MagicMock()
        mock_auto.fetch.return_value = [
            {"text": "자동 생성 자막", "start": 0.0, "duration": 2.0},
        ]
        mock_list.find_generated_transcript.return_value = mock_auto
        mock_api.list.return_value = mock_list

        svc = TranscriptService()
        result = svc.fetch_transcript("vid001")
        assert result is not None
        assert result["transcript_type"] == "auto_generated"


# ===========================================================================
# Path D: analyze -> forecaster/sentiment/eqs -> models -> reporting
# ===========================================================================


class TestPathDAnalysisPipeline:
    """Verify the analysis data flow: forecaster -> models -> reporting."""

    def test_forecaster_linear_to_forecast_model(self) -> None:
        """Forecaster predict -> Forecast model validation."""
        svc = ForecasterService()
        base_date = date(2024, 1, 1).toordinal()
        historical = [
            {"date": base_date + i, "value": float(100 + i * 2)} for i in range(200)
        ]

        results = svc.predict(
            CHANNEL_ID,
            "views",
            historical,
            horizon_days=7,
            model="linear",
        )

        assert len(results) == 7
        for r in results:
            f = Forecast(
                channel_id=r["channel_id"],
                metric_name=r["metric_name"],
                date=r["date"],
                predicted_value=r["predicted_value"],
                lower_bound=r["lower_bound"],
                upper_bound=r["upper_bound"],
            )
            assert f.channel_id == CHANNEL_ID
            assert f.lower_bound <= f.predicted_value <= f.upper_bound

    def test_anomaly_detection_flow(self) -> None:
        """Anomaly detection produces correct is_anomaly flags."""
        svc = ForecasterService()
        data = [{"date": i, "value": 100.0} for i in range(50)]
        # Inject an anomaly
        data[25]["value"] = 10000.0

        results = svc.detect_anomalies(data, threshold_sigma=3.0)
        assert len(results) == 50
        anomalies = [r for r in results if r["is_anomaly"]]
        assert len(anomalies) >= 1
        assert anomalies[0]["value"] == 10000.0

    def test_eqs_empty_transcript_returns_zeros(self) -> None:
        """EQS with empty transcript returns all-zero scores."""
        from tube_scout.services.eqs import EQSService

        svc = EQSService(llm=None)
        result = svc.evaluate("vid001", "", [], [])
        assert result["overall"] == 0.0
        assert result["relevance"] == 0.0

    def test_department_report_generation(self, tmp_path: Path) -> None:
        """Department report generation with parsed titles + videos."""
        from tube_scout.models.parsed_title import ParsedTitle
        from tube_scout.reporting.department_report import DepartmentReportGenerator

        gen = DepartmentReportGenerator()

        titles = [
            ParsedTitle(
                video_id=f"vid{i:03d}",
                original_title=f"홍길동 2024 해부학 {i}주차 1차시",
                professor=["홍길동"],
                course="해부학",
                year=2024,
                semester=1,
                week=i,
                session=1,
            )
            for i in range(1, 5)
        ]
        videos = [
            Video(
                video_id=f"vid{i:03d}",
                channel_id=CHANNEL_ID,
                title=f"홍길동 2024 해부학 {i}주차 1차시",
                published_at=datetime(2024, 1, i, tzinfo=UTC),
                duration_seconds=600,
                view_count=100,
            )
            for i in range(1, 5)
        ]

        overview = gen.compute_overview(titles, videos, CHANNEL_ID, "테스트학과")
        assert overview.total_videos == 4
        assert overview.total_professors == 1

        details = gen.compute_professor_details(titles, videos)
        assert len(details) == 1
        assert details[0].professor_name == "홍길동"

        compliance = gen.compute_compliance(titles, videos)
        assert len(compliance) == 1

    def test_excel_export_korean_encoding(self, tmp_path: Path) -> None:
        """Excel export handles Korean text correctly."""
        from tube_scout.models.report import (
            ComplianceMatrix,
            DepartmentOverview,
            ProfessorDetail,
        )
        from tube_scout.reporting.excel_export import ExcelExporter

        overview = DepartmentOverview(
            channel_id=CHANNEL_ID,
            channel_name="간호학과",
            total_videos=10,
        )
        prof = ProfessorDetail(
            professor_name="김교수",
            video_count=5,
            courses=["기초간호학", "해부학"],
        )
        compliance = ComplianceMatrix(
            professor_name="김교수",
            week_statuses={i: "uploaded" for i in range(1, 17)},
            upload_deadline_compliance=1.0,
        )

        exporter = ExcelExporter()
        output = tmp_path / "report.xlsx"
        result = exporter.export(overview, [prof], [compliance], output)
        assert result.exists()
        assert result.stat().st_size > 0

        # Verify Korean content is readable
        import openpyxl

        wb = openpyxl.load_workbook(str(result))
        ws_overview = wb["개요"]
        assert ws_overview.cell(row=2, column=2).value == CHANNEL_ID


# ===========================================================================
# Path E: collect all -> checkpoint -> resume
# ===========================================================================


class TestPathECollectAllCheckpoint:
    """Verify the collect-all pipeline with checkpoint/resume."""

    def test_checkpoint_save_load_roundtrip(self, tmp_path: Path) -> None:
        """Checkpoint save -> load preserves state faithfully."""
        state = CollectionState(
            channel_id=CHANNEL_ID,
            phase="videos",
            last_page_token="TOKEN123",
            total_expected=100,
            total_collected=50,
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            status="in_progress",
        )
        save_checkpoint(tmp_path, state)

        loaded = load_checkpoint(tmp_path, CHANNEL_ID, "videos")
        assert loaded is not None
        assert loaded.last_page_token == "TOKEN123"
        assert loaded.total_collected == 50
        assert loaded.status == "in_progress"

    def test_stage_complete_lifecycle(self, tmp_path: Path) -> None:
        """Mark stage complete -> verify -> skip on resume."""
        assert not is_stage_complete(tmp_path, CHANNEL_ID, "videos")

        mark_stage_complete(tmp_path, CHANNEL_ID, "videos")
        assert is_stage_complete(tmp_path, CHANNEL_ID, "videos")

        # Other stages remain incomplete
        assert not is_stage_complete(tmp_path, CHANNEL_ID, "retention")
        assert not is_stage_complete(tmp_path, CHANNEL_ID, "transcripts")

    def test_multi_stage_checkpoint_independence(self, tmp_path: Path) -> None:
        """Multiple stages maintain independent checkpoints."""
        stages = ["videos", "retention", "transcripts", "analytics"]

        for stage in stages[:2]:
            mark_stage_complete(tmp_path, CHANNEL_ID, stage)

        assert is_stage_complete(tmp_path, CHANNEL_ID, "videos")
        assert is_stage_complete(tmp_path, CHANNEL_ID, "retention")
        assert not is_stage_complete(tmp_path, CHANNEL_ID, "transcripts")
        assert not is_stage_complete(tmp_path, CHANNEL_ID, "analytics")

    def test_checkpoint_resume_preserves_partial_data(self, tmp_path: Path) -> None:
        """Partial collection state is preserved for resume."""
        # Simulate partial collection
        state = CollectionState(
            channel_id=CHANNEL_ID,
            phase="videos",
            last_page_token="PAGE2",
            total_expected=200,
            total_collected=100,
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        save_checkpoint(tmp_path, state)

        # Simulate "resume": load and verify we can continue
        resumed = load_checkpoint(tmp_path, CHANNEL_ID, "videos")
        assert resumed is not None
        assert resumed.last_page_token == "PAGE2"
        assert resumed.total_collected == 100
        assert not resumed.stage_completed

    def test_collect_all_sequential_checkpoint_flow(self, tmp_path: Path) -> None:
        """Simulate collect-all: stages run sequentially, checkpoint each."""
        stages = ["videos", "retention", "transcripts"]

        for stage in stages:
            # Simulate stage execution
            if not is_stage_complete(tmp_path, CHANNEL_ID, stage):
                # "Do work" (mocked)
                mark_stage_complete(tmp_path, CHANNEL_ID, stage)

        # All should be complete
        for stage in stages:
            assert is_stage_complete(tmp_path, CHANNEL_ID, stage)
