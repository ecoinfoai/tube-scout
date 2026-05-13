"""T083 RED — unit tests for kb_export format outputs."""
import json
from pathlib import Path

import pytest


def _write_transcript(tmp_path: Path, segments: list[dict], video_id: str = "vid001") -> Path:
    data = {
        "video_id": video_id,
        "source": "asr:whisper",
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "segments": segments,
    }
    p = tmp_path / f"{video_id}.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


_SEGMENTS = [
    {"start": 0.0, "end": 3.5, "text": "안녕하세요"},
    {"start": 3.5, "end": 8.2, "text": "오늘은 강의입니다"},
    {"start": 8.2, "end": 12.0, "text": "감사합니다"},
]


def test_txt_format_strips_timestamps_by_default(tmp_path: Path) -> None:
    """txt format default: no [hh:mm:ss] timestamps, one line per segment."""
    from tube_scout.services.kb_export import export_transcript

    transcript = _write_transcript(tmp_path, _SEGMENTS)
    out = tmp_path / "out.txt"
    export_transcript(transcript, out)

    content = out.read_text(encoding="utf-8")
    assert "[" not in content
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert lines == ["안녕하세요", "오늘은 강의입니다", "감사합니다"]


def test_txt_keep_timestamps_includes_brackets(tmp_path: Path) -> None:
    """txt format with keep_timestamps=True: each line starts with [HH:MM:SS]."""
    from tube_scout.services.kb_export import export_transcript

    transcript = _write_transcript(tmp_path, _SEGMENTS)
    out = tmp_path / "out.txt"
    export_transcript(transcript, out, keep_timestamps=True)

    content = out.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("[00:00:00]")
    assert lines[1].startswith("[00:00:03]")
    assert "안녕하세요" in lines[0]


def test_md_with_meta_includes_header(tmp_path: Path) -> None:
    """md format with with_meta=True: outputs # title header + meta block."""
    from tube_scout.services.kb_export import export_transcript
    from tube_scout.models.content import VideoMetadata
    import datetime

    vm = VideoMetadata(
        video_id="vid001",
        channel_id="UCtest",
        title="간호연구 8주차",
        duration_seconds=12.0,
        source="takeout",
        privacy_status="unlisted",
        ingested_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    transcript = _write_transcript(tmp_path, _SEGMENTS)
    out = tmp_path / "out.md"
    export_transcript(transcript, out, format_="md", with_meta=True, video_meta=vm)

    content = out.read_text(encoding="utf-8")
    assert content.startswith("# 간호연구 8주차")
    assert "video_id:" in content
    assert "vid001" in content
    assert "---" in content
    assert "안녕하세요" in content


def test_md_without_meta_body_only(tmp_path: Path) -> None:
    """md format without with_meta: no # header, plain text body."""
    from tube_scout.services.kb_export import export_transcript

    transcript = _write_transcript(tmp_path, _SEGMENTS)
    out = tmp_path / "out.md"
    export_transcript(transcript, out, format_="md", with_meta=False)

    content = out.read_text(encoding="utf-8")
    assert not content.startswith("#")
    assert "안녕하세요" in content


def test_jsonl_per_segment_one_line(tmp_path: Path) -> None:
    """jsonl format: one JSON object per line, no timestamps by default."""
    from tube_scout.services.kb_export import export_transcript

    transcript = _write_transcript(tmp_path, _SEGMENTS)
    out = tmp_path / "out.jsonl"
    export_transcript(transcript, out, format_="jsonl")

    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3
    obj = json.loads(lines[0])
    assert "text" in obj
    assert "start" not in obj
    assert "end" not in obj


def test_jsonl_with_meta_first_line_is_meta_object(tmp_path: Path) -> None:
    """jsonl with_meta=True: first line has _meta key, followed by segment lines."""
    from tube_scout.services.kb_export import export_transcript
    from tube_scout.models.content import VideoMetadata
    import datetime

    vm = VideoMetadata(
        video_id="vid001",
        channel_id="UCtest",
        title="테스트 강의",
        duration_seconds=12.0,
        source="takeout",
        ingested_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    transcript = _write_transcript(tmp_path, _SEGMENTS)
    out = tmp_path / "out.jsonl"
    export_transcript(transcript, out, format_="jsonl", with_meta=True, video_meta=vm)

    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 4  # 1 meta + 3 segments
    meta = json.loads(lines[0])
    assert meta.get("_meta") is True
    assert "video_id" in meta
    seg = json.loads(lines[1])
    assert "text" in seg


def test_clean_fillers_removes_korean_filler_patterns(tmp_path: Path) -> None:
    """clean_fillers=True removes Korean ASR filler expressions."""
    from tube_scout.services.kb_export import export_transcript

    segments = [
        {"start": 0.0, "end": 3.0, "text": "음 안녕하세요 어 오늘은"},
        {"start": 3.0, "end": 6.0, "text": "에 강의입니다 아 그러니까"},
    ]
    transcript = _write_transcript(tmp_path, segments)
    out = tmp_path / "out.txt"
    export_transcript(transcript, out, clean_fillers=True)

    content = out.read_text(encoding="utf-8")
    for filler in ["음 ", " 어 ", " 에 ", " 아 "]:
        assert filler not in content, f"Filler '{filler}' was not removed"
    assert "안녕하세요" in content
    assert "강의입니다" in content


def test_output_utf8_no_bom(tmp_path: Path) -> None:
    """Output file must be UTF-8 without BOM (FR-040)."""
    from tube_scout.services.kb_export import export_transcript

    segments = [{"start": 0.0, "end": 2.0, "text": "한글 테스트"}]
    transcript = _write_transcript(tmp_path, segments)
    out = tmp_path / "out.txt"
    export_transcript(transcript, out)

    raw_bytes = out.read_bytes()
    assert not raw_bytes.startswith(b"\xef\xbb\xbf"), "BOM detected — must use encoding='utf-8'"
    assert "한글 테스트" in raw_bytes.decode("utf-8")
