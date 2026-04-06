"""YouTube Reporting API service for bulk data download."""

import time
from pathlib import Path
from typing import Any

import polars as pl
from googleapiclient.errors import HttpError

from tube_scout.models.analytics import ReportingJob


class YouTubeReportingService:
    """Service for interacting with YouTube Reporting API v1."""

    def __init__(self, client: Any | None = None) -> None:
        """Initialize with a YouTube Reporting API client.

        Args:
            client: Pre-built API client (for testing/injection).
        """
        self._client = client

    def _require_client(self) -> Any:
        """Return client or raise if not configured.

        Returns:
            The configured API client.

        Raises:
            ValueError: If client is not configured.
        """
        if self._client is None:
            raise ValueError("Reporting API client is not configured")
        return self._client

    def list_report_types(self) -> list[dict[str, Any]]:
        """List available report types from the Reporting API.

        Returns:
            List of report type dicts with 'id' and 'name' keys.
        """
        client = self._require_client()
        response = client.reportTypes().list().execute()
        return response.get("reportTypes", [])

    def create_job(self, report_type_id: str) -> ReportingJob:
        """Create a reporting job for the given report type.

        Args:
            report_type_id: The report type ID to create a job for.

        Returns:
            ReportingJob with status 'pending'.

        Raises:
            ValueError: If report_type_id is blank.
            PermissionError: If API returns 401/403.
            RuntimeError: If API returns other errors.
        """
        if not report_type_id.strip():
            raise ValueError("report_type_id must not be blank")

        client = self._require_client()

        try:
            response = (
                client.jobs().create(body={"reportTypeId": report_type_id}).execute()
            )
        except HttpError as e:
            if e.resp.status in (401, 403):
                raise PermissionError(f"Failed to create reporting job: {e}") from e
            raise RuntimeError(f"API error creating reporting job: {e}") from e

        return ReportingJob(
            job_id=response["id"],
            report_type_id=response["reportTypeId"],
            created_at=response["createTime"],
            status="pending",
        )

    def get_job_status(self, job_id: str) -> ReportingJob:
        """Check the status of a reporting job.

        Args:
            job_id: The job ID to check.

        Returns:
            ReportingJob with updated status and download_url if ready.

        Raises:
            ValueError: If job_id is blank.
        """
        if not job_id.strip():
            raise ValueError("job_id must not be blank")

        client = self._require_client()
        response = client.jobs().reports().list(jobId=job_id).execute()
        reports = response.get("reports", [])

        if reports:
            latest = reports[0]
            return ReportingJob(
                job_id=job_id,
                report_type_id="unknown",
                created_at=latest.get("createTime", ""),
                status="ready",
                download_url=latest.get("downloadUrl"),
            )

        return ReportingJob(
            job_id=job_id,
            report_type_id="unknown",
            created_at="",
            status="pending",
        )

    def poll_until_ready(
        self,
        job_id: str,
        max_polls: int = 60,
        interval: int = 60,
    ) -> ReportingJob:
        """Poll job status until a report is ready or max_polls exhausted.

        Args:
            job_id: The job ID to poll.
            max_polls: Maximum number of poll attempts.
            interval: Seconds between polls.

        Returns:
            ReportingJob with status 'ready'.

        Raises:
            TimeoutError: If job never becomes ready within max_polls.
        """
        for _ in range(max_polls):
            job = self.get_job_status(job_id)
            if job.status == "ready":
                return job
            time.sleep(interval)

        raise TimeoutError(
            f"Reporting job {job_id} not ready after max polls ({max_polls})"
        )

    def download_report(self, job: ReportingJob, output_dir: Path) -> Path:
        """Download a ready report's CSV data.

        Args:
            job: ReportingJob with status 'ready' and download_url set.
            output_dir: Directory to save the downloaded CSV.

        Returns:
            Path to the downloaded CSV file.

        Raises:
            ValueError: If job has no download URL or response is empty.
            RuntimeError: If download fails (with retry suggestion).
        """
        if not job.download_url:
            raise ValueError(
                f"No download URL for job {job.job_id}. Job may not be ready yet."
            )

        client = self._require_client()

        try:
            data = client.media().download(resourceName=job.download_url).execute()
        except HttpError as e:
            raise RuntimeError(
                f"Failed to download report for job {job.job_id}: {e}. "
                "Please retry later."
            ) from e

        if not data:
            raise ValueError(
                f"Empty response when downloading report for job {job.job_id}"
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{job.report_type_id}_{job.job_id}.csv"

        if isinstance(data, bytes):
            output_path.write_bytes(data)
        else:
            output_path.write_text(str(data))

        return output_path


def parse_report_csv(csv_path: Path) -> pl.DataFrame:
    """Parse a downloaded reporting CSV into a polars DataFrame.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        polars DataFrame with parsed data.

    Raises:
        ValueError: If CSV is empty, has no data rows, or is malformed.
    """
    content = csv_path.read_text().strip()
    if not content:
        raise ValueError(f"CSV file is empty: {csv_path}")

    lines = content.split("\n")
    if len(lines) < 2:
        raise ValueError(f"CSV has no data rows: {csv_path}")

    header_count = len(lines[0].split(","))
    for i, line in enumerate(lines[1:], start=2):
        col_count = len(line.split(","))
        if col_count != header_count:
            raise ValueError(
                f"CSV is malformed at line {i}: expected {header_count} "
                f"columns, got {col_count} in {csv_path}"
            )

    return pl.read_csv(csv_path)
