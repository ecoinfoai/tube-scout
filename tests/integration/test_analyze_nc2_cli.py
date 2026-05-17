"""Integration: ``tube-scout analyze content-reuse --data-dir`` wires Layer B.

spec 013 T068 — when the CLI passes --data-dir, run_nc2_analysis resolves
per-video transcript JSONs under ``<data_dir>/<channel_alias>/02_analyze
/transcripts/<video_id>.json`` and persists match_spans with the
baseline_subtracted flag set for spans that match a professor's baseline
corpus.

This test exercises the CLI end-to-end on a small in-memory fixture so the
public ``analyze content-reuse`` surface is verified, not just the
underlying service function.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from tube_scout.cli.main import app

_PROFESSOR = "prof-cli-e2e"
_CHANNEL_ID = "UC_CLI_E2E_TEST_0001"
_CHANNEL_ALIAS = "cli_e2e"
_BASELINE_TEXT = "이번 시간에는 강의를 시작하겠습니다"


def _setup_db_and_transcripts(tmp_path: Path) -> tuple[Path, Path]:
    """Build a minimal v4 DB + per-video transcripts under tmp_path.

    Returns (db_path, data_dir).
    """
    from tube_scout.services.baseline_corpus import add_baseline_phrase
    from tube_scout.storage.content_db import (
        ContentDB,
        _ensure_v4,
        migrate_to_v2,
        migrate_to_v3,
    )

    db_path = tmp_path / "content_reuse.db"
    ContentDB(db_path).close()
    migrate_to_v2(db_path)
    migrate_to_v3(db_path)
    _ensure_v4(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channel_metadata "
            "(channel_id, channel_alias, title, source, ingested_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (_CHANNEL_ID, _CHANNEL_ALIAS, "CLI E2E Channel", "takeout",
             "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool "
            "(professor_id, display_name, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (_PROFESSOR, "CLI E2E Prof", "2026-01-01T00:00:00+00:00", "test"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool_membership "
            "(professor_id, channel_alias, author_marker, registered_at, "
            "registered_by) VALUES (?, ?, ?, ?, ?)",
            (_PROFESSOR, _CHANNEL_ALIAS, "__channel_owner__",
             "2026-01-01T00:00:00+00:00", "test"),
        )
        for i in range(3):
            vid = f"cli_vid_{i:04d}"
            conn.execute(
                "INSERT OR IGNORE INTO video_metadata "
                "(video_id, channel_id, title, duration_seconds, source, "
                "ingested_at) VALUES (?, ?, ?, ?, ?, ?)",
                (vid, _CHANNEL_ID, f"CLI Video {i}", 1800.0, "takeout",
                 "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO processing_status "
                "(video_id, channel_id, status, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (vid, _CHANNEL_ID, "collected",
                 "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()

    add_baseline_phrase(
        professor_id=_PROFESSOR,
        phrase_raw=_BASELINE_TEXT,
        db_path=db_path,
        source_video_ids=["cli_vid_0000"],
        registered_by="test",
    )

    # Seed transcripts under the exact path layout the CLI expects, so
    # `_resolve_transcript_path_by_video` finds them via the channel_metadata
    # join (no transcript_root override required).
    data_dir = tmp_path / "data"
    transcript_dir = data_dir / _CHANNEL_ALIAS / "02_analyze" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        vid = f"cli_vid_{i:04d}"
        payload = {
            "video_id": vid,
            "source": "asr",
            "segments": [
                {"start": 0.0, "end": 60.0, "text": _BASELINE_TEXT},
                {"start": 60.0, "end": 120.0, "text": f"고유한 본문 {i}"},
            ],
        }
        (transcript_dir / f"{vid}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    return db_path, data_dir


def test_analyze_cli_persists_match_spans_with_data_dir(
    tmp_path: Path,
) -> None:
    """``analyze content-reuse --data-dir`` populates match_spans + Layer B."""
    db_path, data_dir = _setup_db_and_transcripts(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "analyze",
            "content-reuse",
            "--channel", _CHANNEL_ALIAS,
            "--professor", _PROFESSOR,
            "--mode", "M-nC2",
            "--layer-a-seconds", "30.0",
            "--db-path", str(db_path),
            "--data-dir", str(data_dir),
        ],
    )

    assert result.exit_code == 0, (
        f"analyze content-reuse exited non-zero:\n{result.output}\n"
        f"exception: {result.exception!r}"
    )

    with sqlite3.connect(db_path) as conn:
        total_spans = conn.execute(
            "SELECT COUNT(*) FROM match_spans"
        ).fetchone()[0]
        subtracted = conn.execute(
            "SELECT COUNT(*) FROM match_spans WHERE baseline_subtracted = 1"
        ).fetchone()[0]
        comparison_rows = conn.execute(
            "SELECT COUNT(*) FROM comparison_results WHERE professor_id = ?",
            (_PROFESSOR,),
        ).fetchone()[0]

    assert comparison_rows == 3, (
        f"3 videos → C(3,2)=3 comparison_results rows, got {comparison_rows}"
    )
    assert total_spans > 0, (
        "Expected Layer B persistence to write match_spans rows via --data-dir"
    )
    assert subtracted > 0, (
        f"Expected baseline_subtracted=1 spans (baseline phrase shared by "
        f"all 3 videos), got 0 of {total_spans}"
    )


def test_analyze_cli_without_data_dir_skips_match_spans(
    tmp_path: Path,
) -> None:
    """Without --data-dir (or with the default that has no transcripts)
    the analysis still completes but match_spans persistence is skipped."""
    db_path, _ = _setup_db_and_transcripts(tmp_path)

    runner = CliRunner()
    # Point --data-dir at an empty directory so transcript resolution fails
    # for every video and no spans are persisted.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = runner.invoke(
        app,
        [
            "analyze",
            "content-reuse",
            "--channel", _CHANNEL_ALIAS,
            "--professor", _PROFESSOR,
            "--mode", "M-nC2",
            "--layer-a-seconds", "30.0",
            "--db-path", str(db_path),
            "--data-dir", str(empty_dir),
        ],
    )

    assert result.exit_code == 0, result.output

    with sqlite3.connect(db_path) as conn:
        spans = conn.execute("SELECT COUNT(*) FROM match_spans").fetchone()[0]
        comparison_rows = conn.execute(
            "SELECT COUNT(*) FROM comparison_results WHERE professor_id = ?",
            (_PROFESSOR,),
        ).fetchone()[0]

    assert comparison_rows == 3
    assert spans == 0, (
        f"Without transcripts under --data-dir, match_spans should be 0; "
        f"got {spans}"
    )
