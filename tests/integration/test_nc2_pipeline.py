"""Integration tests for nC2 pipeline basic flow (T023 RED).

Tests the end-to-end candidate generation across multiple channels for a
single professor. Time-axis integration (T036) is a deferred xfail placeholder.
"""

import sqlite3
from pathlib import Path

import polars as pl
import pytest

from tests.fixtures.spec011.fixture_db import build_clean_v2_db
from tube_scout.services.professor_resolver import map_professor


def _insert_videos(db: Path, channel: str, video_ids: list[str]) -> None:
    conn = sqlite3.connect(str(db))
    for i, vid in enumerate(video_ids):
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (vid, channel, "fingerprinted", "2026-01-01"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fingerprint_hashes (video_id, sha256_hash, full_text_length, embedding_row_index, created_at) VALUES (?, ?, ?, ?, ?)",
            (vid, f"hash{i:060x}", 1000, i, "2026-01-01"),
        )
    conn.commit()
    conn.close()


def _write_embeddings(captions_dir: Path, video_ids: list[str], dim: int = 8) -> None:
    import random

    captions_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    rows = []
    for _ in video_ids:
        v = [rng.gauss(0, 1) for _ in range(dim)]
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        rows.append([x / norm for x in v])
    df = pl.DataFrame({"video_id": video_ids, "embedding": rows})
    df.write_parquet(captions_dir / "embeddings.parquet")


def test_nc2_basic_flow(tmp_path: Path) -> None:
    """5-video pool across 2 channels → exactly 10 nC2 candidate pairs."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs

    db = build_clean_v2_db(tmp_path / "cr.db")
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-a",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="test",
    )
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-b",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="test",
    )

    vids_a = ["a1", "a2", "a3"]
    vids_b = ["b1", "b2"]
    _insert_videos(db, "ch-a", vids_a)
    _insert_videos(db, "ch-b", vids_b)

    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, vids_a + vids_b)

    pairs = generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)
    assert len(pairs) == 10  # 5C2 = 10


@pytest.mark.xfail(reason="T036: time-axis integration deferred to Phase 4", strict=True)
def test_time_axis_integration_placeholder() -> None:
    """Placeholder: time-axis indicators (I-6/I-7/I-8) not yet integrated."""
    from tube_scout.services.time_axis_indicators import compute_time_axis  # noqa: F401

    raise NotImplementedError("T036: time-axis integration is Phase 4 scope.")
