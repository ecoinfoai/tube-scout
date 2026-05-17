"""RED tests for takeout_ingest service — defect regression matrix (T008-T014).

Defects covered:
  - Defect 3: 채널.csv real headers (채널 제목(원본), 채널 국가, 채널 공개 상태)
  - Defect 4: 동영상.csv real headers (동영상 제목(원본), 동영상 오디오 언어, etc.)
  - Defect 6: 채널 제목(원본) column absent → explicit ValueError (not silent None)
  - Defect 8: ignored CSV categories audit rows
  - Defect 12: yt_dir auto-discovery (archive root vs Takeout/ itself)
  - FR-010/SC-007: title round-trip fidelity
  - FR-022: IngestResult mp4_present_count, mp4_absent_count, elapsed_seconds fields
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# helpers: minimal fixture builders matching real Takeout CSV format
# ---------------------------------------------------------------------------

_REAL_CHANNEL_HEADER = [
    "채널 ID", "채널 국가", "채널 태그 1", "채널 제목(원본)", "채널 공개 상태",
]

_REAL_VIDEO_HEADER = [
    "동영상 ID", "근사치 길이(밀리초)", "동영상 오디오 언어", "동영상 카테고리",
    "동영상 설명(원본) 언어", "채널 ID", "동영상 제목(원본)", "동영상 제목(원본) 언어",
    "개인 정보 보호", "동영상 상태", "동영상 생성 타임스탬프",
]


def _write_channel_csv(path: Path, channel_id: str = "UCtest001", country: str = "KR",
                       title: str = "테스트 채널", privacy: str = "공개") -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_REAL_CHANNEL_HEADER)
        w.writerow([channel_id, country, "태그1", title, privacy])


def _write_video_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_REAL_VIDEO_HEADER)
        w.writeheader()
        w.writerows(rows)


def _video_row(
    video_id: str,
    title: str = "제목",
    duration_ms: int = 3600000,
    channel_id: str = "UCtest001",
    language: str = "ko",
    category: str = "교육",
    privacy: str = "비공개",
    timestamp: str = "2026-01-01T00:00:00+00:00",
) -> dict:
    return {
        "동영상 ID": video_id,
        "근사치 길이(밀리초)": str(duration_ms),
        "동영상 오디오 언어": language,
        "동영상 카테고리": category,
        "동영상 설명(원본) 언어": "ko",
        "채널 ID": channel_id,
        "동영상 제목(원본)": title,
        "동영상 제목(원본) 언어": "ko",
        "개인 정보 보호": privacy,
        "동영상 상태": "처리됨",
        "동영상 생성 타임스탬프": timestamp,
    }


def _make_takeout_tree(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Build Takeout dir structure; return (takeout_root, yt_dir, meta_dir, channel_dir)."""
    yt_dir = tmp_path / "YouTube 및 YouTube Music"
    meta_dir = yt_dir / "동영상 메타데이터"
    channel_dir = yt_dir / "채널"
    meta_dir.mkdir(parents=True)
    channel_dir.mkdir(parents=True)
    return tmp_path, yt_dir, meta_dir, channel_dir


# ---------------------------------------------------------------------------
# T008: Defect 3 + Defect 12
# ---------------------------------------------------------------------------

class TestDefect3RealChannelHeaders:
    """T008 — real 채널.csv headers produce correct ChannelMetadata fields."""

    def test_channel_title_from_real_header(self, tmp_path: Path) -> None:
        """title must come from the '채널 제목(원본)' column, not '채널 이름'."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, _, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv", title="부산보건대 간호학과")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vid001")])

        channel, _ = parse_takeout_csv_metadata(takeout_root)
        assert channel.title == "부산보건대 간호학과"

    def test_channel_country_from_real_header(self, tmp_path: Path) -> None:
        """country must come from the '채널 국가' column, not '국가'."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, _, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv", country="KR")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vid001")])

        channel, _ = parse_takeout_csv_metadata(takeout_root)
        assert channel.country == "KR"

    def test_defect12_archive_root_auto_discovery(self, tmp_path: Path) -> None:
        """Passing archive root (parent of Takeout/) must work the same as Takeout/ itself."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        # Build structure: tmp_path/Takeout/YouTube 및 YouTube Music/...
        takeout_dir = tmp_path / "Takeout"
        yt_dir = takeout_dir / "YouTube 및 YouTube Music"
        meta_dir = yt_dir / "동영상 메타데이터"
        channel_dir = yt_dir / "채널"
        meta_dir.mkdir(parents=True)
        channel_dir.mkdir(parents=True)
        _write_channel_csv(channel_dir / "채널.csv", title="테스트채널")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vid001")])

        # Pass archive root (tmp_path), not Takeout/ itself
        channel, videos = parse_takeout_csv_metadata(tmp_path)
        assert channel.title == "테스트채널"
        assert len(videos) == 1

    def test_defect12_takeout_dir_itself_also_works(self, tmp_path: Path) -> None:
        """Passing Takeout/ directly must also work."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, _, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv", title="채널직접")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vid001")])

        channel, videos = parse_takeout_csv_metadata(takeout_root)
        assert channel.title == "채널직접"
        assert len(videos) == 1


# ---------------------------------------------------------------------------
# T009: Defect 4 — real video CSV column mapping
# ---------------------------------------------------------------------------

class TestDefect4RealVideoHeaders:
    """T009 — real 동영상.csv column names produce correct VideoMetadata fields."""

    def test_title_from_real_column(self, tmp_path: Path) -> None:
        """title must come from the '동영상 제목(원본)' column, not '동영상 제목'."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, _, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vidA", title="실제 강의 제목")])

        _, videos = parse_takeout_csv_metadata(takeout_root)
        assert videos[0].title == "실제 강의 제목"

    def test_language_from_real_column(self, tmp_path: Path) -> None:
        """language must come from the '동영상 오디오 언어' column, not '오디오 언어'."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, _, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vidA", language="ko")])

        _, videos = parse_takeout_csv_metadata(takeout_root)
        assert videos[0].language == "ko"

    def test_category_from_real_column(self, tmp_path: Path) -> None:
        """category must come from the '동영상 카테고리' column, not '카테고리'."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, _, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vidA", category="교육")])

        _, videos = parse_takeout_csv_metadata(takeout_root)
        assert videos[0].category == "교육"

    def test_no_error_when_video_url_column_absent(self, tmp_path: Path) -> None:
        """Real CSV has no '동영상 URL' column — must not raise."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, _, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        # Real header does NOT include '동영상 URL'
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vidA")])

        _, videos = parse_takeout_csv_metadata(takeout_root)
        assert len(videos) == 1


# ---------------------------------------------------------------------------
# T010: Defect 6 — _parse_channel_csv missing column raises ValueError
# ---------------------------------------------------------------------------

class TestDefect6ChannelMissingColumn:
    """T010 — a missing '채널 제목(원본)' column raises an explicit ValueError instead of returning None."""

    def test_missing_title_column_raises_value_error(self, tmp_path: Path) -> None:
        from tube_scout.services.takeout_ingest import (
            _parse_channel_csv,  # type: ignore[attr-defined]
        )

        bad_csv = tmp_path / "채널.csv"
        with bad_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["채널 ID", "채널 국가"])  # missing 채널 제목(원본)
            w.writerow(["UCtest", "KR"])

        with pytest.raises(ValueError, match="채널 제목"):
            _parse_channel_csv(bad_csv)

    def test_missing_channel_id_column_raises_value_error(self, tmp_path: Path) -> None:
        from tube_scout.services.takeout_ingest import (
            _parse_channel_csv,  # type: ignore[attr-defined]
        )

        bad_csv = tmp_path / "채널.csv"
        with bad_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["채널 제목(원본)", "채널 국가"])  # missing 채널 ID
            w.writerow(["채널명", "KR"])

        with pytest.raises(ValueError):
            _parse_channel_csv(bad_csv)


# ---------------------------------------------------------------------------
# T012: Defect 8 — ignored CSV categories → audit rows
# ---------------------------------------------------------------------------

class TestDefect8IgnoredCsvAudit:
    """T012 — '동영상 녹화*.csv' and '동영상 텍스트*.csv' are skipped with audit rows."""

    def test_ignored_csvs_produce_skip_audit_rows(self, tmp_path: Path) -> None:
        """동영상.csv is parsed; 동영상 녹화.csv + 동영상 텍스트.csv produce skip audit rows."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, yt_dir, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vid001")])

        # Add ignored category files in meta_dir (they coexist with 동영상*.csv)
        (meta_dir / "동영상 녹화.csv").write_text("ignored\n", encoding="utf-8")
        (meta_dir / "동영상 텍스트.csv").write_text("ignored\n", encoding="utf-8")

        # parse_takeout_csv_metadata must only parse 동영상*.csv (not 녹화/텍스트)
        _, videos = parse_takeout_csv_metadata(takeout_root)
        assert len(videos) == 1  # only vid001 from 동영상.csv

    def test_ignored_video_subfolders_counted_in_ingest_result(self, tmp_path: Path) -> None:
        """ingest_takeout() ignored_csv_count reflects ignored categories under yt_dir."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        takeout_root, yt_dir, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vid001")])

        # Create ignored sub-dirs (these directory names must match the _is_ignored pattern)
        (yt_dir / "동영상 녹화").mkdir()
        (yt_dir / "동영상 텍스트").mkdir()

        db_path = tmp_path / "test.db"
        work_root = tmp_path / "data"

        import unittest.mock as mock
        with mock.patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"nursing": mock.MagicMock(channel_id="UCtest001")},
        ):
            result = ingest_takeout(
                takeout_dir=takeout_root,
                channel_alias="nursing",
                db_path=db_path,
                work_root=work_root,
                dry_run=True,
            )
        assert result.ignored_csv_count >= 2


# ---------------------------------------------------------------------------
# T013: FR-010/SC-007 — title round-trip fidelity
# ---------------------------------------------------------------------------

class TestTitleRoundTripFidelity:
    """T013 — title with commas, quotes, whitespace survives CSV parse unchanged."""

    @pytest.mark.parametrize("raw_title", [
        "25-1. 홍길동 융합헬스케어4.0 1주차 1차시-1 (간호학과)",
        'Title with "quotes" inside',
        "Title, with, commas",
        "  leading and trailing  ",
        "간호학과 & 의료공학과 : 복합 세션",
    ])
    def test_title_fidelity(self, tmp_path: Path, raw_title: str) -> None:
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, _, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        _write_video_csv(meta_dir / "동영상.csv", [_video_row("vid001", title=raw_title)])

        _, videos = parse_takeout_csv_metadata(takeout_root)
        # strip() is acceptable for leading/trailing whitespace
        assert videos[0].title.strip() == raw_title.strip()


# ---------------------------------------------------------------------------
# T014: FR-022 — IngestResult extra fields
# ---------------------------------------------------------------------------

class TestIngestResultExtraFields:
    """T014 — IngestResult must include mp4_present_count, mp4_absent_count, elapsed_seconds."""

    def test_ingest_result_has_mp4_present_count(self) -> None:
        from tube_scout.services.takeout_ingest import IngestResult

        fields = IngestResult.model_fields
        assert "mp4_present_count" in fields, "IngestResult missing mp4_present_count"

    def test_ingest_result_has_mp4_absent_count(self) -> None:
        from tube_scout.services.takeout_ingest import IngestResult

        fields = IngestResult.model_fields
        assert "mp4_absent_count" in fields, "IngestResult missing mp4_absent_count"

    def test_ingest_result_has_elapsed_seconds(self) -> None:
        from tube_scout.services.takeout_ingest import IngestResult

        fields = IngestResult.model_fields
        assert "elapsed_seconds" in fields, "IngestResult missing elapsed_seconds"

    def test_ingest_result_mp4_counts_sum_equals_total(self, tmp_path: Path) -> None:
        """mp4_present_count + mp4_absent_count must equal total_videos."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        takeout_root, yt_dir, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        # 3 videos in metadata, 0 mp4 files in archive
        _write_video_csv(meta_dir / "동영상.csv", [
            _video_row("vid001"),
            _video_row("vid002"),
            _video_row("vid003"),
        ])

        import unittest.mock as mock
        with mock.patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"nursing": mock.MagicMock(channel_id="UCtest001")},
        ):
            result = ingest_takeout(
                takeout_dir=takeout_root,
                channel_alias="nursing",
                db_path=tmp_path / "test.db",
                work_root=tmp_path / "data",
                dry_run=True,
            )

        assert result.mp4_present_count + result.mp4_absent_count == result.total_videos
        assert result.elapsed_seconds >= 0.0
