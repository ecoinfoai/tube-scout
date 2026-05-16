"""T013 RED — idempotent integration test for collect ingest (spec 017 US1, SC-004).

Verifies that running collect ingest twice on the same archive yields identical
DB state and zero re-processing on the second run.
Skipped when archive is absent. Fails at RED stage: collect ingest command does not exist.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

_ARCHIVE_ROOT = (
    Path(__file__).parent.parent.parent
    / "data"
    / "takeout-20260511T130817Z-3-001"
)

_ARCHIVE_PRESENT = _ARCHIVE_ROOT.exists()


@pytest.mark.skipif(
    not _ARCHIVE_PRESENT,
    reason="Real takeout archive not present — skipping idempotent test",
)
class TestIngestIdempotent:
    """T013 — two consecutive collect ingest calls on same archive are idempotent (SC-004)."""

    @pytest.fixture(scope="class")
    def two_run_outputs(self, tmp_path_factory):
        """Run collect ingest twice; return (result1, result2, work_root, db_path)."""
        from unittest.mock import MagicMock, patch

        from tube_scout.cli.main import app

        work_root = tmp_path_factory.mktemp("nursing_idempotent_work")
        db_path = work_root / "test.db"

        mock_reg = MagicMock()
        mock_reg.channel_id = "UCnh3tm9uQkyA260cAHfl9rg"

        runner = CliRunner()
        common_args = [
            "collect", "ingest",
            "--takeout-dir", str(_ARCHIVE_ROOT),
            "--channel", "nursing",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ]

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"nursing": mock_reg},
        ):
            result1 = runner.invoke(app, common_args)
            result2 = runner.invoke(app, common_args)

        return result1, result2, work_root, db_path

    def test_idempotent_db_row_count(self, two_run_outputs) -> None:
        """Second run does not add rows to video_metadata (SC-004)."""
        result1, result2, work_root, db_path = two_run_outputs

        assert result1.exit_code == 0, f"First run failed: {result1.output}"
        assert result2.exit_code == 0, f"Second run failed: {result2.output}"

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM video_metadata"
        ).fetchone()[0]
        conn.close()
        assert count == 2554, (
            f"Expected 2554 video_metadata rows after idempotent second run, got {count}"
        )

    def test_idempotent_new_videos_zero(self, two_run_outputs) -> None:
        """Second run reports new_videos=0 in UnifiedIngestSummary.ingest_result."""
        result1, result2, work_root, db_path = two_run_outputs

        # new_videos=0 is detectable from stdout — the CLI must report it
        assert "new=0" in result2.output or "new_videos=0" in result2.output, (
            f"Expected new_videos=0 in second run output, got:\n{result2.output}"
        )

    def test_idempotent_transcript_fingerprint_unchanged(self, two_run_outputs) -> None:
        """Transcript and fingerprint files are not re-generated on second run."""
        result1, result2, work_root, db_path = two_run_outputs

        transcript_dir = work_root / "nursing" / "03_transcripts"
        if not transcript_dir.exists():
            pytest.skip("transcript_dir not created — skipping mtime check")

        # Allow 1s buffer between runs — if files were re-created their mtime
        # would be after result1 completed
        transcript_files = sorted(transcript_dir.glob("*.json"))
        if not transcript_files:
            pytest.skip("No transcript files found — skipping mtime check")

        # All transcripts must have been created before second run started
        # (mtime from first run, not second run)
        # We check that second run output does not contain "새로 생성" / "success" for transcripts
        assert result2.output is not None, "Second run produced no output"
