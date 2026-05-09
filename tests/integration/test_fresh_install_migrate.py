"""T060 RED — G-3: fresh install migrate_to_v3 always called (no db_path.exists() guard).

Verifies that collect audio on a fresh install (no content_reuse.db) still:
  - calls migrate_to_v3 (CREATE TABLE IF NOT EXISTS → safe)
  - successfully inserts audio_fingerprint rows
"""
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from typer.testing import CliRunner

from tube_scout.cli.main import app

runner = CliRunner()


def _mock_mgr(project_dir: Path) -> MagicMock:
    mgr = MagicMock()
    mgr.project_dir = str(project_dir)
    return mgr


def test_migrate_called_on_fresh_install(tmp_path: Path) -> None:
    """G-3: migrate_to_v3 called even when db_path does not exist yet."""
    channel_id = "UC_G3_FRESH1"
    channel_dir = tmp_path / "01_collect" / "channels" / channel_id
    channel_dir.mkdir(parents=True)
    (channel_dir / "videos_meta.json").write_text(
        json.dumps([{"video_id": "FRESHVID001"}]), encoding="utf-8"
    )

    # Intentionally do NOT create db_path
    db_path = tmp_path / "02_analyze" / "content" / "content_reuse.db"
    assert not db_path.exists(), "Pre-condition: db must not exist for fresh-install test"

    migrate_calls: list = []

    def spy_migrate(path):
        migrate_calls.append(path)

    with patch("tube_scout.cli.collect.resolve_project", return_value=_mock_mgr(tmp_path)), \
         patch("tube_scout.cli.collect.resolve_alias_to_channel_id", return_value=channel_id), \
         patch("tube_scout.cli.collect.dispatch_audio_fingerprint"), \
         patch("tube_scout.storage.content_db.migrate_to_v3", side_effect=spy_migrate):
        result = runner.invoke(app, [
            "collect", "audio", "--channel", "nursing",
            "--project-dir", str(tmp_path),
        ])

    assert result.exit_code in (0, 1), f"Unexpected exit: {result.exit_code}\n{result.output}"
    assert len(migrate_calls) >= 1, (
        "migrate_to_v3 must be called on fresh install (no exists() guard). "
        f"Called {len(migrate_calls)} times."
    )


def test_fresh_install_insert_succeeds(tmp_path: Path) -> None:
    """G-3: First insert_audio_fingerprint on fresh db succeeds (no OperationalError)."""
    from tube_scout.storage.content_db import insert_audio_fingerprint, migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    # Do NOT pre-create db — simulate fresh install
    assert not db_path.exists()

    # migrate_to_v3 must create the table idempotently
    migrate_to_v3(db_path)

    # First INSERT must succeed
    insert_audio_fingerprint(
        db_path,
        video_id="FRESHVID001",
        fingerprint=b"AQADtFMSRUkiJdmE",
        duration=1989.0,
        extracted_at="2026-05-10T00:00:00+00:00",
    )

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT video_id FROM audio_fingerprint").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "FRESHVID001"


def test_migrate_idempotent_on_existing_db(tmp_path: Path) -> None:
    """G-3: migrate_to_v3 called twice on existing db → no error (idempotent)."""
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    migrate_to_v3(db_path)
    # Second call must not raise
    migrate_to_v3(db_path)
