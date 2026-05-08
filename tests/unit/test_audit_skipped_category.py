"""Unit tests for spec 010 FR-010-06 — `skipped` audit classification."""

from __future__ import annotations

import csv
from pathlib import Path

from tube_scout.services.transcripts_audit import (
    ALLOWED_CLASSIFICATIONS,
    write_audit_csv,
)


class TestSkippedClassificationRegistered:
    def test_skipped_in_allowed_set(self) -> None:
        """FR-010-06: 'skipped' must be a recognised classification token."""
        assert "skipped" in ALLOWED_CLASSIFICATIONS

    def test_existing_classifications_still_present(self) -> None:
        """No existing token is dropped when 'skipped' is added."""
        for token in (
            "private_no_captions_api",
            "transcripts_disabled",
            "no_caption_track",
            "api_error",
            "unknown",
        ):
            assert token in ALLOWED_CLASSIFICATIONS


class TestSkippedRowRoundTrip:
    def test_skipped_row_roundtrips_through_csv(self, tmp_path: Path) -> None:
        """A row with classification='skipped' writes and re-reads cleanly."""
        rows = [
            {
                "video_id": "private_vid_001",
                "title": "Sample Lecture Week 1",
                "published_at": "2026-04-06T07:24:13Z",
                "privacy_status": "unlisted",
                "classification": "skipped",
                "hint": (
                    "Existing transcript at projects/test/01_collect/"
                    "transcripts/private_vid_001.json (5 segments); "
                    "pass --force-refresh to override."
                ),
            }
        ]
        csv_path = tmp_path / "audit.csv"
        write_audit_csv(rows, csv_path)

        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            loaded = list(reader)
        assert len(loaded) == 1
        assert loaded[0]["classification"] == "skipped"
        assert "cached" in loaded[0]["hint"] or "Existing" in loaded[0]["hint"]
        assert "--force-refresh" in loaded[0]["hint"]

    def test_skipped_hint_does_not_trigger_excel_injection_guard(
        self, tmp_path: Path
    ) -> None:
        """Hint must not start with =, +, -, or @ (Excel CSV injection vectors)."""
        rows = [
            {
                "video_id": "private_vid_001",
                "title": "Sample",
                "published_at": "",
                "privacy_status": "private",
                "classification": "skipped",
                "hint": "Existing transcript at /tmp/x.json (3 segments).",
            }
        ]
        csv_path = tmp_path / "audit.csv"
        write_audit_csv(rows, csv_path)
        text = csv_path.read_text(encoding="utf-8")
        # The hint cell must not start with a CSV-injection-prone char.
        for line in text.splitlines()[1:]:  # skip header
            cells = line.split(",")
            hint_cell = cells[-1] if cells else ""
            if hint_cell:
                assert hint_cell[0] not in "=+-@\t", (
                    f"Hint starts with injection-prone char: {hint_cell[:20]}"
                )
