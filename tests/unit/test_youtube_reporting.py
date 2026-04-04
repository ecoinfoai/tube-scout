"""Tests for YouTubeReportingService (T092).

Tests the reporting job lifecycle: list types, create job,
check status, download report, and full lifecycle.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tube_scout.models.analytics import ReportingJob
from tube_scout.services.youtube_reporting import YouTubeReportingService


@pytest.fixture
def mock_reporting_client() -> MagicMock:
    """Create a mock YouTube Reporting API client."""
    return MagicMock()


@pytest.fixture
def service(mock_reporting_client: MagicMock) -> YouTubeReportingService:
    """Create a YouTubeReportingService with mocked client."""
    return YouTubeReportingService(client=mock_reporting_client)


class TestListReportTypes:
    """Tests for list_report_types method."""

    def test_returns_available_types(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """list_report_types returns available report types from API."""
        mock_reporting_client.reportTypes().list().execute.return_value = {
            "reportTypes": [
                {"id": "channel_basic_a2", "name": "Channel Basic"},
                {"id": "channel_demographics_a1", "name": "Channel Demographics"},
            ]
        }
        result = service.list_report_types()
        assert len(result) == 2
        assert result[0]["id"] == "channel_basic_a2"
        assert result[1]["id"] == "channel_demographics_a1"

    def test_returns_empty_list_when_no_types(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """list_report_types returns empty list when API returns no types."""
        mock_reporting_client.reportTypes().list().execute.return_value = {}
        result = service.list_report_types()
        assert result == []


class TestCreateJob:
    """Tests for create_job method."""

    def test_creates_job_and_returns_model(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """create_job sends correct request and returns ReportingJob."""
        mock_reporting_client.jobs().create().execute.return_value = {
            "id": "job-123",
            "reportTypeId": "channel_basic_a2",
            "createTime": "2026-04-03T10:00:00Z",
        }
        job = service.create_job("channel_basic_a2")
        assert isinstance(job, ReportingJob)
        assert job.job_id == "job-123"
        assert job.report_type_id == "channel_basic_a2"
        assert job.status == "pending"

    def test_create_job_validates_report_type_id(
        self, service: YouTubeReportingService
    ) -> None:
        """create_job rejects blank report_type_id."""
        with pytest.raises(ValueError, match="report_type_id must not be blank"):
            service.create_job("")

    def test_create_job_rejects_whitespace_only(
        self, service: YouTubeReportingService
    ) -> None:
        """create_job rejects whitespace-only report_type_id."""
        with pytest.raises(ValueError, match="report_type_id must not be blank"):
            service.create_job("   ")


class TestGetJobStatus:
    """Tests for get_job_status method."""

    def test_returns_updated_job_with_ready_report(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """get_job_status returns job with download URL when report is ready."""
        mock_reporting_client.jobs().reports().list().execute.return_value = {
            "reports": [
                {
                    "id": "report-456",
                    "jobId": "job-123",
                    "createTime": "2026-04-03T12:00:00Z",
                    "downloadUrl": "https://youtubereporting.googleapis.com/v1/media/report-456",
                }
            ]
        }
        job = service.get_job_status("job-123")
        assert isinstance(job, ReportingJob)
        assert job.status == "ready"
        assert job.download_url is not None

    def test_returns_pending_when_no_reports(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """get_job_status returns pending status when no reports available."""
        mock_reporting_client.jobs().reports().list().execute.return_value = {
            "reports": []
        }
        job = service.get_job_status("job-123")
        assert job.status == "pending"
        assert job.download_url is None

    def test_get_job_status_validates_job_id(
        self, service: YouTubeReportingService
    ) -> None:
        """get_job_status rejects blank job_id."""
        with pytest.raises(ValueError, match="job_id must not be blank"):
            service.get_job_status("")


class TestDownloadReport:
    """Tests for download_report method."""

    def test_downloads_and_saves_csv(
        self,
        service: YouTubeReportingService,
        mock_reporting_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """download_report fetches CSV and saves to disk."""
        csv_content = (
            b"date,views,estimatedMinutesWatched\n"
            b"2026-04-01,100,50.5\n"
            b"2026-04-02,120,60.0\n"
        )
        mock_reporting_client.media().download().execute.return_value = csv_content

        job = ReportingJob(
            job_id="job-123",
            report_type_id="channel_basic_a2",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            created_at="2026-04-03T10:00:00Z",
            status="ready",
            download_url="https://youtubereporting.googleapis.com/v1/media/report-456",
        )
        result_path = service.download_report(job, output_dir=tmp_path)
        assert result_path.exists()
        assert result_path.suffix == ".csv"
        content = result_path.read_text()
        assert "date,views" in content

    def test_download_report_rejects_job_without_url(
        self, service: YouTubeReportingService, tmp_path: Path
    ) -> None:
        """download_report raises error if job has no download URL."""
        job = ReportingJob(
            job_id="job-123",
            report_type_id="channel_basic_a2",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            created_at="2026-04-03T10:00:00Z",
            status="pending",
        )
        with pytest.raises(ValueError, match="No download URL"):
            service.download_report(job, output_dir=tmp_path)


class TestPollUntilReady:
    """Tests for poll_until_ready method."""

    def test_returns_ready_job_after_polling(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """poll_until_ready returns ready job once report becomes available."""
        # First call: no reports. Second call: report ready.
        mock_reporting_client.jobs().reports().list().execute.side_effect = [
            {"reports": []},
            {
                "reports": [
                    {
                        "id": "report-456",
                        "jobId": "job-123",
                        "createTime": "2026-04-03T12:00:00Z",
                        "downloadUrl": "https://youtubereporting.googleapis.com/v1/media/report-456",
                    }
                ]
            },
        ]
        with patch("time.sleep"):
            job = service.poll_until_ready("job-123", max_polls=5, interval=0)
        assert job.status == "ready"
        assert job.download_url is not None

    def test_timeout_after_max_polls(
        self, service: YouTubeReportingService, mock_reporting_client: MagicMock
    ) -> None:
        """poll_until_ready raises TimeoutError after max_polls with no ready report."""
        mock_reporting_client.jobs().reports().list().execute.return_value = {
            "reports": []
        }
        with patch("time.sleep"):
            with pytest.raises(TimeoutError, match="max polls"):
                service.poll_until_ready("job-123", max_polls=3, interval=0)


class TestFullLifecycle:
    """Test complete lifecycle: create -> poll -> download."""

    def test_create_poll_download(
        self,
        mock_reporting_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Full lifecycle: create job, poll until ready, download CSV."""
        service = YouTubeReportingService(client=mock_reporting_client)

        # create_job mock
        mock_reporting_client.jobs().create().execute.return_value = {
            "id": "job-lifecycle",
            "reportTypeId": "channel_basic_a2",
            "createTime": "2026-04-03T10:00:00Z",
        }

        # poll mock — ready on first poll
        mock_reporting_client.jobs().reports().list().execute.return_value = {
            "reports": [
                {
                    "id": "report-789",
                    "jobId": "job-lifecycle",
                    "createTime": "2026-04-03T12:00:00Z",
                    "downloadUrl": "https://youtubereporting.googleapis.com/v1/media/report-789",
                }
            ]
        }

        # download mock
        csv_content = b"date,views\n2026-04-01,100\n"
        mock_reporting_client.media().download().execute.return_value = csv_content

        # Lifecycle
        job = service.create_job("channel_basic_a2")
        assert job.status == "pending"

        with patch("time.sleep"):
            job = service.poll_until_ready(job.job_id, max_polls=5, interval=0)
        assert job.status == "ready"

        path = service.download_report(job, output_dir=tmp_path)
        assert path.exists()
        assert path.read_text().startswith("date,views")
