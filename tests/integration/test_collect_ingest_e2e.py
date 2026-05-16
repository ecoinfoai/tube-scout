"""T012 RED — e2e integration test for `collect ingest` with real nursing archive (spec 017 US1).

Uses data/takeout-20260511T130817Z-3-001 (nursing, 9 mp4 + 2554 metadata rows).
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


def _faster_whisper_available() -> bool:
    """Check whether the ``asr`` optional extra is installed.

    The full-pipeline e2e test runs faster-whisper on every mp4 and would
    otherwise mark every video as ``transcript_failed`` with an ImportError,
    masking the actual integration signal.
    """
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.slow
@pytest.mark.skipif(
    not _ARCHIVE_PRESENT,
    reason="Real takeout archive not present — skipping e2e test",
)
@pytest.mark.skipif(
    not _faster_whisper_available(),
    reason=(
        "faster-whisper not installed — run `uv sync --extra asr` to enable "
        "the ASR-dependent e2e test."
    ),
)
class TestCollectIngestE2E:
    """T012 — full collect ingest pipeline with real nursing archive."""

    @pytest.fixture(scope="class")
    def ingest_output(self, tmp_path_factory):
        """Run collect ingest once for the whole class; return (result, work_root, db_path)."""
        from unittest.mock import MagicMock, patch

        from tube_scout.cli.main import app

        work_root = tmp_path_factory.mktemp("nursing_unified_work")
        db_path = work_root / "test.db"

        mock_reg = MagicMock()
        mock_reg.channel_id = "UCnh3tm9uQkyA260cAHfl9rg"

        runner = CliRunner()
        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"nursing": mock_reg},
        ):
            result = runner.invoke(app, [
                "collect", "ingest",
                "--takeout-dir", str(_ARCHIVE_ROOT),
                "--channel", "nursing",
                "--data-dir", str(work_root),
                "--db-path", str(db_path),
                # No --preset override here: resolve_preset() auto-detects
                # the host's GPU and picks poc-laptop for any card with
                # >= 4 GiB VRAM, cpu-fallback otherwise. Operators can still
                # force a preset via TUBE_SCOUT_ASR_PRESET when needed.
            ])
        return result, work_root, db_path

    def test_e2e_full_pipeline(self, ingest_output) -> None:
        """Full pipeline yields 2554 video_metadata rows, 9 transcript files, 9 fingerprint rows."""
        result, work_root, db_path = ingest_output

        assert result.exit_code == 0, (
            f"Expected exit 0 for full pipeline, got {result.exit_code}\n{result.output}"
        )

        conn = sqlite3.connect(db_path)
        video_count = conn.execute(
            "SELECT COUNT(*) FROM video_metadata"
        ).fetchone()[0]
        conn.close()
        assert video_count == 2554, (
            f"Expected 2554 video_metadata rows after full ingest, got {video_count}"
        )

        transcript_dir = work_root / "nursing" / "03_transcripts"
        if transcript_dir.exists():
            transcript_files = list(transcript_dir.glob("*.json"))
            assert len(transcript_files) == 9, (
                f"Expected 9 transcript JSON files (one per mp4), got {len(transcript_files)}"
            )

        conn = sqlite3.connect(db_path)
        fp_count = conn.execute(
            "SELECT COUNT(*) FROM audio_fingerprint"
        ).fetchone()[0]
        conn.close()
        assert fp_count == 9, (
            f"Expected 9 rows in audio_fingerprint, got {fp_count}"
        )

        retry_manifest = work_root / "nursing" / "retry_pending.json"
        assert retry_manifest.exists(), "retry_pending.json must be created after full pipeline"
        import json
        manifest_data = json.loads(retry_manifest.read_text(encoding="utf-8"))
        assert manifest_data.get("entries") == [], (
            "retry_pending.json entries must be empty when all stages succeed"
        )

    def test_e2e_stage_elapsed_seconds_positive(self, ingest_output) -> None:
        """T033 — each stage in UnifiedIngestSummary must report positive elapsed time."""
        from unittest.mock import MagicMock, patch

        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import ingest_unified

        _, work_root, _ = ingest_output
        db_path = work_root / "t033.db"

        mock_reg = MagicMock()
        mock_reg.channel_id = "UCnh3tm9uQkyA260cAHfl9rg"

        audit = AuditWriter(work_root / "t033_audit")

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"nursing": mock_reg},
        ):
            summary = ingest_unified(
                takeout_dir=_ARCHIVE_ROOT,
                channel_alias="nursing",
                db_path=db_path,
                work_root=work_root / "t033_work",
                audit_writer=audit,
            )

        assert summary.ingest_result.elapsed_seconds > 0, (
            f"ingest stage elapsed must be > 0, got {summary.ingest_result.elapsed_seconds}"
        )
        assert summary.transcript_result.elapsed_seconds > 0, (
            f"transcript stage elapsed must be > 0, "
            f"got {summary.transcript_result.elapsed_seconds}"
        )
        assert summary.fingerprint_result.elapsed_seconds > 0, (
            f"fingerprint stage elapsed must be > 0, "
            f"got {summary.fingerprint_result.elapsed_seconds}"
        )
        assert summary.total_elapsed_seconds > 0, (
            f"total elapsed must be > 0, got {summary.total_elapsed_seconds}"
        )
        assert summary.cleanup_result is None, (
            "--delete-source not passed, cleanup_result must be None"
        )
