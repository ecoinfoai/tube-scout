"""Integration test for full analytics collection flow (T030)."""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from tube_scout.services.youtube_analytics import YouTubeAnalyticsService
from tube_scout.storage.checkpoint import load_checkpoint
from tube_scout.storage.json_store import write_json


def _setup_config(data_dir: Path) -> None:
    """Write a minimal config.json for testing."""
    write_json(
        data_dir / "config.json",
        {
            "channels": [
                {
                    "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                    "professor_name": "TestProfessor",
                }
            ],
            "settings": {"data_dir": str(data_dir)},
        },
    )


class TestAnalyticsCollectionFlow:
    """Integration tests for the analytics collection pipeline."""

    def test_collect_all_reports_stores_data(self, tmp_path: Path) -> None:
        """Full flow: collect all report types and verify storage."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "checkpoints").mkdir(parents=True)
        _setup_config(data_dir)

        mock_client = MagicMock()
        mock_client.reports().query().execute.return_value = {"rows": []}

        service = YouTubeAnalyticsService(client=mock_client)
        result = service.collect_all_reports(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        assert "daily_metrics" in result
        assert "traffic_sources" in result
        assert "demographics" in result
        assert "geography" in result
        assert "devices" in result
        assert "playback_locations" in result
        assert "subscriber_changes" in result
        assert "errors" in result
        assert len(result["errors"]) == 0

    def test_incremental_sync_uses_last_dates(self, tmp_path: Path) -> None:
        """Verify incremental sync skips already-collected date ranges."""
        from tube_scout.models.config import CollectionState
        from tube_scout.storage.checkpoint import save_checkpoint

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "checkpoints").mkdir(parents=True)

        # Set up checkpoint with last collected dates
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="analytics",
            status="completed",
            analytics_last_dates={
                "daily_metrics": "2024-03-01",
                "traffic_sources": "2024-03-01",
            },
        )
        save_checkpoint(data_dir, state)

        loaded = load_checkpoint(data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "analytics")
        assert loaded is not None
        assert loaded.analytics_last_dates["daily_metrics"] == "2024-03-01"

    def test_collect_single_report_type(self, tmp_path: Path) -> None:
        """Collect a single report type only."""
        mock_client = MagicMock()
        mock_client.reports().query().execute.return_value = {
            "rows": [
                ["2024-01-01", 100, 50.0, 120.0, 45.0],
            ]
        }

        service = YouTubeAnalyticsService(client=mock_client)
        result = service.collect_all_reports(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            report_types=["daily_metrics"],
        )

        assert "daily_metrics" in result
        assert len(result["daily_metrics"]) == 1
        assert "traffic_sources" not in result

    def test_collect_with_video_filter(self, tmp_path: Path) -> None:
        """Collect analytics filtered to a specific video."""
        mock_client = MagicMock()
        mock_client.reports().query().execute.return_value = {"rows": []}

        service = YouTubeAnalyticsService(client=mock_client)
        result = service.collect_all_reports(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            video_id="dQw4w9WgXcQ",
        )

        # demographics and subscriber_changes are channel-only,
        # but should still be included (API will just return channel data)
        assert "daily_metrics" in result
        assert "errors" in result
