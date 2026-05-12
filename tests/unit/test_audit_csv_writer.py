"""Unit tests for AuditWriter (spec 012, FR-015, data-model E-5).

T010 RED — 6 scenarios for CSV append, header, atomic write, and fieldnames.
"""

import csv


def test_transcripts_fieldnames_constant():
    from tube_scout.services.audit_writer import TRANSCRIPTS_FIELDNAMES

    assert TRANSCRIPTS_FIELDNAMES == (
        "video_id", "result", "reason",
        "source", "caption_source_detail", "timestamp", "cookies_source",
    )


def test_fingerprint_fieldnames_constant():
    from tube_scout.services.audit_writer import FINGERPRINT_FIELDNAMES

    assert FINGERPRINT_FIELDNAMES == (
        "video_id", "result", "reason",
        "duration_sec", "fingerprint_input_policy", "timestamp", "cookies_source",
    )


def test_append_transcript_row_creates_file_with_header(tmp_path):
    from tube_scout.services.audit_writer import TRANSCRIPTS_FIELDNAMES, AuditWriter

    writer = AuditWriter(tmp_path)
    row = {
        "video_id": "abc12345678",
        "result": "success",
        "reason": "captured",
        "source": "ytdlp:manual",
        "timestamp": "2026-05-09T12:00:00+09:00",
        "cookies_source": "brave",
    }
    writer.append_transcript_row(row)

    csv_path = tmp_path / "01_collect" / "transcripts_audit.csv"
    assert csv_path.exists()
    rows = list(csv.DictReader(csv_path.open()))
    assert len(rows) == 1
    assert list(rows[0].keys()) == list(TRANSCRIPTS_FIELDNAMES)
    assert rows[0]["video_id"] == "abc12345678"


def test_append_transcript_row_appends_not_overwrites(tmp_path):
    from tube_scout.services.audit_writer import AuditWriter

    writer = AuditWriter(tmp_path)
    base_row = {
        "video_id": "vid00000001",
        "result": "success",
        "reason": "captured",
        "source": "ytdlp:auto",
        "timestamp": "2026-05-09T12:00:00+09:00",
        "cookies_source": "brave",
    }
    writer.append_transcript_row(base_row)
    writer.append_transcript_row({**base_row, "video_id": "vid00000002"})

    csv_path = tmp_path / "01_collect" / "transcripts_audit.csv"
    rows = list(csv.DictReader(csv_path.open()))
    assert len(rows) == 2
    assert rows[0]["video_id"] == "vid00000001"
    assert rows[1]["video_id"] == "vid00000002"


def test_header_written_only_once(tmp_path):
    from tube_scout.services.audit_writer import AuditWriter

    writer = AuditWriter(tmp_path)
    row = {
        "video_id": "vid00000001",
        "result": "skip",
        "reason": "skip_existing",
        "source": "",
        "timestamp": "2026-05-09T12:00:00+09:00",
        "cookies_source": "brave",
    }
    writer.append_transcript_row(row)
    writer.append_transcript_row({**row, "video_id": "vid00000002"})

    csv_path = tmp_path / "01_collect" / "transcripts_audit.csv"
    lines = csv_path.read_text().splitlines()
    header_count = sum(1 for line in lines if line.startswith("video_id,"))
    assert header_count == 1


def test_append_fingerprint_row_creates_file(tmp_path):
    from tube_scout.services.audit_writer import FINGERPRINT_FIELDNAMES, AuditWriter

    writer = AuditWriter(tmp_path)
    row = {
        "video_id": "abc12345678",
        "result": "success",
        "reason": "captured",
        "duration_sec": "1823.4",
        "timestamp": "2026-05-09T12:00:00+09:00",
        "cookies_source": "file",
    }
    writer.append_fingerprint_row(row)

    csv_path = tmp_path / "01_collect" / "fingerprint_audit.csv"
    assert csv_path.exists()
    rows = list(csv.DictReader(csv_path.open()))
    assert len(rows) == 1
    assert list(rows[0].keys()) == list(FINGERPRINT_FIELDNAMES)


def test_audit_writer_creates_parent_dirs(tmp_path):
    from tube_scout.services.audit_writer import AuditWriter

    deep_path = tmp_path / "projects" / "job-001"
    writer = AuditWriter(deep_path)
    row = {
        "video_id": "abc12345678",
        "result": "fail",
        "reason": "rate_limit",
        "source": "",
        "timestamp": "2026-05-09T12:00:00+09:00",
        "cookies_source": "brave",
    }
    writer.append_transcript_row(row)

    assert (deep_path / "01_collect" / "transcripts_audit.csv").exists()
