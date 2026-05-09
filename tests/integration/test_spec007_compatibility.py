"""Integration tests for spec 007 backward compatibility (T025 RED — boundary B-2 + SC-009).

Verifies that spec 011 nC2 operations do not modify spec 007 rows or
recompute embeddings.parquet.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import polars as pl
import pytest

from tests.fixtures.spec011.fixture_db import build_spec007_legacy_db
from tube_scout.storage.content_db import migrate_to_v2


def _sha256_rows(db: Path, table: str) -> str:
    """Compute a SHA-256 hash over all rows in a table for change detection."""
    conn = sqlite3.connect(str(db))
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
    conn.close()
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


def _write_embeddings(captions_dir: Path, video_ids: list[str], dim: int = 8) -> None:
    import random

    captions_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(2)
    rows = []
    for _ in video_ids:
        v = [rng.gauss(0, 1) for _ in range(dim)]
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        rows.append([x / norm for x in v])
    df = pl.DataFrame({"video_id": video_ids, "embedding": rows})
    df.write_parquet(captions_dir / "embeddings.parquet")


def test_spec007_rows_unchanged_after_nc2(tmp_path: Path) -> None:
    """spec 007 comparison_results rows are byte-identical before and after nc2."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs
    from tube_scout.services.professor_resolver import map_professor

    db = build_spec007_legacy_db(tmp_path / "cr.db")
    migrate_to_v2(db)
    # Measure hash AFTER migrate so column additions don't count as nc2 change
    hash_before = _sha256_rows(db, "comparison_results")

    # Map one professor to the legacy channel
    map_professor("prof-x", "Prof X", "ch-test", "__channel_owner__", db, "test")

    # Add a couple of videos with fingerprinted status
    conn = sqlite3.connect(str(db))
    for i in range(3):
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (f"new-vid-{i}", "ch-test", "fingerprinted", "2026-01-01"),
        )
    conn.commit()
    conn.close()

    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, [f"new-vid-{i}" for i in range(3)])

    generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)

    hash_after = _sha256_rows(db, "comparison_results")
    assert hash_before == hash_after, (
        "spec 007 comparison_results rows were modified by nc2 operation (boundary B-2 violation)"
    )


def test_embeddings_parquet_not_rewritten(tmp_path: Path) -> None:
    """embeddings.parquet mtime is unchanged after generate_nc2_pairs (boundary B-2)."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs
    from tube_scout.services.professor_resolver import map_professor

    db = build_spec007_legacy_db(tmp_path / "cr.db")
    migrate_to_v2(db)
    map_professor("prof-x", "Prof X", "ch-legacy", "__channel_owner__", db, "test")

    vids = ["lv0", "lv1", "lv2"]
    conn = sqlite3.connect(str(db))
    for i, vid in enumerate(vids):
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (vid, "ch-legacy", "fingerprinted", "2026-01-01"),
        )
    conn.commit()
    conn.close()

    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, vids)

    emb_path = captions_dir / "embeddings.parquet"
    mtime_before = emb_path.stat().st_mtime_ns

    generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)

    mtime_after = emb_path.stat().st_mtime_ns
    assert mtime_before == mtime_after, (
        "embeddings.parquet was rewritten during nc2 operation (boundary B-2 violation)"
    )
