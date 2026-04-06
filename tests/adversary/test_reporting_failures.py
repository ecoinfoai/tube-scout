"""Adversarial failure case tests for YouTube Reporting API (T093).

Tests error handling for job creation failures, timeouts,
download failures, and CSV parsing errors.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError

from tube_scout.models.analytics import ReportingJob
from tube_scout.services.youtube_reporting import (
    YouTubeReportingService,
    parse_report_csv,
)


@pytest.fixture
def mock_reporting_client() -> MagicMock:
    """Create a mock YouTube Reporting API client."""
    return MagicMock()


@pytest.fixture
def service(mock_reporting_client: MagicMock) -> YouTubeReportingService:
    """Create a YouTubeReportingService with mocked client."""
    return YouTubeReportingService(client=mock_reporting_client)


class TestJobCreationFailures:
    """Persona: API errors during job creation."""

    def test_api_error_returns_clear_message(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """API error on job creation raises with clear error message."""
        resp = httplib2.Response({"status": "403"})
        mock_reporting_client.jobs().create().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "Forbidden: insufficient permissions"}}'
        )
        with pytest.raises(PermissionError, match="Failed to create reporting job"):
            service.create_job("channel_basic_a2")

    def test_server_error_propagates(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """500 server error during job creation propagates as RuntimeError."""
        resp = httplib2.Response({"status": "500"})
        mock_reporting_client.jobs().create().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "Internal error"}}'
        )
        with pytest.raises(RuntimeError, match="API error"):
            service.create_job("channel_basic_a2")

    def test_no_client_configured(self) -> None:
        """Service without client raises ValueError on create_job."""
        svc = YouTubeReportingService(client=None)
        with pytest.raises(ValueError, match="client is not configured"):
            svc.create_job("channel_basic_a2")


class TestJobTimeoutFailures:
    """Persona: Job never becomes ready."""

    def test_timeout_after_max_polls(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """poll_until_ready raises TimeoutError after exhausting max_polls."""
        mock_reporting_client.jobs().reports().list().execute.return_value = {
            "reports": []
        }
        with patch("time.sleep"):
            with pytest.raises(TimeoutError, match="max polls"):
                service.poll_until_ready("job-timeout", max_polls=2, interval=0)

    def test_api_error_during_polling(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """API error during polling propagates immediately."""
        resp = httplib2.Response({"status": "500"})
        mock_reporting_client.jobs().reports().list().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "Internal error"}}'
        )
        with patch("time.sleep"):
            with pytest.raises(HttpError):
                service.poll_until_ready("job-error", max_polls=3, interval=0)


class TestDownloadFailures:
    """Persona: Download URL is broken or fails."""

    def test_download_api_error(
        self,
        service: YouTubeReportingService,
        mock_reporting_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Download failure raises RuntimeError with retry suggestion."""
        resp = httplib2.Response({"status": "404"})
        mock_reporting_client.media().download().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "Not found"}}'
        )
        job = ReportingJob(
            job_id="job-dl-fail",
            report_type_id="channel_basic_a2",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            created_at="2026-04-03T10:00:00Z",
            status="ready",
            download_url="https://youtubereporting.googleapis.com/v1/media/report-bad",
        )
        with pytest.raises(RuntimeError, match="retry"):
            service.download_report(job, output_dir=tmp_path)

    def test_download_empty_response(
        self,
        service: YouTubeReportingService,
        mock_reporting_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Empty download response raises ValueError."""
        mock_reporting_client.media().download().execute.return_value = b""
        job = ReportingJob(
            job_id="job-empty",
            report_type_id="channel_basic_a2",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            created_at="2026-04-03T10:00:00Z",
            status="ready",
            download_url="https://youtubereporting.googleapis.com/v1/media/report-empty",
        )
        with pytest.raises(ValueError, match="Empty"):
            service.download_report(job, output_dir=tmp_path)


class TestCSVParsingFailures:
    """Persona: Downloaded CSV is malformed."""

    def test_empty_csv_file(self, tmp_path: Path) -> None:
        """Parsing empty CSV raises ValueError with details."""
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("")
        with pytest.raises(ValueError, match="empty"):
            parse_report_csv(csv_path)

    def test_header_only_csv(self, tmp_path: Path) -> None:
        """Parsing header-only CSV raises ValueError."""
        csv_path = tmp_path / "header_only.csv"
        csv_path.write_text("date,views,estimatedMinutesWatched\n")
        with pytest.raises(ValueError, match="no data rows"):
            parse_report_csv(csv_path)

    def test_malformed_csv_with_inconsistent_columns(self, tmp_path: Path) -> None:
        """Parsing CSV with inconsistent columns raises ValueError."""
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text(
            "date,views,estimatedMinutesWatched\n"
            "2026-04-01,100\n"  # missing column
            "2026-04-02,120,60.0,extra\n"  # extra column
        )
        with pytest.raises(ValueError, match="malformed"):
            parse_report_csv(csv_path)

    def test_valid_csv_parses_correctly(self, tmp_path: Path) -> None:
        """Valid CSV parses into polars DataFrame."""
        csv_path = tmp_path / "valid.csv"
        csv_path.write_text(
            "date,views,estimatedMinutesWatched\n"
            "2026-04-01,100,50.5\n"
            "2026-04-02,120,60.0\n"
        )
        df = parse_report_csv(csv_path)
        assert len(df) == 2
        assert "date" in df.columns
        assert "views" in df.columns
