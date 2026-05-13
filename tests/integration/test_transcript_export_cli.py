"""T086 RED — integration + endpoint tests for transcript export/export-bulk CLI.

Tests:
- export_command: single video → output file written, audit row appended
- export_bulk_command: channel transcripts → all output files written, audit rows
- export_command missing transcript → exit code 1
- export_bulk_command with video-ids-file filter
- audit kb_export_audit.csv format validation
"""
import json
from pathlib import Path

import pytest


def _make_transcript(transcripts_dir: Path, video_id: str) -> None:
    data = {
        "video_id": video_id,
        "source": "asr:whisper",
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "segments": [
            {"start": 0.0, "end": 3.0, "text": f"안녕하세요 {video_id}"},
            {"start": 3.0, "end": 6.0, "text": "강의입니다"},
        ],
    }
    (transcripts_dir / f"{video_id}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_export_command_single_video(tmp_path: Path) -> None:
    """transcript export --video-id → output file written + audit row."""
    from tube_scout.cli.transcript import export_command

    transcripts_dir = tmp_path / "01_collect" / "transcripts"
    transcripts_dir.mkdir(parents=True)
    _make_transcript(transcripts_dir, "VID001")

    output_file = tmp_path / "kb_export" / "VID001.txt"
    output_file.parent.mkdir(parents=True)

    export_command(
        video_id="VID001",
        transcripts_dir=transcripts_dir,
        output=output_file,
        format_="txt",
        keep_timestamps=False,
        clean_fillers=False,
        with_meta=False,
        audit_dir=tmp_path,
    )

    assert output_file.exists()
    assert output_file.stat().st_size > 0
    content = output_file.read_text(encoding="utf-8")
    assert "VID001" in content or "강의입니다" in content

    audit_path = tmp_path / "01_collect" / "kb_export_audit.csv"
    assert audit_path.exists()
    audit_content = audit_path.read_text(encoding="utf-8")
    assert "VID001" in audit_content
    assert "success" in audit_content


def test_export_command_missing_transcript_raises(tmp_path: Path) -> None:
    """transcript export with non-existent transcript → FileNotFoundError."""
    from tube_scout.cli.transcript import export_command

    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    output_file = tmp_path / "out.txt"

    with pytest.raises(FileNotFoundError):
        export_command(
            video_id="MISSING",
            transcripts_dir=transcripts_dir,
            output=output_file,
            format_="txt",
            keep_timestamps=False,
            clean_fillers=False,
            with_meta=False,
            audit_dir=tmp_path,
        )


def test_export_bulk_command_all(tmp_path: Path) -> None:
    """transcript export-bulk --all → one file per transcript, audit rows."""
    from tube_scout.cli.transcript import export_bulk_command

    transcripts_dir = tmp_path / "01_collect" / "transcripts"
    transcripts_dir.mkdir(parents=True)
    output_dir = tmp_path / "kb_export"
    output_dir.mkdir()

    video_ids = [f"VID{i:03d}" for i in range(1, 6)]
    for vid in video_ids:
        _make_transcript(transcripts_dir, vid)

    export_bulk_command(
        transcripts_dir=transcripts_dir,
        output_dir=output_dir,
        video_ids_file=None,
        export_all=True,
        format_="txt",
        keep_timestamps=False,
        clean_fillers=False,
        with_meta=False,
        audit_dir=tmp_path,
    )

    for vid in video_ids:
        out_file = output_dir / f"{vid}.txt"
        assert out_file.exists(), f"Missing output: {out_file}"

    audit_path = tmp_path / "01_collect" / "kb_export_audit.csv"
    assert audit_path.exists()
    audit_text = audit_path.read_text(encoding="utf-8")
    for vid in video_ids:
        assert vid in audit_text


def test_export_bulk_command_video_ids_file(tmp_path: Path) -> None:
    """transcript export-bulk --video-ids-file → only specified IDs exported."""
    from tube_scout.cli.transcript import export_bulk_command

    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    output_dir = tmp_path / "kb_export"
    output_dir.mkdir()

    all_ids = [f"VID{i:03d}" for i in range(1, 6)]
    selected = all_ids[:2]
    for vid in all_ids:
        _make_transcript(transcripts_dir, vid)

    ids_file = tmp_path / "selected.txt"
    ids_file.write_text("\n".join(selected), encoding="utf-8")

    export_bulk_command(
        transcripts_dir=transcripts_dir,
        output_dir=output_dir,
        video_ids_file=ids_file,
        export_all=False,
        format_="txt",
        keep_timestamps=False,
        clean_fillers=False,
        with_meta=False,
        audit_dir=tmp_path,
    )

    for vid in selected:
        assert (output_dir / f"{vid}.txt").exists()
    for vid in all_ids[2:]:
        assert not (output_dir / f"{vid}.txt").exists()


def test_export_audit_csv_fieldnames(tmp_path: Path) -> None:
    """kb_export_audit.csv header must match KB_EXPORT_FIELDNAMES."""
    from tube_scout.cli.transcript import export_command
    from tube_scout.services.audit_writer import KB_EXPORT_FIELDNAMES

    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    _make_transcript(transcripts_dir, "AUD001")
    output_file = tmp_path / "AUD001.txt"

    export_command(
        video_id="AUD001",
        transcripts_dir=transcripts_dir,
        output=output_file,
        format_="txt",
        keep_timestamps=False,
        clean_fillers=False,
        with_meta=False,
        audit_dir=tmp_path,
    )

    import csv
    audit_path = tmp_path / "01_collect" / "kb_export_audit.csv"
    with open(audit_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames is not None
        for field in KB_EXPORT_FIELDNAMES:
            assert field in reader.fieldnames, f"Missing field: {field}"
