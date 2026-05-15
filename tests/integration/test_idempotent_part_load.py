"""Integration tests — multi-part archive idempotent ingestion (T049-T051, US3).

SC-005: second ingest of the same archive produces new_videos=0, no DB row count change,
no new mp4 symlinks.  R-8: first-write-wins for duplicate video_id.  FR-020: new
video_id present only in part-2 archive is appended on second call.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Shared fixture paths
# ---------------------------------------------------------------------------

_SAMPLE = (
    Path(__file__).parent.parent / "fixtures" / "takeout_sample"
)

_CHANNEL_ID = "UCfakeAnonChan0123456789"

_CHANNEL_CSV_HEADER = "채널 ID,채널 국가,채널 태그 1,채널 제목(원본),채널 공개 상태\n"
_CHANNEL_CSV_ROW = f"{_CHANNEL_ID},KR,태그,Test Channel,공개\n"

_VIDEO_CSV_HEADER = (
    "동영상 ID,근사치 길이(밀리초),동영상 오디오 언어,동영상 카테고리,"
    "동영상 설명(원본) 언어,채널 ID,동영상 제목(원본),동영상 제목(원본) 언어,"
    "개인 정보 보호,동영상 상태,동영상 생성 타임스탬프\n"
)


def _make_video_row(
    video_id: str,
    title: str,
    privacy: str = "일부 공개",
    channel_id: str = _CHANNEL_ID,
) -> str:
    return (
        f"{video_id},3600000,ko,교육,ko,{channel_id},{title},ko,"
        f"{privacy},처리됨,2026-04-01T09:00:00+00:00\n"
    )


def _build_takeout_dir(
    base: Path,
    video_rows: list[tuple[str, str]],
    mp4_names: list[str] | None = None,
) -> Path:
    """Create a minimal Takeout directory tree.

    Args:
        base: Parent directory for the archive.
        video_rows: List of (video_id, title) tuples for 동영상.csv.
        mp4_names: mp4 filenames to create as empty files in 동영상/.

    Returns:
        Path to the archive root (parent of Takeout/).
    """
    yt = base / "Takeout" / "YouTube 및 YouTube Music"
    channel_dir = yt / "채널"
    meta_dir = yt / "동영상 메타데이터"
    video_dir = yt / "동영상"
    for d in (channel_dir, meta_dir, video_dir):
        d.mkdir(parents=True, exist_ok=True)

    (channel_dir / "채널.csv").write_text(
        _CHANNEL_CSV_HEADER + _CHANNEL_CSV_ROW, encoding="utf-8"
    )

    rows = _VIDEO_CSV_HEADER + "".join(
        _make_video_row(vid, title) for vid, title in video_rows
    )
    (meta_dir / "동영상.csv").write_text(rows, encoding="utf-8")

    for name in mp4_names or []:
        (video_dir / name).write_bytes(b"")

    return base


def _mock_registry() -> dict:
    reg = MagicMock()
    reg.channel_id = _CHANNEL_ID
    return {"test-channel": reg}


# ---------------------------------------------------------------------------
# T049: second identical ingest → new_videos=0, DB row count unchanged
# ---------------------------------------------------------------------------


class TestIdempotentSameArchive:
    """T049 — SC-005: duplicate ingest of the same archive is a no-op."""

    def test_second_ingest_new_videos_zero(self, tmp_path: Path) -> None:
        """Second ingest of identical archive must return new_videos=0."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        archive = _build_takeout_dir(
            tmp_path / "archive1",
            [("vid-A", "Video A"), ("vid-B", "Video B")],
        )
        work_root = tmp_path / "work"
        db_path = work_root / "content_reuse.db"

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value=_mock_registry(),
        ):
            first = ingest_takeout(
                takeout_dir=archive,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )
            second = ingest_takeout(
                takeout_dir=archive,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )

        assert first.new_videos == 2
        assert second.new_videos == 0, (
            f"Expected new_videos=0 on second ingest, got {second.new_videos}"
        )

    def test_second_ingest_db_row_count_unchanged(self, tmp_path: Path) -> None:
        """SQLite video_metadata row count must not increase on second ingest."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        archive = _build_takeout_dir(
            tmp_path / "archive1",
            [("vid-A", "Video A"), ("vid-B", "Video B")],
        )
        work_root = tmp_path / "work"
        db_path = work_root / "content_reuse.db"

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value=_mock_registry(),
        ):
            ingest_takeout(
                takeout_dir=archive,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )
            with sqlite3.connect(db_path) as conn:
                count_after_first = conn.execute(
                    "SELECT COUNT(*) FROM video_metadata"
                ).fetchone()[0]

            ingest_takeout(
                takeout_dir=archive,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )
            with sqlite3.connect(db_path) as conn:
                count_after_second = conn.execute(
                    "SELECT COUNT(*) FROM video_metadata"
                ).fetchone()[0]

        assert count_after_second == count_after_first, (
            f"DB row count changed: {count_after_first} → {count_after_second}"
        )

    def test_second_ingest_no_new_mp4_symlinks(self, tmp_path: Path) -> None:
        """mp4 symlinks must not multiply on second ingest."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        archive = _build_takeout_dir(
            tmp_path / "archive1",
            [("vid-A", "Video A")],
            mp4_names=["vid-A.mp4"],
        )
        work_root = tmp_path / "work"
        db_path = work_root / "content_reuse.db"

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value=_mock_registry(),
        ):
            ingest_takeout(
                takeout_dir=archive,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=True,
                dry_run=False,
            )
            video_dir = work_root / "test-channel" / "동영상"
            mp4_count_after_first = len(list(video_dir.glob("*.mp4")))

            ingest_takeout(
                takeout_dir=archive,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=True,
                dry_run=False,
            )
            mp4_count_after_second = len(list(video_dir.glob("*.mp4")))

        assert mp4_count_after_second == mp4_count_after_first, (
            f"mp4 count changed: {mp4_count_after_first} → {mp4_count_after_second}"
        )


# ---------------------------------------------------------------------------
# T050: duplicate video_id with different title → first-write-wins (R-8)
# ---------------------------------------------------------------------------


class TestFirstWriteWins:
    """T050 — R-8: first-write-wins for duplicate video_id across parts."""

    def test_duplicate_video_id_title_not_overwritten(self, tmp_path: Path) -> None:
        """part-2 title for same video_id must not overwrite part-1 title in DB."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        part1 = _build_takeout_dir(
            tmp_path / "part1",
            [("vid-X", "Original Title")],
        )
        part2 = _build_takeout_dir(
            tmp_path / "part2",
            [("vid-X", "Different Title From Part2")],
        )
        work_root = tmp_path / "work"
        db_path = work_root / "content_reuse.db"

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value=_mock_registry(),
        ):
            ingest_takeout(
                takeout_dir=part1,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )
            ingest_takeout(
                takeout_dir=part2,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )

        with sqlite3.connect(db_path) as conn:
            title = conn.execute(
                "SELECT title FROM video_metadata WHERE video_id = ?", ("vid-X",)
            ).fetchone()[0]

        assert title == "Original Title", (
            f"Expected 'Original Title' (first-write-wins), got {title!r}"
        )

    def test_duplicate_video_id_no_audit_conflict_row(self, tmp_path: Path) -> None:
        """Second ingest of duplicate video_id must not produce an audit conflict row."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        part1 = _build_takeout_dir(
            tmp_path / "part1",
            [("vid-X", "Original Title")],
        )
        part2 = _build_takeout_dir(
            tmp_path / "part2",
            [("vid-X", "Different Title")],
        )
        work_root = tmp_path / "work"
        db_path = work_root / "content_reuse.db"

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value=_mock_registry(),
        ):
            ingest_takeout(
                takeout_dir=part1,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )
            ingest_takeout(
                takeout_dir=part2,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )

        audit_csv = work_root / "test-channel" / "01_collect" / "takeout_ingest_audit.csv"
        assert audit_csv.exists()
        with audit_csv.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        conflict_rows = [r for r in rows if r.get("reason") == "duplicate_conflict"]
        assert conflict_rows == [], (
            f"Expected 0 conflict audit rows, found {len(conflict_rows)}"
        )


# ---------------------------------------------------------------------------
# T051: part-2 has new video_id → new_videos > 0, new mp4 symlink added
# ---------------------------------------------------------------------------


class TestNewVideoInPart2:
    """T051 — FR-020: new video_id in part-2 archive is appended."""

    def test_new_video_id_in_part2_increases_new_videos(
        self, tmp_path: Path
    ) -> None:
        """part-2 with additional video_id must result in new_videos > 0."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        part1 = _build_takeout_dir(
            tmp_path / "part1",
            [("vid-A", "Video A")],
        )
        part2 = _build_takeout_dir(
            tmp_path / "part2",
            [("vid-A", "Video A"), ("vid-NEW", "New Video")],
        )
        work_root = tmp_path / "work"
        db_path = work_root / "content_reuse.db"

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value=_mock_registry(),
        ):
            ingest_takeout(
                takeout_dir=part1,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )
            second = ingest_takeout(
                takeout_dir=part2,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )

        assert second.new_videos > 0, (
            f"Expected new_videos > 0 when part-2 has a new video_id, "
            f"got {second.new_videos}"
        )

    def test_new_video_mp4_symlink_added(self, tmp_path: Path) -> None:
        """New mp4 in part-2 must be symlinked; existing mp4 symlink must survive."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        part1 = _build_takeout_dir(
            tmp_path / "part1",
            [("vid-A", "Video A")],
            mp4_names=["vid-A.mp4"],
        )
        part2 = _build_takeout_dir(
            tmp_path / "part2",
            [("vid-A", "Video A"), ("vid-NEW", "New Video")],
            mp4_names=["vid-A.mp4", "vid-NEW.mp4"],
        )
        work_root = tmp_path / "work"
        db_path = work_root / "content_reuse.db"

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value=_mock_registry(),
        ):
            ingest_takeout(
                takeout_dir=part1,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=True,
                dry_run=False,
            )
            video_dir = work_root / "test-channel" / "동영상"
            mp4_count_after_first = len(list(video_dir.glob("*.mp4")))

            ingest_takeout(
                takeout_dir=part2,
                channel_alias="test-channel",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=True,
                dry_run=False,
            )
            mp4_count_after_second = len(list(video_dir.glob("*.mp4")))

        assert mp4_count_after_second > mp4_count_after_first, (
            f"Expected new mp4 symlink added in part-2: "
            f"{mp4_count_after_first} → {mp4_count_after_second}"
        )
        assert (video_dir / "vid-A.mp4").exists(), "Existing vid-A.mp4 must survive"
        assert (video_dir / "vid-NEW.mp4").exists(), "New vid-NEW.mp4 must be added"
