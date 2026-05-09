"""Integration test for Layer D whitelist persistence e2e (T056 RED).

SC-005: mark pair FALSE_POSITIVE + add-phrase → re-run scan produces 0 re-alerts
for whitelisted pair/phrase combinations.
"""

import sqlite3
from pathlib import Path

import pytest

from tests.fixtures.spec011.fixture_db import build_clean_v2_db
from tube_scout.models.reuse_v2 import CandidatePair, MatchSpan, PolicyConfig
from tube_scout.models.content import ComparisonResult


def _make_db(tmp_path: Path) -> Path:
    db = build_clean_v2_db(tmp_path / "content_reuse.db")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-e2e', 'E2E Prof', '2026-01-01T00:00:00', 'system')"
    )
    conn.commit()
    conn.close()
    return db


def _make_comparison(**kwargs) -> ComparisonResult:
    defaults = dict(
        source_video_id="vid_a",
        target_video_id="vid_b",
        professor="E2E Prof",
        course="CS101",
        week=1,
        session=1,
        year_from=2023,
        year_to=2024,
        matching_mode="M-nC2",
        professor_id="prof-e2e",
    )
    defaults.update(kwargs)
    return ComparisonResult(**defaults)


def _make_span(text: str, length: float = 300.0) -> MatchSpan:
    return MatchSpan(
        start_a_seconds=0.0,
        end_a_seconds=length,
        start_b_seconds=0.0,
        end_b_seconds=length,
        length_seconds=length,
        matched_text_sample=text,
    )


def test_sc005_pair_whitelist_suppresses_next_run(tmp_path: Path) -> None:
    """SC-005a: pair marked FALSE_POSITIVE is filtered by filter_pair_whitelisted."""
    from tube_scout.services.phrase_whitelist import add_pair_whitelist
    from tube_scout.services.layer_defense import filter_pair_whitelisted

    db = _make_db(tmp_path)

    # Seed comparison_results row
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR IGNORE INTO comparison_results "
        "(source_video_id, target_video_id, review_status, created_at) "
        "VALUES ('vid_a', 'vid_b', 'UNREVIEWED', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    # Mark pair as FALSE_POSITIVE via whitelist service
    add_pair_whitelist(
        source_video_id="vid_a",
        target_video_id="vid_b",
        reason="same intro clip — confirmed false positive",
        db_path=db,
        registered_by="admin",
    )

    # Simulate re-run: candidate pair appears again
    candidates = [
        CandidatePair(
            source_video_id="vid_a",
            target_video_id="vid_b",
            cosine=0.95,
            professor_id="prof-e2e",
        ),
        CandidatePair(
            source_video_id="vid_c",
            target_video_id="vid_d",
            cosine=0.85,
            professor_id="prof-e2e",
        ),
    ]

    remaining = filter_pair_whitelisted(candidates, db)

    # vid_a / vid_b must be excluded; vid_c / vid_d must remain
    ids = [(c.source_video_id, c.target_video_id) for c in remaining]
    assert ("vid_a", "vid_b") not in ids, "FALSE_POSITIVE pair should be filtered"
    assert ("vid_c", "vid_d") in ids, "Non-whitelisted pair should remain"


def test_sc005_phrase_whitelist_suppresses_span_in_next_run(tmp_path: Path) -> None:
    """SC-005b: whitelisted phrase removed from spans by subtract_phrase_whitelist."""
    from tube_scout.services.phrase_whitelist import (
        add_phrase_whitelist,
        subtract_phrase_whitelist,
    )

    db = _make_db(tmp_path)

    add_phrase_whitelist(
        professor_id="prof-e2e",
        phrase_raw="안녕하세요 여러분",
        reason="habitual greeting",
        db_path=db,
        registered_by="admin",
    )

    spans = [
        _make_span("안녕하세요 여러분", 5.0),
        _make_span("강의 본론 내용", 300.0),
    ]

    remaining, removed_count = subtract_phrase_whitelist("prof-e2e", spans, db)

    assert removed_count == 1, f"Expected 1 removed, got {removed_count}"
    assert len(remaining) == 1
    assert remaining[0].matched_text_sample == "강의 본론 내용"


def test_sc005_full_pipeline_pair_plus_phrase_whitelist(tmp_path: Path) -> None:
    """SC-005c: combined pair whitelist + phrase whitelist in apply_layers pipeline."""
    from tube_scout.services.phrase_whitelist import add_phrase_whitelist
    from tube_scout.services.layer_defense import apply_layers

    db = _make_db(tmp_path)
    add_phrase_whitelist("prof-e2e", "안녕하세요 여러분", "habitual", db, "admin")

    policy = PolicyConfig(layer_a_min_seconds=10.0, layer_c_evolution_band=(0.60, 0.75))
    comparison = _make_comparison(
        i6_longest_contiguous_seconds=305.0,
        i2_cosine_similarity=0.90,
        suspicion_score=80.0,
        grade="high",
    )
    spans = [
        _make_span("안녕하세요 여러분", 5.0),
        _make_span("강의 본론 내용", 300.0),
    ]

    updated, remaining_spans = apply_layers(comparison, spans, "prof-e2e", db, policy)

    # Layer D attribution should note subtraction
    d_attrs = [a for a in updated.layer_attribution if a.layer == "D"]
    assert d_attrs, "Layer D attribution missing"

    # The whitelisted phrase span should be removed
    remaining_texts = [s.matched_text_sample for s in remaining_spans]
    assert "안녕하세요 여러분" not in remaining_texts
    assert "강의 본론 내용" in remaining_texts


def test_sc005_pair_whitelist_persists_across_reconnect(tmp_path: Path) -> None:
    """SC-005d: FALSE_POSITIVE status survives DB reconnect (persistence)."""
    from tube_scout.services.phrase_whitelist import add_pair_whitelist

    db = _make_db(tmp_path)

    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR IGNORE INTO comparison_results "
        "(source_video_id, target_video_id, review_status, created_at) "
        "VALUES ('vid_x', 'vid_y', 'UNREVIEWED', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    add_pair_whitelist("vid_x", "vid_y", "persistent test", db, "admin")

    # Reconnect and verify
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT review_status FROM comparison_results "
        "WHERE source_video_id='vid_x' AND target_video_id='vid_y'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "FALSE_POSITIVE", f"Expected FALSE_POSITIVE after reconnect, got {row[0]}"
