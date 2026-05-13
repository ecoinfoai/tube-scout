"""T026 RED — takeout_ingest CSV parser unit tests (spec 013).

Covers:
 - split CSV (동영상.csv + 동영상(1).csv + ...) merge + dedup by video_id
 - duration_ms → duration_sec conversion
 - channel_id extraction from 채널.csv
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_video_row(
    video_id: str,
    title: str = "제목",
    duration_ms: int = 3600000,
    channel_id: str = "UCfake0001",
    privacy: str = "unlisted",
) -> list[str]:
    return [
        video_id,
        title,
        f"https://www.youtube.com/watch?v={video_id}",
        "2026-04-01T09:00:00Z",
        str(duration_ms),
        channel_id,
        "Education",
        privacy,
        "ko",
    ]


_VIDEO_HEADER = [
    "동영상 ID", "동영상 제목", "동영상 URL", "동영상 생성 타임스탬프",
    "근사치 길이(밀리초)", "채널 ID", "카테고리", "공개상태", "오디오 언어",
]
_CHANNEL_HEADER = ["채널 ID", "채널 이름", "채널 URL", "채널 핸들", "국가", "비공개 상태"]


def _write_video_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_VIDEO_HEADER)
        writer.writerows(rows)


def _write_channel_csv(path: Path, channel_id: str = "UCfake0001") -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_CHANNEL_HEADER)
        writer.writerow([channel_id, "Test Ch", f"https://www.youtube.com/channel/{channel_id}",
                         "@testch", "KR", "공개"])


def _make_takeout_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (takeout_root, meta_dir, channel_dir)."""
    yt = tmp_path / "YouTube 및 YouTube Music"
    meta_dir = yt / "동영상 메타데이터"
    meta_dir.mkdir(parents=True)
    channel_dir = yt / "채널"
    channel_dir.mkdir(parents=True)
    return tmp_path, meta_dir, channel_dir


# ---------------------------------------------------------------------------
# test 1: split CSVs merged and deduped
# ---------------------------------------------------------------------------

def test_split_csvs_merged_and_deduped(tmp_path: Path) -> None:
    """동영상.csv + 동영상(1).csv rows are merged; duplicate video_id produces one entry."""
    from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

    takeout_root, meta_dir, channel_dir = _make_takeout_dir(tmp_path)
    _write_channel_csv(channel_dir / "채널.csv")

    # 동영상.csv: vid001, vid002
    _write_video_csv(meta_dir / "동영상.csv", [
        _make_video_row("vid001", "영상1"),
        _make_video_row("vid002", "영상2"),
    ])
    # 동영상(1).csv: vid002 (dup), vid003
    _write_video_csv(meta_dir / "동영상(1).csv", [
        _make_video_row("vid002", "영상2"),
        _make_video_row("vid003", "영상3"),
    ])

    _channel, videos = parse_takeout_csv_metadata(takeout_root)

    ids = [v.video_id for v in videos]
    assert sorted(ids) == ["vid001", "vid002", "vid003"], (
        f"Expected 3 unique video_ids, got {ids}"
    )
    assert ids.count("vid002") == 1, "vid002 must appear exactly once after dedup"


# ---------------------------------------------------------------------------
# test 2: duration_ms converted to duration_sec
# ---------------------------------------------------------------------------

def test_duration_ms_converted_to_seconds(tmp_path: Path) -> None:
    """근사치 길이(밀리초) value is converted to duration_sec (float) on VideoMetadata."""
    from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

    takeout_root, meta_dir, channel_dir = _make_takeout_dir(tmp_path)
    _write_channel_csv(channel_dir / "채널.csv")
    _write_video_csv(meta_dir / "동영상.csv", [
        _make_video_row("vidA", duration_ms=3600000),
        _make_video_row("vidB", duration_ms=105000),
    ])

    _channel, videos = parse_takeout_csv_metadata(takeout_root)

    by_id = {v.video_id: v for v in videos}
    assert abs(by_id["vidA"].duration_sec - 3600.0) < 0.001, (
        f"Expected 3600.0s, got {by_id['vidA'].duration_sec}"
    )
    assert abs(by_id["vidB"].duration_sec - 105.0) < 0.001, (
        f"Expected 105.0s, got {by_id['vidB'].duration_sec}"
    )


# ---------------------------------------------------------------------------
# test 3: channel_id extracted from 채널.csv
# ---------------------------------------------------------------------------

def test_channel_id_extracted_from_channel_csv(tmp_path: Path) -> None:
    """ChannelMetadata.channel_id matches the 채널 ID column from 채널.csv."""
    from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

    takeout_root, meta_dir, channel_dir = _make_takeout_dir(tmp_path)
    _write_channel_csv(channel_dir / "채널.csv", channel_id="UCexpected001")
    _write_video_csv(meta_dir / "동영상.csv", [_make_video_row("vid001")])

    channel, _videos = parse_takeout_csv_metadata(takeout_root)

    assert channel.channel_id == "UCexpected001", (
        f"Expected channel_id='UCexpected001', got '{channel.channel_id}'"
    )


# ---------------------------------------------------------------------------
# test 4: missing 동영상.csv raises FileNotFoundError
# ---------------------------------------------------------------------------

def test_missing_video_csv_raises_file_not_found(tmp_path: Path) -> None:
    """FileNotFoundError raised when no 동영상*.csv exists under 동영상 메타데이터/."""
    from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

    takeout_root, _meta_dir, channel_dir = _make_takeout_dir(tmp_path)
    _write_channel_csv(channel_dir / "채널.csv")
    # No 동영상.csv written — directory exists but is empty

    with pytest.raises(FileNotFoundError):
        parse_takeout_csv_metadata(takeout_root)


# ---------------------------------------------------------------------------
# test 5: missing required column raises ValueError
# ---------------------------------------------------------------------------

def test_missing_required_column_raises_value_error(tmp_path: Path) -> None:
    """ValueError raised when 동영상 ID column is absent from the CSV."""
    from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

    takeout_root, meta_dir, channel_dir = _make_takeout_dir(tmp_path)
    _write_channel_csv(channel_dir / "채널.csv")

    # Write CSV with wrong header (missing 동영상 ID)
    bad_csv = meta_dir / "동영상.csv"
    with bad_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["wrong_col1", "wrong_col2"])
        writer.writerow(["v1", "title1"])

    with pytest.raises(ValueError):
        parse_takeout_csv_metadata(takeout_root)
