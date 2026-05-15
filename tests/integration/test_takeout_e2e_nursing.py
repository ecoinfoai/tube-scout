"""Integration e2e test — nursing channel Takeout archive ingestion (T016).

SC-001/SC-002/SC-007: real data at data/takeout-20260511T130817Z-3-001/
  - SQLite video_metadata row count = 2554 after ingest
  - privacy_status column: no NULL (Korean) values remaining
  - audit rows: 9 success (mp4 matched) + 2545 no_mp4 + 26 ignored_csv

Marked xfail at RED stage — GREEN once ingest_takeout() is fixed (T017+).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_TAKEOUT_ARCHIVE = Path(__file__).parent.parent.parent / \
    "data" / "takeout-20260511T130817Z-3-001"
_ARCHIVE_ROOT = _TAKEOUT_ARCHIVE  # parent of Takeout/


@pytest.mark.skipif(
    not _TAKEOUT_ARCHIVE.exists(),
    reason="Real takeout archive not present — skipping e2e test",
)
class TestNursingTakeoutE2E:
    """T016 — full ingest of real nursing archive; validates DB + audit counts."""

    @pytest.fixture(scope="class")
    def ingest_result(self, tmp_path_factory):
        """Run ingest_takeout() once for the whole class; return (result, work_root)."""
        from unittest.mock import MagicMock, patch

        from tube_scout.services.takeout_ingest import ingest_takeout

        work_root = tmp_path_factory.mktemp("nursing_work")
        db_path = work_root / "test.db"

        mock_reg = MagicMock()
        mock_reg.channel_id = "UCnh3tm9uQkyA260cAHfl9rg"

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"nursing": mock_reg},
        ):
            result = ingest_takeout(
                takeout_dir=_ARCHIVE_ROOT,
                channel_alias="nursing",
                db_path=db_path,
                work_root=work_root,
                use_symlinks=False,
                dry_run=False,
            )
        return result, work_root, db_path

    def test_total_video_count(self, ingest_result) -> None:
        """SC-001: 2554 video rows expected after full ingest."""
        result, work_root, db_path = ingest_result
        assert result.total_videos == 2554, (
            f"Expected 2554 total_videos, got {result.total_videos}"
        )

    def test_db_video_metadata_row_count(self, ingest_result) -> None:
        """SC-002: SQLite video_metadata table must have exactly 2554 rows."""
        result, work_root, db_path = ingest_result
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]
        assert count == 2554, f"Expected 2554 DB rows, got {count}"

    def test_no_korean_privacy_in_db(self, ingest_result) -> None:
        """SC-007: No Korean privacy strings in video_metadata.privacy_status."""
        result, work_root, db_path = ingest_result
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT privacy_status FROM video_metadata WHERE privacy_status IS NOT NULL"
            ).fetchall()
        korean_values = [r[0] for r in rows if r[0] not in ("public", "unlisted", "private")]
        assert len(korean_values) == 0, (
            f"Korean privacy values found in DB: {korean_values[:5]}"
        )

    def test_mp4_present_count(self, ingest_result) -> None:
        """9 mp4 files present in archive → 9 high/medium mappings."""
        result, work_root, db_path = ingest_result
        assert result.mp4_present_count == 9, (
            f"Expected mp4_present_count=9, got {result.mp4_present_count}"
        )

    def test_mp4_absent_count(self, ingest_result) -> None:
        """2545 videos without mp4 in archive."""
        result, work_root, db_path = ingest_result
        assert result.mp4_absent_count == 2545, (
            f"Expected mp4_absent_count=2545, got {result.mp4_absent_count}"
        )

    def test_audit_ignored_csv_count(self, ingest_result) -> None:
        """30 ignored items = meta_dir 26 (동영상 텍스트 ×13 + 동영상 녹화 ×13) + yt_dir top-level 4 (구독정보/댓글/시청 기록/재생목록)."""
        result, work_root, db_path = ingest_result
        assert result.ignored_csv_count == 30, (
            f"Expected ignored_csv_count=30, got {result.ignored_csv_count}"
        )

    def test_elapsed_seconds_positive(self, ingest_result) -> None:
        """elapsed_seconds must be > 0."""
        result, work_root, db_path = ingest_result
        assert result.elapsed_seconds > 0, "elapsed_seconds must be positive"
