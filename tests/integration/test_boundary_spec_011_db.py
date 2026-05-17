"""T032 RED — B-X1-2: v2 schema (videos/matches tables) unchanged after migrate_to_v3.

Verifies that migrate_to_v3() + audio_fingerprint inserts do NOT touch v2 data.
"""
import sqlite3
from pathlib import Path


def _setup_v2_db(db_path: Path) -> None:
    """Create a v2 schema DB with sample rows.

    Uses ContentDB (v1 init) + migrate_to_v2 to create full spec 011 schema.
    """
    from tube_scout.storage.content_db import ContentDB, migrate_to_v2

    # Init v1 schema (ContentDB creates all base tables including comparison_results)
    db = ContentDB(db_path)
    db.close()

    # Migrate to v2
    migrate_to_v2(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("VID_V2_001", "UC_TEST", "pending", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("VID_V2_002", "UC_TEST", "pending", "2026-01-02T00:00:00Z"),
        )
        conn.commit()


def test_b_x1_2_v2_row_count_unchanged_after_migrate(tmp_path: Path) -> None:
    """B-X1-2: videos table row count identical before/after migrate_to_v3."""
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    _setup_v2_db(db_path)

    with sqlite3.connect(db_path) as conn:
        before_count = conn.execute("SELECT COUNT(*) FROM processing_status").fetchone()[0]

    migrate_to_v3(db_path)

    with sqlite3.connect(db_path) as conn:
        after_count = conn.execute("SELECT COUNT(*) FROM processing_status").fetchone()[0]

    assert before_count == after_count == 2


def test_b_x1_2_v2_row_data_unchanged_after_migrate(tmp_path: Path) -> None:
    """B-X1-2: existing videos row data identical after migrate_to_v3."""
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    _setup_v2_db(db_path)

    with sqlite3.connect(db_path) as conn:
        before_rows = conn.execute(
            "SELECT video_id, channel_id, status FROM processing_status ORDER BY video_id"
        ).fetchall()

    migrate_to_v3(db_path)

    with sqlite3.connect(db_path) as conn:
        after_rows = conn.execute(
            "SELECT video_id, channel_id, status FROM processing_status ORDER BY video_id"
        ).fetchall()

    assert before_rows == after_rows


def test_b_x1_2_audio_fingerprint_insert_does_not_touch_videos(tmp_path: Path) -> None:
    """B-X1-2: insert_audio_fingerprint leaves videos table rows intact."""
    from tube_scout.storage.content_db import insert_audio_fingerprint, migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    _setup_v2_db(db_path)
    migrate_to_v3(db_path)

    import datetime
    extracted_at = datetime.datetime.now(tz=datetime.UTC).isoformat()
    insert_audio_fingerprint(
        db_path, "VID_V2_001", b"AQADtFMSRUkiJdmE" * 2, 3600.0, extracted_at
    )

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM processing_status").fetchone()[0]
        statuses = conn.execute(
            "SELECT status FROM processing_status ORDER BY video_id"
        ).fetchall()

    assert count == 2
    assert statuses[0][0] == "pending"
    assert statuses[1][0] == "pending"


def test_b_x1_2_pragma_user_version_is_3_after_migrate(tmp_path: Path) -> None:
    """B-X1-2: PRAGMA user_version == 3 after migrate_to_v3."""
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    _setup_v2_db(db_path)
    migrate_to_v3(db_path)

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert version == 3
