"""RED integration test for 8-stage audit log pipeline (spec 013 T017).

Simulates 4 stages (takeout_ingest → audio_extract → transcripts → analyze)
via AuditWriter.append_row and verifies separate CSV files with correct headers.

Ref: contracts/audit_writer_v2_contract.md + data-model.md §E-12.
"""

import csv
from pathlib import Path

import pytest

from tube_scout.services.audit_writer import STAGE_FIELDNAMES, AuditWriter

_TS = "2026-05-13T10:00:00+09:00"

_STAGE_ROWS = {
    "takeout_ingest": {
        "video_id": "vid001",
        "result": "success",
        "reason": "mapping_resolved_manual",
        "mp4_filename": "5-1.lec.mp4",
        "match_confidence": "high",
        "score": "0.95",
        "timestamp": _TS,
        "raw_value": "",
        "elapsed_ms": "0",
    },
    "audio_extract": {
        "video_id": "vid001",
        "result": "success",
        "reason": "ok",
        "input_kind": "mp4",
        "output_path": "/tmp/vid001.wav",
        "wav_size_bytes": "2048000",
        "elapsed_s": "1.23",
        "timestamp": _TS,
    },
    "transcripts": {
        "video_id": "vid001",
        "result": "success",
        "reason": "ok",
        "source": "asr",
        "caption_source_detail": "faster-whisper-large-v3",
        "timestamp": _TS,
        "cookies_source": "",
    },
    "analyze": {
        "pair_id": "pair-001",
        "source_video_id": "vid001",
        "target_video_id": "vid002",
        "result": "success",
        "reason": "ok",
        "matching_mode": "M-nC2",
        "elapsed_s": "0.05",
        "timestamp": _TS,
    },
}


def test_4_stage_pipeline_creates_separate_csv_files(tmp_path: Path) -> None:
    """4-stage pipeline writes 4 separate CSV files with correct headers and rows."""
    writer = AuditWriter(tmp_path)

    for stage, row in _STAGE_ROWS.items():
        writer.append_row(stage, row)

    collect_dir = tmp_path / "01_collect"
    for stage, row in _STAGE_ROWS.items():
        csv_path = collect_dir / f"{stage}_audit.csv"

        assert csv_path.exists(), f"{stage}_audit.csv not found"

        with csv_path.open(newline="") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == list(STAGE_FIELDNAMES[stage]), (
                f"{stage} header mismatch"
            )
            rows = list(reader)

        assert len(rows) == 1, f"{stage} expected 1 data row, got {len(rows)}"

        fieldnames = STAGE_FIELDNAMES[stage]
        for field in fieldnames:
            assert field in rows[0], f"{stage} missing field {field!r}"
            assert rows[0][field] == str(row.get(field, "")), (
                f"{stage}.{field} value mismatch"
            )
