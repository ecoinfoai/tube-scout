"""T033 — E2E integration test for takeout_ingest (spec 013).

Uses the sanitized 9-video Takeout fixture (tests/fixtures/takeout_sample).
Verifies: CSV parse → evidence mapping → SQLite v4 persist → audit CSV → symlinks.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from unittest.mock import patch

FIXTURE_TAKEOUT = Path(__file__).parent.parent / "fixtures" / "takeout_sample" / "Takeout"


def _make_registry() -> dict:
    from tube_scout.models.config import ChannelRegistration
    return {
        "test_channel": ChannelRegistration(
            channel_id="UCfakeAnonChan0123456789",
            alias="test_channel",
            channel_name="Test Channel",
            registered_at="2026-01-01T00:00:00Z",
            last_used_at="2026-01-01T00:00:00Z",
            token_path="/tmp/fake_token.json",
        )
    }


def test_e2e_full_ingest_9_videos(tmp_path: Path) -> None:
    """Full pipeline: 9-video Takeout → v4 DB → 9 video_metadata rows + audit CSV."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    # ffprobe is called for every mp4 during evidence scoring — mock it
    import subprocess
    def mock_ffprobe(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "1.0"
        result.stderr = ""
        return result

    with patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()), \
         patch("subprocess.run", side_effect=mock_ffprobe):
        result = ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias="test_channel",
            db_path=db_path,
            work_root=work_root,
        )

    # DB: v4 schema applied
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert version == 4, f"Expected user_version=4, got {version}"

        vm_count = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]
        assert vm_count == 9, f"Expected 9 video_metadata rows, got {vm_count}"

        ch_count = conn.execute("SELECT COUNT(*) FROM channel_metadata").fetchone()[0]
        assert ch_count == 1, f"Expected 1 channel_metadata row, got {ch_count}"

    # IngestResult summary
    assert result.total_videos == 9, f"Expected 9, got {result.total_videos}"
    assert result.new_videos == 9, f"First run: expected 9 new, got {result.new_videos}"
    assert result.channel_id == "UCfakeAnonChan0123456789"
    assert result.channel_alias == "test_channel"
    assert result.dry_run is False

    # Audit CSV exists and has rows
    audit_path = work_root / "test_channel" / "01_collect" / "takeout_ingest_audit.csv"
    assert audit_path.exists(), f"Audit CSV not found: {audit_path}"
    rows = list(csv.DictReader(audit_path.open(encoding="utf-8")))
    assert len(rows) >= 9, f"Expected >= 9 audit rows, got {len(rows)}"


def test_e2e_symlinks_created(tmp_path: Path) -> None:
    """After ingest, work_dir/동영상/ contains 9 mp4 symlinks."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    import subprocess
    def mock_ffprobe(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "1.0"
        result.stderr = ""
        return result

    with patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()), \
         patch("subprocess.run", side_effect=mock_ffprobe):
        ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias="test_channel",
            db_path=db_path,
            work_root=work_root,
            use_symlinks=True,
        )

    video_dir = work_root / "test_channel" / "동영상"
    assert video_dir.exists(), f"video_dir not created: {video_dir}"
    mp4s = list(video_dir.glob("*.mp4"))
    assert len(mp4s) == 9, f"Expected 9 mp4 symlinks, got {len(mp4s)}"
    for mp4 in mp4s:
        assert mp4.is_symlink(), f"{mp4.name} must be a symlink"
        assert mp4.resolve().exists(), f"Symlink target does not exist: {mp4}"


def test_e2e_idempotent_second_run(tmp_path: Path) -> None:
    """Second run on same Takeout: DB row count stable, new_videos=0."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    import subprocess
    def mock_ffprobe(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "1.0"
        result.stderr = ""
        return result

    registry = _make_registry()

    with patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=registry), \
         patch("subprocess.run", side_effect=mock_ffprobe):
        ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias="test_channel",
            db_path=db_path,
            work_root=work_root,
        )

    with sqlite3.connect(db_path) as conn:
        count_1 = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]

    with patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=registry), \
         patch("subprocess.run", side_effect=mock_ffprobe):
        result2 = ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias="test_channel",
            db_path=db_path,
            work_root=work_root,
        )

    with sqlite3.connect(db_path) as conn:
        count_2 = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]

    assert count_1 == count_2, f"Row count changed: {count_1} → {count_2}"
    assert result2.new_videos == 0, f"Second run must report 0 new_videos, got {result2.new_videos}"


def test_e2e_dry_run_no_db(tmp_path: Path) -> None:
    """dry_run=True: IngestResult.dry_run is True and no DB rows written."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    import subprocess
    def mock_ffprobe(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "1.0"
        result.stderr = ""
        return result

    with patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()), \
         patch("subprocess.run", side_effect=mock_ffprobe):
        result = ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias="test_channel",
            db_path=db_path,
            work_root=work_root,
            dry_run=True,
        )

    assert result.dry_run is True
    assert result.total_videos == 9

    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "video_metadata" in tables:
                count = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]
                assert count == 0, f"dry_run must not write rows, got {count}"


def test_e2e_json_files_written(tmp_path: Path) -> None:
    """After ingest, channel_meta.json and videos_meta.json are written."""
    import json

    from tube_scout.services.takeout_ingest import ingest_takeout

    db_path = tmp_path / "content_reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    import subprocess
    def mock_ffprobe(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "1.0"
        result.stderr = ""
        return result

    with patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()), \
         patch("subprocess.run", side_effect=mock_ffprobe):
        ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias="test_channel",
            db_path=db_path,
            work_root=work_root,
        )

    work_dir = work_root / "test_channel"
    ch_json = work_dir / "channel_meta.json"
    vm_json = work_dir / "videos_meta.json"

    assert ch_json.exists(), "channel_meta.json must be written"
    assert vm_json.exists(), "videos_meta.json must be written"

    ch_data = json.loads(ch_json.read_text(encoding="utf-8"))
    assert ch_data["channel_id"] == "UCfakeAnonChan0123456789"

    vm_data = json.loads(vm_json.read_text(encoding="utf-8"))
    assert isinstance(vm_data, list), "videos_meta.json must be a list"
    assert len(vm_data) == 9, f"Expected 9 videos, got {len(vm_data)}"
