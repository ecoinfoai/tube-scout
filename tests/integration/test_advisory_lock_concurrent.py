"""Concurrent write test for Layer D advisory lock (T057 RED).

FR-033: Two concurrent Layer D write attempts must result in ConcurrentWriteRejected
for the second writer. The CLI surface translates this to exit code 3.
"""

import sqlite3
import threading
from pathlib import Path

from tests.fixtures.spec011.fixture_db import build_clean_v2_db
from tube_scout.services.advisory_lock import (
    ConcurrentWriteRejected,
    layer_d_write_lock,
)


def _make_db(tmp_path: Path) -> Path:
    db = build_clean_v2_db(tmp_path / "content_reuse.db")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-lock', 'Lock Prof', '2026-01-01T00:00:00', 'system')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO comparison_results "
        "(source_video_id, target_video_id, review_status, created_at) "
        "VALUES ('src-lock', 'tgt-lock', 'UNREVIEWED', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()
    return db


def test_concurrent_layer_d_second_writer_raises_concurrent_write_rejected(
    tmp_path: Path,
) -> None:
    """Two concurrent Layer D writers: second must get ConcurrentWriteRejected."""
    db = _make_db(tmp_path)

    first_entered = threading.Event()
    second_done = threading.Event()
    results: dict[str, object] = {}

    def first_writer() -> None:
        try:
            with layer_d_write_lock(db) as conn:
                first_entered.set()
                # Hold the lock until the second writer has attempted
                second_done.wait(timeout=5.0)
                conn.execute(
                    "UPDATE comparison_results SET review_status='FALSE_POSITIVE' "
                    "WHERE source_video_id='src-lock'"
                )
        except Exception as exc:
            results["first_error"] = exc

    def second_writer() -> None:
        first_entered.wait(timeout=5.0)
        try:
            with layer_d_write_lock(db) as conn:
                conn.execute(
                    "UPDATE comparison_results SET review_status='CONFIRMED_DUPLICATE' "
                    "WHERE source_video_id='src-lock'"
                )
            results["second_success"] = True
        except ConcurrentWriteRejected as exc:
            results["second_error"] = exc
        except Exception as exc:
            results["second_unexpected"] = exc
        finally:
            second_done.set()

    t1 = threading.Thread(target=first_writer)
    t2 = threading.Thread(target=second_writer)
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert "second_error" in results, (
        f"Expected ConcurrentWriteRejected for second writer. "
        f"Got: success={results.get('second_success')}, "
        f"unexpected={results.get('second_unexpected')}, "
        f"first_error={results.get('first_error')}"
    )
    assert isinstance(results["second_error"], ConcurrentWriteRejected)
    assert "first_error" not in results, f"First writer failed: {results.get('first_error')}"


def test_concurrent_write_rejected_message_is_actionable(tmp_path: Path) -> None:
    """ConcurrentWriteRejected message contains actionable text for operators."""
    db = _make_db(tmp_path)

    first_entered = threading.Event()
    second_done = threading.Event()
    captured: dict[str, object] = {}

    def first_writer() -> None:
        with layer_d_write_lock(db) as conn:
            first_entered.set()
            second_done.wait(timeout=5.0)

    def second_writer() -> None:
        first_entered.wait(timeout=5.0)
        try:
            with layer_d_write_lock(db):
                pass
        except ConcurrentWriteRejected as exc:
            captured["msg"] = str(exc)
        finally:
            second_done.set()

    t1 = threading.Thread(target=first_writer)
    t2 = threading.Thread(target=second_writer)
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert "msg" in captured
    msg = captured["msg"].lower()
    assert "retry" in msg or "administrator" in msg, (
        f"Message not actionable: {captured['msg']!r}"
    )


def test_cli_review_mark_concurrent_exits_3(tmp_path: Path) -> None:
    """'content review --mark' under held lock exits with code 3 (FR-033 CLI surface)."""
    from typer.testing import CliRunner

    import tube_scout.cli.content as _content_mod
    from tube_scout.cli.content import content_app

    db = _make_db(tmp_path)
    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True, exist_ok=True)

    # Move db to expected location
    import shutil
    shutil.copy(str(db), str(db_dir / "content_reuse.db"))
    db_path = db_dir / "content_reuse.db"

    conn = sqlite3.connect(str(db_path))
    comp_row = conn.execute(
        "SELECT id FROM comparison_results WHERE source_video_id='src-lock'"
    ).fetchone()
    conn.close()
    comp_id = comp_row[0] if comp_row else 1

    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with layer_d_write_lock(db_path) as conn:
            lock_held.set()
            release_lock.wait(timeout=10.0)

    t = threading.Thread(target=hold_lock)
    t.start()
    lock_held.wait(timeout=5.0)

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        runner = CliRunner()
        result = runner.invoke(
            content_app,
            [
                "review",
                "--project", str(tmp_path),
                "--channel", "ch-test",
                "--mark", f"{comp_id} FALSE_POSITIVE",
            ],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag
        release_lock.set()
        t.join(timeout=5.0)

    assert result.exit_code == 3, (
        f"Expected exit code 3 under lock contention, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )


def test_sequential_layer_d_writes_succeed(tmp_path: Path) -> None:
    """Sequential Layer D writes (no contention) both succeed."""
    db = _make_db(tmp_path)

    # First write
    with layer_d_write_lock(db) as conn:
        conn.execute(
            "UPDATE comparison_results SET review_status='FALSE_POSITIVE' "
            "WHERE source_video_id='src-lock'"
        )

    # Second write after first committed
    with layer_d_write_lock(db) as conn:
        conn.execute(
            "UPDATE comparison_results SET review_status='UNREVIEWED' "
            "WHERE source_video_id='src-lock'"
        )

    conn2 = sqlite3.connect(str(db))
    row = conn2.execute(
        "SELECT review_status FROM comparison_results WHERE source_video_id='src-lock'"
    ).fetchone()
    conn2.close()
    assert row[0] == "UNREVIEWED"
