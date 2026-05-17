"""RED contract tests for AuditWriter v2 generalization (spec 013 T016).

Ref: contracts/audit_writer_v2_contract.md + data-model.md §E-12.
"""

import csv
from pathlib import Path

import pytest

from tube_scout.services.audit_writer import (
    STAGE_FIELDNAMES,
    AuditWriter,
)


def test_stage_fieldnames_has_8_entries() -> None:
    """STAGE_FIELDNAMES must include the 8 spec 013 stages plus spec 017 additions."""
    spec013_keys = {
        "takeout_ingest", "audio_extract", "transcripts", "fingerprint",
        "normalize", "analyze", "report", "kb_export",
    }
    spec017_keys = {"ingest_orchestrator", "source_video_cleanup"}
    assert set(STAGE_FIELDNAMES.keys()) == spec013_keys | spec017_keys
    assert len(STAGE_FIELDNAMES) == len(spec013_keys) + len(spec017_keys)


def test_append_row_unknown_stage_logged_not_raised(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """append_row must log a warning and NOT raise for unknown stage (ADV-59 graceful)."""
    import logging
    writer = AuditWriter(tmp_path)
    with caplog.at_level(logging.WARNING, logger="tube_scout.services.audit_writer"):
        writer.append_row("nonexistent_stage", {"result": "success", "reason": "ok"})
    assert any("nonexistent_stage" in r.message for r in caplog.records)


def test_append_row_invalid_result_logged_not_raised(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """append_row must log a warning and NOT raise for invalid result (ADV-59 graceful)."""
    import logging
    writer = AuditWriter(tmp_path)
    row = {k: "x" for k in STAGE_FIELDNAMES["transcripts"]}
    row["result"] = "bad_result"
    with caplog.at_level(logging.WARNING, logger="tube_scout.services.audit_writer"):
        writer.append_row("transcripts", row)
    assert any("bad_result" in r.message or "result" in r.message for r in caplog.records)


def test_append_row_drops_extra_keys(tmp_path: Path) -> None:
    """append_row must silently ignore keys not in the stage fieldnames."""
    writer = AuditWriter(tmp_path)
    fieldnames = STAGE_FIELDNAMES["transcripts"]
    row = {k: "x" for k in fieldnames}
    row["result"] = "success"
    row["extra_unknown_key"] = "should_be_dropped"
    writer.append_row("transcripts", row)

    csv_path = tmp_path / "01_collect" / "transcripts_audit.csv"
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        written_row = next(reader)
    assert "extra_unknown_key" not in written_row


def test_append_row_writes_header_on_first_call_only(tmp_path: Path) -> None:
    """Header row must appear exactly once even after multiple append_row calls."""
    writer = AuditWriter(tmp_path)
    fieldnames = STAGE_FIELDNAMES["transcripts"]
    row = {k: "x" for k in fieldnames}
    row["result"] = "success"

    writer.append_row("transcripts", row)
    writer.append_row("transcripts", row)

    csv_path = tmp_path / "01_collect" / "transcripts_audit.csv"
    lines = csv_path.read_text().splitlines()
    header_count = sum(1 for line in lines if line.startswith("video_id"))
    assert header_count == 1


def test_append_row_atomic_tempfile_rename_pattern(tmp_path: Path) -> None:
    """No .tmp files must remain after append_row completes."""
    writer = AuditWriter(tmp_path)
    fieldnames = STAGE_FIELDNAMES["transcripts"]
    row = {k: "x" for k in fieldnames}
    row["result"] = "success"
    writer.append_row("transcripts", row)

    collect_dir = tmp_path / "01_collect"
    tmp_files = list(collect_dir.glob("*.tmp"))
    assert tmp_files == [], f"Leftover .tmp files found: {tmp_files}"
