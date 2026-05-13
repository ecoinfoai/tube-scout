"""T068 RED — layer_defense e2e integration test (spec 013 T068).

Tests that apply_layer_b correctly filters match spans whose text
matches professor baseline corpus phrases.

Setup:
  - Seed baseline_corpus with high-frequency phrases.
  - Create MatchSpan list: some spans match baseline, some don't.
  - Call apply_layer_b → verify matching spans are removed.

The match_spans.baseline_subtracted assertions are RED until
run_nc2_analysis integrates Layer B and persists baseline_subtracted flags.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tube_scout.models.reuse_v2 import MatchSpan


def _make_span(text: str, length: float = 120.0) -> MatchSpan:
    return MatchSpan(
        start_a_seconds=0.0,
        end_a_seconds=length,
        start_b_seconds=0.0,
        end_b_seconds=length,
        length_seconds=length,
        matched_text_sample=text,
    )


def _setup_db_with_baseline(tmp_path: Path, professor: str = "prof-layer-b") -> Path:
    """Create v2 DB with seeded baseline phrases for professor."""
    db_path = tmp_path / "content_reuse.db"

    from tube_scout.storage.content_db import ContentDB, migrate_to_v2
    ContentDB(db_path).close()
    migrate_to_v2(db_path)

    from tube_scout.services.baseline_corpus import add_baseline_phrase
    from tube_scout.storage.content_db import ContentDB

    # Register professor_pool first
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool "
            "(professor_id, display_name, created_at, created_by) VALUES (?, ?, ?, ?)",
            (professor, "Layer B Prof", "2026-01-01T00:00:00+00:00", "test"),
        )
        conn.commit()

    # Seed baseline phrases
    baseline_phrases = [
        "이번 시간에는 강의를 시작하겠습니다",
        "다음 주에 계속 설명하도록 하겠습니다",
        "질문 있으시면 언제든지 연락주세요",
    ]
    for phrase in baseline_phrases:
        add_baseline_phrase(
            professor_id=professor,
            phrase_raw=phrase,
            db_path=db_path,
            source_video_ids=["vid001", "vid002", "vid003"],
            registered_by="test",
        )

    return db_path


def test_apply_layer_b_removes_baseline_spans(tmp_path: Path) -> None:
    """apply_layer_b removes spans whose text matches baseline corpus phrases."""
    from tube_scout.services.layer_defense import apply_layer_b

    professor = "prof-layer-b"
    db_path = _setup_db_with_baseline(tmp_path, professor)

    # 3 spans: 2 match baseline, 1 doesn't
    spans = [
        _make_span("이번 시간에는 강의를 시작하겠습니다", 120.0),
        _make_span("다음 주에 계속 설명하도록 하겠습니다", 90.0),
        _make_span("오늘은 머신러닝의 기초 개념을 다루겠습니다", 300.0),
    ]

    remaining = apply_layer_b(spans, professor, db_path, threshold=0.30)

    assert len(remaining) == 1, (
        f"Expected 1 non-baseline span, got {len(remaining)}: "
        f"{[s.matched_text_sample for s in remaining]}"
    )
    assert remaining[0].matched_text_sample == "오늘은 머신러닝의 기초 개념을 다루겠습니다", (
        f"Wrong span survived: {remaining[0].matched_text_sample!r}"
    )


def test_apply_layer_b_keeps_all_non_matching_spans(tmp_path: Path) -> None:
    """apply_layer_b with no baseline matches returns all spans unchanged."""
    from tube_scout.services.layer_defense import apply_layer_b

    professor = "prof-layer-b"
    db_path = _setup_db_with_baseline(tmp_path, professor)

    unique_spans = [
        _make_span("자율주행차의 경로계획 알고리즘", 200.0),
        _make_span("딥러닝 모델의 학습률 조정 기법", 150.0),
    ]
    remaining = apply_layer_b(unique_spans, professor, db_path)
    assert len(remaining) == len(unique_spans), (
        f"Expected all {len(unique_spans)} spans kept, got {len(remaining)}"
    )


def test_apply_layer_a_filters_short_spans() -> None:
    """apply_layer_a removes spans shorter than min_seconds."""
    from tube_scout.services.layer_defense import apply_layer_a

    spans = [
        _make_span("short span", 10.0),
        _make_span("medium span", 60.0),
        _make_span("long span", 300.0),
    ]
    remaining = apply_layer_a(spans, min_seconds=30.0)
    assert len(remaining) == 2, f"Expected 2 spans (>=30s), got {len(remaining)}"
    lengths = {s.length_seconds for s in remaining}
    assert 10.0 not in lengths, "Short span must be removed"


def test_match_spans_baseline_subtracted_flag_persisted(tmp_path: Path) -> None:
    """When run_nc2_analysis applies Layer B, match_spans.baseline_subtracted is set.

    This test is RED until run_nc2_analysis integrates Layer B and persists
    baseline_subtracted flags in match_spans table.
    """
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import ContentDB, migrate_to_v2, migrate_to_v3, _ensure_v4
    from tube_scout.services.baseline_corpus import add_baseline_phrase

    professor = "prof-layer-b-e2e"
    db_path = tmp_path / "content_reuse_lb.db"
    ContentDB(db_path).close()
    migrate_to_v2(db_path)
    migrate_to_v3(db_path)
    _ensure_v4(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channel_metadata "
            "(channel_id, channel_alias, title, source, ingested_at) VALUES (?, ?, ?, ?, ?)",
            ("UCtest000000002", "test_ch_lb", "LB Channel", "takeout", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool "
            "(professor_id, display_name, created_at, created_by) VALUES (?, ?, ?, ?)",
            (professor, "LB Prof", "2026-01-01T00:00:00+00:00", "test"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool_membership "
            "(professor_id, channel_alias, author_marker, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (professor, "test_ch_lb", "__channel_owner__", "2026-01-01T00:00:00+00:00", "test"),
        )
        for i in range(3):
            vid = f"lb_vid_{i:04d}"
            conn.execute(
                "INSERT OR IGNORE INTO video_metadata "
                "(video_id, channel_id, title, duration_seconds, source, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (vid, "UCtest000000002", f"LB Video {i}", 1800.0, "takeout", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO processing_status "
                "(video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
                (vid, "UCtest000000002", "collected", "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()

    # Seed baseline phrase for this professor
    add_baseline_phrase(
        professor_id=professor,
        phrase_raw="이번 시간에는 강의를 시작하겠습니다",
        db_path=db_path,
        source_video_ids=["lb_vid_0000"],
        registered_by="test",
    )

    db = ContentDB(db_path)
    try:
        run_nc2_analysis(
            professor=professor,
            channel_alias="test_ch_lb",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
        )
    finally:
        db.close()

    # Check if any match_spans exist with baseline_subtracted=True
    # This assertion is RED until run_nc2_analysis integrates Layer B
    with sqlite3.connect(db_path) as conn:
        total_spans = conn.execute("SELECT COUNT(*) FROM match_spans").fetchone()[0]
        subtracted = conn.execute(
            "SELECT COUNT(*) FROM match_spans WHERE baseline_subtracted = 1"
        ).fetchone()[0]

    assert total_spans > 0, (
        "Expected at least some match_spans to be persisted by run_nc2_analysis"
    )
    assert subtracted > 0, (
        f"Expected some match_spans.baseline_subtracted=True after Layer B, "
        f"but got 0 (total_spans={total_spans}). "
        "run_nc2_analysis must persist match_spans with Layer B filtering."
    )