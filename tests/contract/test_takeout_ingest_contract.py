"""Contract tests — takeout_ingest service signatures (spec 013 T025 RED).

FR-001~FR-009: parse_takeout_csv_metadata, assemble_channel_work_dir, ingest_takeout.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

FIXTURE_TAKEOUT = Path(__file__).parent.parent / "fixtures" / "takeout_sample" / "Takeout"
_YT_DIR = FIXTURE_TAKEOUT / "YouTube 및 YouTube Music"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_dup_video_csv(takeout_dir: Path) -> Path:
    """Return a takeout_dir containing a 동영상.csv with one duplicate video_id row."""
    yt = takeout_dir / "YouTube 및 YouTube Music"
    meta_dir = yt / "동영상 메타데이터"
    meta_dir.mkdir(parents=True, exist_ok=True)
    video_csv = meta_dir / "동영상.csv"
    rows = [
        ["동영상 ID", "동영상 제목", "동영상 URL", "동영상 생성 타임스탬프",
         "근사치 길이(밀리초)", "채널 ID", "카테고리", "공개상태", "오디오 언어"],
        ["dup0000001", "중복영상A", "https://www.youtube.com/watch?v=dup0000001",
         "2026-04-01T09:00:00Z", "3600000", "UCdup000001", "Education", "unlisted", "ko"],
        ["dup0000001", "중복영상A", "https://www.youtube.com/watch?v=dup0000001",
         "2026-04-01T09:00:00Z", "3600000", "UCdup000001", "Education", "unlisted", "ko"],
        ["dup0000002", "중복영상B", "https://www.youtube.com/watch?v=dup0000002",
         "2026-04-02T09:00:00Z", "1800000", "UCdup000001", "Education", "unlisted", "ko"],
    ]
    channel_dir = yt / "채널"
    channel_dir.mkdir(parents=True, exist_ok=True)
    channel_csv = channel_dir / "채널.csv"
    with channel_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["채널 ID", "채널 이름", "채널 URL", "채널 핸들", "국가", "비공개 상태"])
        writer.writerow(["UCdup000001", "Dup Channel", "https://www.youtube.com/channel/UCdup000001",
                         "@duphandle", "KR", "공개"])
    with video_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return takeout_dir


def _write_ignored_category_csvs(takeout_dir: Path) -> Path:
    """Return takeout_dir with all FR-008 ignored-category CSV files present."""
    yt = takeout_dir / "YouTube 및 YouTube Music"
    ignored = [
        "동영상 녹화.csv",
        "동영상 텍스트.csv",
        "댓글.csv",
        "재생목록.csv",
        "구독정보.csv",
    ]
    for name in ignored:
        (yt / name).write_text("col1,col2\nval1,val2\n", encoding="utf-8")
    return takeout_dir


# ---------------------------------------------------------------------------
# T025-1: parse_takeout_csv_metadata — dedup by video_id
# ---------------------------------------------------------------------------

def test_parse_takeout_csv_metadata_returns_dedup_video_list(tmp_path: Path) -> None:
    """Duplicate video_id rows are collapsed to a single VideoMetadata entry."""
    from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

    _write_dup_video_csv(tmp_path)
    _channel, videos = parse_takeout_csv_metadata(tmp_path)
    ids = [v.video_id for v in videos]
    assert len(ids) == len(set(ids)), "duplicate video_id rows must be dedup'd"
    assert "dup0000001" in ids
    assert "dup0000002" in ids
    assert ids.count("dup0000001") == 1


# ---------------------------------------------------------------------------
# T025-2: assemble_channel_work_dir — symlinks created
# ---------------------------------------------------------------------------

def test_assemble_channel_work_dir_creates_symlinks(tmp_path: Path) -> None:
    """assemble_channel_work_dir creates mp4 symlinks under <work_root>/<alias>/동영상/."""
    from tube_scout.services.takeout_ingest import assemble_channel_work_dir

    work_root = tmp_path / "data"
    work_root.mkdir()

    work_dir = assemble_channel_work_dir(
        takeout_dir=FIXTURE_TAKEOUT,
        channel_alias="test_channel",
        work_root=work_root,
        use_symlinks=True,
    )

    assert work_dir.exists(), "work_dir must be created"
    mp4_links = list(work_dir.rglob("*.mp4"))
    assert len(mp4_links) > 0, "at least one mp4 symlink must be created"
    for link in mp4_links:
        assert link.is_symlink(), f"{link} must be a symlink"


# ---------------------------------------------------------------------------
# T025-3: ingest_takeout — unknown alias raises ValueError
# ---------------------------------------------------------------------------

def test_ingest_takeout_rejects_unknown_alias(tmp_path: Path) -> None:
    """ingest_takeout raises ValueError when channel_alias is not registered."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    with pytest.raises(ValueError, match="alias"):
        ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias="__no_such_alias_xyz__",
            db_path=db_path,
            work_root=work_root,
        )


# ---------------------------------------------------------------------------
# T025-4: ingest_takeout — idempotent two runs
# ---------------------------------------------------------------------------

def test_ingest_takeout_idempotent_two_runs(tmp_path: Path) -> None:
    """Running ingest_takeout twice on the same takeout produces the same DB row count."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    # First run
    result1 = ingest_takeout(
        takeout_dir=FIXTURE_TAKEOUT,
        channel_alias="test_channel",
        db_path=db_path,
        work_root=work_root,
    )
    with sqlite3.connect(db_path) as conn:
        row_count_1 = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]

    # Second run — same takeout, idempotent
    result2 = ingest_takeout(
        takeout_dir=FIXTURE_TAKEOUT,
        channel_alias="test_channel",
        db_path=db_path,
        work_root=work_root,
    )
    with sqlite3.connect(db_path) as conn:
        row_count_2 = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]

    assert row_count_1 == row_count_2, (
        f"Row count must be stable across runs: first={row_count_1}, second={row_count_2}"
    )
    assert result1.total_videos == result2.total_videos
    assert result2.new_videos == 0, "second run must report 0 new_videos (all already ingested)"


# ---------------------------------------------------------------------------
# T025-5: ingest_takeout — dry_run writes 0 DB rows
# ---------------------------------------------------------------------------

def test_ingest_takeout_dry_run_no_db_write(tmp_path: Path) -> None:
    """dry_run=True must not write any rows to SQLite."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    result = ingest_takeout(
        takeout_dir=FIXTURE_TAKEOUT,
        channel_alias="test_channel",
        db_path=db_path,
        work_root=work_root,
        dry_run=True,
    )

    assert result.dry_run is True, "IngestResult.dry_run must be True"
    assert not db_path.exists() or _video_metadata_count(db_path) == 0, (
        "dry_run must not persist any video_metadata rows"
    )


def _video_metadata_count(db_path: Path) -> int:
    """Return number of rows in video_metadata, or 0 if table does not exist."""
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "video_metadata" not in tables:
            return 0
        return conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]


# ---------------------------------------------------------------------------
# T025-6: FR-008 ignored category CSVs — audit rows logged
# ---------------------------------------------------------------------------

def test_ignored_categories_audit_logged(tmp_path: Path) -> None:
    """All FR-008 ignored-category CSV files produce audit rows with reason='ignored_by_policy'."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    _write_ignored_category_csvs(tmp_path)

    # Copy the minimal valid takeout structure into tmp_path
    import shutil
    src_yt = FIXTURE_TAKEOUT / "YouTube 및 YouTube Music"
    dst_yt = tmp_path / "YouTube 및 YouTube Music"
    if not dst_yt.exists():
        shutil.copytree(str(src_yt), str(dst_yt))
    else:
        # Merge: copy 채널 and 동영상 메타데이터 if missing
        for sub in ["채널", "동영상 메타데이터", "동영상"]:
            src_sub = src_yt / sub
            dst_sub = dst_yt / sub
            if not dst_sub.exists() and src_sub.exists():
                shutil.copytree(str(src_sub), str(dst_sub))

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir(exist_ok=True)

    result = ingest_takeout(
        takeout_dir=tmp_path,
        channel_alias="test_channel",
        db_path=db_path,
        work_root=work_root,
    )

    assert result.ignored_csv_count >= 5, (
        f"Expected at least 5 ignored CSVs, got {result.ignored_csv_count}"
    )

    # Audit CSV must contain 'ignored_by_policy' entries
    audit_path = work_root / "test_channel" / "01_collect" / "takeout_ingest_audit.csv"
    assert audit_path.exists(), f"audit CSV not found at {audit_path}"
    content = audit_path.read_text(encoding="utf-8")
    assert "ignored_by_policy" in content, "audit CSV must contain ignored_by_policy rows"
