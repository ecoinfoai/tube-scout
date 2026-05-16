"""T010 RED — contract tests for `tube-scout collect ingest` (spec 017 US1).

Acceptance Matrix 9 scenarios from contracts/collect-ingest.md.
All tests fail at RED stage: collect_ingest_command does not yet exist.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

_REAL_CHANNEL_HEADER = [
    "채널 ID", "채널 국가", "채널 태그 1", "채널 제목(원본)", "채널 공개 상태",
]
_REAL_VIDEO_HEADER = [
    "동영상 ID", "근사치 길이(밀리초)", "동영상 오디오 언어", "동영상 카테고리",
    "동영상 설명(원본) 언어", "채널 ID", "동영상 제목(원본)", "동영상 제목(원본) 언어",
    "개인 정보 보호", "동영상 상태", "동영상 생성 타임스탬프",
]


def _make_archive(tmp_path: Path, channel_id: str = "UCtest001") -> Path:
    """Create a minimal valid Takeout archive layout."""
    yt_dir = (
        tmp_path
        / "Takeout"
        / "YouTube 및 YouTube Music"
        / "동영상 메타데이터"
    )
    yt_dir.mkdir(parents=True)
    ch_dir = tmp_path / "Takeout" / "YouTube 및 YouTube Music" / "채널"
    ch_dir.mkdir(parents=True)

    ch_csv = ch_dir / "채널.csv"
    with ch_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_REAL_CHANNEL_HEADER)
        w.writerow([channel_id, "KR", "태그", "테스트채널", "공개"])

    vid_csv = yt_dir / "동영상.csv"
    with vid_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_REAL_VIDEO_HEADER)
        w.writerow([
            "vid001", "3600000", "ko", "교육", "ko",
            channel_id, "1-1강의제목A", "ko",
            "일부 공개", "공개됨", "2026-04-01T00:00:00Z",
        ])

    return tmp_path


def _mock_registry(channel_id: str = "UCtest001"):
    mock_reg = MagicMock()
    mock_reg.channel_id = channel_id
    return mock_reg


def _get_runner_and_app():
    from tube_scout.cli.main import app
    return CliRunner(), app


def test_normal_ingest_exit_0(tmp_path: Path) -> None:
    """Normal collect ingest with valid archive and registered alias exits 0."""
    archive = _make_archive(tmp_path / "archive")
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    runner, app = _get_runner_and_app()
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={"nursing": _mock_registry()},
    ), patch(
        "tube_scout.services.unified_ingest.ingest_unified",
    ) as mock_ingest:
        mock_ingest.return_value = MagicMock()
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ])

    assert result.exit_code == 0, (
        f"Expected exit 0 for normal ingest, got {result.exit_code}\n{result.output}"
    )


def test_delete_source_yes_unlinks(tmp_path: Path) -> None:
    """--delete-source with operator 'y' response triggers unlink and returns CleanupResult."""
    archive = _make_archive(tmp_path / "archive")
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    runner, app = _get_runner_and_app()
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={"nursing": _mock_registry()},
    ), patch(
        "tube_scout.services.unified_ingest.ingest_unified",
    ) as mock_ingest:
        mock_ingest.return_value = MagicMock()
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
            "--delete-source",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ], input="y\n")

    assert result.exit_code == 0, (
        f"Expected exit 0 for delete-source yes, got {result.exit_code}\n{result.output}"
    )


def test_delete_source_no_preserves(tmp_path: Path) -> None:
    """--delete-source with operator 'n' response preserves source files, exits 0."""
    archive = _make_archive(tmp_path / "archive")
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    runner, app = _get_runner_and_app()
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={"nursing": _mock_registry()},
    ), patch(
        "tube_scout.services.unified_ingest.ingest_unified",
    ) as mock_ingest:
        mock_ingest.return_value = MagicMock()
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
            "--delete-source",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ], input="n\n")

    assert result.exit_code == 0, (
        f"Expected exit 0 for delete-source no, got {result.exit_code}\n{result.output}"
    )


def test_alias_unregistered_exit_1(tmp_path: Path) -> None:
    """Unknown alias produces exit code 1."""
    archive = _make_archive(tmp_path / "archive")

    runner, app = _get_runner_and_app()
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={},
    ):
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "unknown_dept",
        ])

    assert result.exit_code == 1, (
        f"Expected exit 1 for unregistered alias, got {result.exit_code}\n{result.output}"
    )


def test_alias_mismatch_blocks_exit_1(tmp_path: Path) -> None:
    """Alias present in channels.json but mismatched with departments.json exits 1 (boundary B-9)."""
    archive = _make_archive(tmp_path / "archive", channel_id="UCtest001")

    runner, app = _get_runner_and_app()
    # Simulate mismatch: registry returns alias but channel_id differs from CSV
    mismatch_reg = MagicMock()
    mismatch_reg.channel_id = "UCdifferent999"
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={"nursing": mismatch_reg},
    ):
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
        ])

    assert result.exit_code == 1, (
        f"Expected exit 1 for alias mismatch, got {result.exit_code}\n{result.output}"
    )


def test_takeout_dir_missing_exit_1(tmp_path: Path) -> None:
    """Non-existent --takeout-dir produces exit code 1."""
    nonexistent = tmp_path / "does_not_exist"

    runner, app = _get_runner_and_app()
    result = runner.invoke(app, [
        "collect", "ingest",
        "--takeout-dir", str(nonexistent),
        "--channel", "nursing",
    ])

    assert result.exit_code == 1, (
        f"Expected exit 1 for missing takeout-dir, got {result.exit_code}\n{result.output}"
    )


def test_dry_run_no_db_write(tmp_path: Path) -> None:
    """--dry-run exits 0 and writes 0 rows to DB."""
    archive = _make_archive(tmp_path / "archive")
    db_path = tmp_path / "test.db"
    work_root = tmp_path / "work"

    runner, app = _get_runner_and_app()
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={"nursing": _mock_registry()},
    ):
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
            "--dry-run",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ])

    assert result.exit_code == 0, (
        f"Expected exit 0 for dry-run, got {result.exit_code}\n{result.output}"
    )
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM video_metadata"
        ).fetchone()[0]
        conn.close()
        assert count == 0, f"Expected 0 DB rows in dry-run mode, got {count}"


def test_partial_failure_with_delete_source(tmp_path: Path) -> None:
    """Partial stage failure + --delete-source shows failed table + reduced candidate count."""
    archive = _make_archive(tmp_path / "archive")
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    runner, app = _get_runner_and_app()
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={"nursing": _mock_registry()},
    ), patch(
        "tube_scout.services.unified_ingest.ingest_unified",
    ) as mock_ingest:
        # Simulate 1 transcript failure; 8 deletion candidates (N-1)
        mock_summary = MagicMock()
        mock_summary.cleanup_result.presented_failure_count = 1
        mock_summary.cleanup_result.deletion_candidate_count = 8
        mock_ingest.return_value = mock_summary
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
            "--delete-source",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ], input="y\n")

    assert result.exit_code == 0, (
        f"Expected exit 0 for partial failure with delete-source, "
        f"got {result.exit_code}\n{result.output}"
    )


def test_idempotent_second_run(tmp_path: Path) -> None:
    """Second run on same archive yields new_videos=0 (SC-004)."""
    archive = _make_archive(tmp_path / "archive")
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    runner, app = _get_runner_and_app()
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={"nursing": _mock_registry()},
    ), patch(
        "tube_scout.services.unified_ingest.ingest_unified",
    ) as mock_ingest:
        second_summary = MagicMock()
        second_summary.ingest_result.new_videos = 0
        mock_ingest.return_value = second_summary

        # first run
        runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ])
        # second run
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ])

    assert result.exit_code == 0, (
        f"Expected exit 0 on second run, got {result.exit_code}\n{result.output}"
    )
    assert mock_ingest.return_value.ingest_result.new_videos == 0, (
        "Expected new_videos=0 on idempotent second run"
    )
