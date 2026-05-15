"""T026 RED — takeout_ingest CSV parser unit tests (spec 013).
T005 RED — _PRIVACY_MAPPING constant in takeout_ingest module (R-4, FR-005).

Covers:
 - split CSV (동영상.csv + 동영상(1).csv + ...) merge + dedup by video_id
 - duration_ms → duration_sec conversion
 - channel_id extraction from 채널.csv
 - _PRIVACY_MAPPING Korean→English privacy status translation
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_VIDEO_HEADER = [
    "동영상 ID", "근사치 길이(밀리초)", "동영상 오디오 언어", "동영상 카테고리",
    "동영상 설명(원본) 언어", "채널 ID", "동영상 제목(원본)", "동영상 제목(원본) 언어",
    "개인 정보 보호", "동영상 상태", "동영상 생성 타임스탬프",
]
_CHANNEL_HEADER = ["채널 ID", "채널 국가", "채널 태그 1", "채널 제목(원본)", "채널 공개 상태"]


def _make_video_row(
    video_id: str,
    title: str = "제목",
    duration_ms: int = 3600000,
    channel_id: str = "UCfake0001",
    privacy: str = "일부 공개",
) -> dict:
    return {
        "동영상 ID": video_id,
        "근사치 길이(밀리초)": str(duration_ms),
        "동영상 오디오 언어": "ko",
        "동영상 카테고리": "교육",
        "동영상 설명(원본) 언어": "ko",
        "채널 ID": channel_id,
        "동영상 제목(원본)": title,
        "동영상 제목(원본) 언어": "ko",
        "개인 정보 보호": privacy,
        "동영상 상태": "처리됨",
        "동영상 생성 타임스탬프": "2026-04-01T09:00:00+00:00",
    }


def _write_video_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_VIDEO_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _write_channel_csv(path: Path, channel_id: str = "UCfake0001") -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_CHANNEL_HEADER)
        writer.writerow([channel_id, "KR", "태그", "Test Ch", "공개"])


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
    assert abs(by_id["vidA"].duration_seconds - 3600.0) < 0.001, (
        f"Expected 3600.0s, got {by_id['vidA'].duration_seconds}"
    )
    assert abs(by_id["vidB"].duration_seconds - 105.0) < 0.001, (
        f"Expected 105.0s, got {by_id['vidB'].duration_seconds}"
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


# ─── T005 RED: _PRIVACY_MAPPING constant ─────────────────────────────────────

def test_privacy_mapping_exists():
    from tube_scout.services.takeout_ingest import _PRIVACY_MAPPING

    assert isinstance(_PRIVACY_MAPPING, dict)


def test_privacy_mapping_korean_to_english():
    from tube_scout.services.takeout_ingest import _PRIVACY_MAPPING

    assert _PRIVACY_MAPPING["공개"] == "public"
    assert _PRIVACY_MAPPING["일부 공개"] == "unlisted"
    assert _PRIVACY_MAPPING["비공개"] == "private"


def test_privacy_mapping_covers_all_three_statuses():
    from tube_scout.services.takeout_ingest import _PRIVACY_MAPPING

    assert set(_PRIVACY_MAPPING.values()) == {"public", "unlisted", "private"}
