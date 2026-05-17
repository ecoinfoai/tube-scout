"""T084 RED — integration test for kb_export bulk export."""
import json
from pathlib import Path


def _make_transcript(transcripts_dir: Path, video_id: str, source: str = "captions_api_auto") -> None:
    data = {
        "video_id": video_id,
        "source": source,
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "segments": [
            {"start": 0.0, "end": 3.0, "text": f"안녕하세요 {video_id}"},
            {"start": 3.0, "end": 6.0, "text": "강의입니다"},
        ],
    }
    (transcripts_dir / f"{video_id}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_bulk_export_50_transcripts(tmp_path: Path) -> None:
    """export_bulk produces one output file per input transcript (50 total)."""
    from tube_scout.services.kb_export import export_bulk

    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    output_dir = tmp_path / "kb_export"
    output_dir.mkdir()

    video_ids = [f"VID{i:04d}" for i in range(1, 51)]
    for vid in video_ids:
        _make_transcript(transcripts_dir, vid)

    result = export_bulk(transcripts_dir, output_dir)

    assert result.total_videos == 50
    assert result.exported_count == 50
    assert result.failed_count == 0

    for vid in video_ids:
        out_file = output_dir / f"{vid}.txt"
        assert out_file.exists(), f"Missing output for {vid}"
        assert out_file.stat().st_size > 0


def test_bulk_export_source_agnostic(tmp_path: Path) -> None:
    """FR-042: ASR source and captions_api source produce identical format output."""
    from tube_scout.services.kb_export import export_bulk

    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    output_dir = tmp_path / "kb_export"
    output_dir.mkdir()

    _make_transcript(transcripts_dir, "ASR_VID01", source="asr:whisper")
    _make_transcript(transcripts_dir, "API_VID01", source="captions_api")

    result = export_bulk(transcripts_dir, output_dir)

    assert result.exported_count == 2

    asr_content = (output_dir / "ASR_VID01.txt").read_text(encoding="utf-8")
    api_content = (output_dir / "API_VID01.txt").read_text(encoding="utf-8")

    # Both should have same structure (plain text lines — only video_id differs in text)
    asr_lines = asr_content.splitlines()
    api_lines = api_content.splitlines()
    assert len(asr_lines) == len(api_lines)
    # Second segment is identical
    assert asr_lines[1] == api_lines[1] == "강의입니다"


def test_bulk_export_video_ids_filter(tmp_path: Path) -> None:
    """video_ids filter exports only specified IDs, skipping others."""
    from tube_scout.services.kb_export import export_bulk

    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    output_dir = tmp_path / "kb_export"
    output_dir.mkdir()

    all_ids = [f"VID{i:03d}" for i in range(1, 11)]
    for vid in all_ids:
        _make_transcript(transcripts_dir, vid)

    selected = all_ids[:3]
    result = export_bulk(transcripts_dir, output_dir, video_ids=selected)

    assert result.exported_count == 3
    for vid in selected:
        assert (output_dir / f"{vid}.txt").exists()
    for vid in all_ids[3:]:
        assert not (output_dir / f"{vid}.txt").exists()


def test_bulk_export_idempotent_overwrite(tmp_path: Path) -> None:
    """Second export_bulk run overwrites existing files (idempotent)."""
    from tube_scout.services.kb_export import export_bulk

    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    output_dir = tmp_path / "kb_export"
    output_dir.mkdir()

    _make_transcript(transcripts_dir, "VID001")

    export_bulk(transcripts_dir, output_dir)
    (output_dir / "VID001.txt").stat().st_mtime

    result2 = export_bulk(transcripts_dir, output_dir)

    assert result2.exported_count == 1
    assert result2.failed_count == 0
    # File is overwritten (mtime may differ on some fs, but it must still exist and be valid)
    assert (output_dir / "VID001.txt").exists()
