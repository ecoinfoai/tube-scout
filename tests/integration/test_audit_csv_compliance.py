"""T041 RED: data-model E-5 — audit CSV column sequence frozen, append-only invariant.

Phase 5 / User Story 3: AuditWriter must produce exactly the columns defined in
data-model.md E-5. Column order, count, and names must be frozen (spec Y compatibility).

Verified properties:
- transcripts_audit.csv: exactly TRANSCRIPTS_FIELDNAMES (6 columns in order)
- fingerprint_audit.csv: exactly FINGERPRINT_FIELDNAMES (6 columns in order)
- Append-only: second call appends a row; header appears only once
- Column sequence matches data-model.md E-5 tables (contractual freeze)
"""

import csv
import datetime
from pathlib import Path

import pytest

from tube_scout.services.audit_writer import (
    FINGERPRINT_FIELDNAMES,
    TRANSCRIPTS_FIELDNAMES,
    AuditWriter,
)


# ---------------------------------------------------------------------------
# Expected columns per data-model.md E-5 (contractual freeze)
# ---------------------------------------------------------------------------

_EXPECTED_TRANSCRIPTS_COLS = (
    "video_id",
    "result",
    "reason",
    "source",
    "timestamp",
    "cookies_source",
)

_EXPECTED_FINGERPRINT_COLS = (
    "video_id",
    "result",
    "reason",
    "duration_sec",
    "timestamp",
    "cookies_source",
)


def _csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        return next(reader)


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Scenario 1: TRANSCRIPTS_FIELDNAMES constant matches data-model E-5
# ---------------------------------------------------------------------------

def test_transcripts_fieldnames_constant_matches_data_model() -> None:
    """TRANSCRIPTS_FIELDNAMES must exactly equal data-model.md E-5 transcripts columns."""
    assert tuple(TRANSCRIPTS_FIELDNAMES) == _EXPECTED_TRANSCRIPTS_COLS, (
        f"TRANSCRIPTS_FIELDNAMES mismatch.\n"
        f"  Expected: {_EXPECTED_TRANSCRIPTS_COLS}\n"
        f"  Got:      {tuple(TRANSCRIPTS_FIELDNAMES)}"
    )


# ---------------------------------------------------------------------------
# Scenario 2: FINGERPRINT_FIELDNAMES constant matches data-model E-5
# ---------------------------------------------------------------------------

def test_fingerprint_fieldnames_constant_matches_data_model() -> None:
    """FINGERPRINT_FIELDNAMES must exactly equal data-model.md E-5 fingerprint columns."""
    assert tuple(FINGERPRINT_FIELDNAMES) == _EXPECTED_FINGERPRINT_COLS, (
        f"FINGERPRINT_FIELDNAMES mismatch.\n"
        f"  Expected: {_EXPECTED_FINGERPRINT_COLS}\n"
        f"  Got:      {tuple(FINGERPRINT_FIELDNAMES)}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: transcripts_audit.csv header order + append-only
# ---------------------------------------------------------------------------

def test_transcripts_audit_csv_column_order_and_append_only(tmp_path: Path) -> None:
    """transcripts_audit.csv must have exact column order; header appears only once."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    writer = AuditWriter(project_dir)

    ts = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    row1 = {
        "video_id": "aaaaaaaaaaa",
        "result": "success",
        "reason": "captured",
        "source": "ytdlp:manual",
        "timestamp": ts,
        "cookies_source": "brave",
    }
    row2 = {
        "video_id": "bbbbbbbbbbb",
        "result": "skip",
        "reason": "skip_existing",
        "source": None,
        "timestamp": ts,
        "cookies_source": "brave",
    }

    writer.append_transcript_row(row1)
    writer.append_transcript_row(row2)

    csv_path = project_dir / "01_collect" / "transcripts_audit.csv"
    assert csv_path.exists(), "transcripts_audit.csv not created"

    header = _csv_header(csv_path)
    assert header == list(_EXPECTED_TRANSCRIPTS_COLS), (
        f"Column order mismatch.\n"
        f"  Expected: {list(_EXPECTED_TRANSCRIPTS_COLS)}\n"
        f"  Got:      {header}"
    )

    rows = _csv_rows(csv_path)
    assert len(rows) == 2, f"Expected 2 data rows, got {len(rows)}"
    assert rows[0]["video_id"] == "aaaaaaaaaaa"
    assert rows[1]["video_id"] == "bbbbbbbbbbb"

    # Header must appear exactly once (append-only)
    raw_lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    header_lines = [l for l in raw_lines if l.startswith("video_id,")]
    assert len(header_lines) == 1, (
        f"Header appeared {len(header_lines)} time(s); expected exactly 1 (append-only)"
    )


# ---------------------------------------------------------------------------
# Scenario 4: fingerprint_audit.csv header order + append-only
# ---------------------------------------------------------------------------

def test_fingerprint_audit_csv_column_order_and_append_only(tmp_path: Path) -> None:
    """fingerprint_audit.csv must have exact column order; header appears only once."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    writer = AuditWriter(project_dir)

    ts = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    row1 = {
        "video_id": "ccccccccccc",
        "result": "success",
        "reason": "captured",
        "duration_sec": 1821.5,
        "timestamp": ts,
        "cookies_source": "brave",
    }
    row2 = {
        "video_id": "ddddddddddd",
        "result": "skip",
        "reason": "too_short",
        "duration_sec": None,
        "timestamp": ts,
        "cookies_source": "file",
    }

    writer.append_fingerprint_row(row1)
    writer.append_fingerprint_row(row2)

    csv_path = project_dir / "01_collect" / "fingerprint_audit.csv"
    assert csv_path.exists(), "fingerprint_audit.csv not created"

    header = _csv_header(csv_path)
    assert header == list(_EXPECTED_FINGERPRINT_COLS), (
        f"Column order mismatch.\n"
        f"  Expected: {list(_EXPECTED_FINGERPRINT_COLS)}\n"
        f"  Got:      {header}"
    )

    rows = _csv_rows(csv_path)
    assert len(rows) == 2, f"Expected 2 data rows, got {len(rows)}"

    # Header once
    raw_lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    header_lines = [l for l in raw_lines if l.startswith("video_id,")]
    assert len(header_lines) == 1, (
        f"Header appeared {len(header_lines)} time(s); expected exactly 1"
    )
