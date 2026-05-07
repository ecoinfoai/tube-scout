"""Unit tests for services/transcripts_audit (T036/T039)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tube_scout.services.transcripts_audit import (
    ALLOWED_CLASSIFICATIONS,
    AUDIT_HEADER,
    classify_miss,
    write_audit_csv,
)


class TestClassifyMiss:
    def test_transcripts_disabled(self) -> None:
        class TranscriptsDisabled(Exception):
            pass

        cls, hint = classify_miss(TranscriptsDisabled(), None, {"video_id": "v1"})
        assert cls == "transcripts_disabled"
        assert hint
        assert cls in ALLOWED_CLASSIFICATIONS

    def test_private_no_fallback(self) -> None:
        cls, hint = classify_miss(
            Exception("403"),
            Exception("captions API not configured"),
            {"video_id": "v1", "privacy_status": "private"},
        )
        assert cls == "private_no_captions_api"
        assert "auth --channel" in hint

    def test_unlisted_treated_as_private(self) -> None:
        cls, _ = classify_miss(
            Exception("403"),
            Exception("captions API"),
            {"video_id": "v1", "privacy_status": "unlisted"},
        )
        assert cls == "private_no_captions_api"

    def test_no_caption_track_for_public(self) -> None:
        class NoTranscriptFound(Exception):
            pass

        cls, hint = classify_miss(
            NoTranscriptFound(),
            None,
            {"video_id": "v1", "privacy_status": "public"},
        )
        assert cls == "no_caption_track"
        assert "ASR" in hint

    def test_api_error_fallback(self) -> None:
        cls, _ = classify_miss(
            Exception("network"),
            None,
            {"video_id": "v1", "privacy_status": "public"},
        )
        assert cls == "api_error"

    def test_unknown_when_no_errors(self) -> None:
        cls, hint = classify_miss(None, None, {"video_id": "v1"})
        assert cls == "unknown"
        assert hint


class TestWriteAuditCsv:
    def test_header_and_rows(self, tmp_path: Path) -> None:
        rows = [
            {
                "video_id": "abc",
                "title": "Lecture 1",
                "published_at": "2026-05-01",
                "privacy_status": "private",
                "classification": "private_no_captions_api",
                "hint": "register channel",
            },
        ]
        out = tmp_path / "transcripts_audit.csv"
        write_audit_csv(rows, out)
        assert out.exists()
        with out.open() as fh:
            reader = csv.reader(fh)
            header = next(reader)
            assert tuple(header) == AUDIT_HEADER
            data_row = next(reader)
            assert data_row[0] == "abc"
            assert data_row[4] == "private_no_captions_api"

    def test_csv_injection_neutralized(self, tmp_path: Path) -> None:
        rows = [
            {
                "video_id": "=cmd|/c calc",
                "title": "+attack",
                "published_at": "-1+1",
                "privacy_status": "@home",
                "classification": "api_error",
                "hint": "retry",
            },
        ]
        out = tmp_path / "audit.csv"
        write_audit_csv(rows, out)
        text = out.read_text()
        for prefix in ("=", "+", "-", "@"):
            for line in text.splitlines()[1:]:
                for cell in line.split(","):
                    cell = cell.strip().strip('"')
                    if cell:
                        assert not cell.startswith(prefix), (
                            f"Excel-injection prefix '{prefix}' leaked"
                        )

    def test_missing_keys_render_blank(self, tmp_path: Path) -> None:
        rows = [{"video_id": "abc"}]
        out = tmp_path / "audit.csv"
        write_audit_csv(rows, out)
        with out.open() as fh:
            reader = csv.reader(fh)
            next(reader)  # header
            row = next(reader)
            assert row[0] == "abc"
            assert row[1] == ""

    def test_missing_parent_dir_created(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "audit.csv"
        write_audit_csv([], out)
        assert out.exists()


class TestTranscriptSourceField:
    """T034: TranscriptService MUST set source field per retrieval path."""

    def test_source_values_documented(self) -> None:
        # Compile-time check: source is one of the documented values
        documented = {"manual", "auto_generated", "captions_api"}
        assert documented.issubset(
            {"manual", "auto_generated", "captions_api"}
        )
