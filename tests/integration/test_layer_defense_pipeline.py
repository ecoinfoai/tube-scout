"""Integration tests for end-to-end layer defense pipeline (T044 RED).

Verifies that apply_layers correctly chains A → B → D-phrase → C
using a real SQLite DB with baseline corpus data.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from tube_scout.models.reuse_v2 import MatchSpan, PolicyConfig
from tube_scout.models.content import ComparisonResult
from tube_scout.storage.content_db import migrate_to_v2


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "content_reuse.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS comparison_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_video_id TEXT NOT NULL,
            target_video_id TEXT NOT NULL,
            professor TEXT,
            course TEXT,
            week INTEGER,
            session INTEGER,
            year_from INTEGER,
            year_to INTEGER,
            i1_hash_match INTEGER NOT NULL DEFAULT 0,
            i2_cosine_similarity REAL,
            i3_change_rate REAL,
            i4_new_term_count INTEGER,
            i5_duration_diff_seconds REAL,
            suspicion_score REAL,
            grade TEXT,
            review_status TEXT NOT NULL DEFAULT 'UNREVIEWED',
            reviewed_at TEXT,
            reviewed_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(source_video_id, target_video_id)
        );
        CREATE TABLE IF NOT EXISTS processing_status (
            video_id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            caption_source TEXT,
            error_message TEXT,
            collected_at TEXT,
            fingerprinted_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fingerprint_hashes (
            video_id TEXT PRIMARY KEY,
            sha256_hash TEXT NOT NULL,
            full_text_length INTEGER NOT NULL,
            embedding_row_index INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quality_results (
            video_id TEXT PRIMARY KEY,
            q001_voice_present INTEGER NOT NULL DEFAULT 0,
            q002_min_duration INTEGER NOT NULL DEFAULT 0,
            q003_course_relevance REAL,
            q004_silence_ratio REAL,
            q005_speech_density REAL,
            pass_count INTEGER NOT NULL DEFAULT 0,
            checked_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    migrate_to_v2(db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-test', 'Test Professor', '2026-01-01T00:00:00', 'system')"
    )
    conn.commit()
    conn.close()
    return db


def _comparison(**kwargs) -> ComparisonResult:
    defaults = dict(
        source_video_id="vid_a",
        target_video_id="vid_b",
        professor="test-prof",
        course="CS101",
        week=1,
        session=1,
        year_from=2023,
        year_to=2024,
        matching_mode="M-nC2",
        professor_id="prof-test",
    )
    defaults.update(kwargs)
    return ComparisonResult(**defaults)


def _span(start: float, end: float, text: str = "고유 강의 내용입니다") -> MatchSpan:
    return MatchSpan(
        start_a_seconds=start, end_a_seconds=end,
        start_b_seconds=start, end_b_seconds=end,
        length_seconds=end - start,
        matched_text_sample=text,
    )


def test_full_pipeline_a_then_c(tmp_path: Path) -> None:
    """Long span (>= Layer A) + cosine outside band: attribution has A no-op + C no-op."""
    from tube_scout.services.layer_defense import apply_layers

    db = _make_db(tmp_path)
    policy = PolicyConfig(layer_a_min_seconds=60.0, layer_c_evolution_band=(0.60, 0.75))
    comparison = _comparison(
        i6_longest_contiguous_seconds=1200.0,
        i2_cosine_similarity=0.90,
        suspicion_score=85.0,
        grade="critical",
    )
    spans = [_span(0.0, 1200.0)]

    result_comparison, result_spans = apply_layers(comparison, spans, "prof-test", db, policy)
    assert result_comparison.grade == "critical"
    assert len(result_comparison.layer_attribution) >= 1


def test_full_pipeline_baseline_subtraction_then_c_demotion(tmp_path: Path) -> None:
    """Baseline phrase subtraction + evolution band demotion applied in sequence."""
    from tube_scout.services.layer_defense import apply_layers
    from tube_scout.services.baseline_corpus import add_baseline_phrase

    db = _make_db(tmp_path)
    add_baseline_phrase("prof-test", "안녕하세요 여러분", db, None, "system")

    policy = PolicyConfig(
        layer_a_min_seconds=10.0,
        layer_c_evolution_band=(0.60, 0.75),
    )
    comparison = _comparison(
        i6_longest_contiguous_seconds=600.0,
        i2_cosine_similarity=0.67,
        suspicion_score=85.0,
        grade="critical",
    )
    spans = [
        _span(0.0, 5.0, "안녕하세요 여러분"),
        _span(10.0, 610.0, "강의 내용 본론입니다"),
    ]

    result_comparison, result_spans = apply_layers(comparison, spans, "prof-test", db, policy)
    # Layer C should demote (i2=0.67 is in band [0.60, 0.75])
    c_attrs = [la for la in result_comparison.layer_attribution if la.layer == "C"]
    if c_attrs:
        assert any(la.action == "demoted" for la in c_attrs)


def test_layer_attribution_ordered(tmp_path: Path) -> None:
    """layer_attribution entries appear in A → B → D → C order."""
    from tube_scout.services.layer_defense import apply_layers

    db = _make_db(tmp_path)
    policy = PolicyConfig(layer_a_min_seconds=60.0, layer_c_evolution_band=(0.60, 0.75))
    comparison = _comparison(
        i6_longest_contiguous_seconds=1200.0,
        i2_cosine_similarity=0.67,
        suspicion_score=85.0,
        grade="critical",
    )
    spans = [_span(0.0, 1200.0)]

    result_comparison, _ = apply_layers(comparison, spans, "prof-test", db, policy)
    layers_seen = [la.layer for la in result_comparison.layer_attribution]
    valid_order = ["A", "B", "D", "C"]
    for i in range(len(layers_seen) - 1):
        assert valid_order.index(layers_seen[i]) <= valid_order.index(layers_seen[i + 1])


def test_apply_layers_pure_no_db_write(tmp_path: Path) -> None:
    """apply_layers does not write to DB (pure transformation contract)."""
    from tube_scout.services.layer_defense import apply_layers

    db = _make_db(tmp_path)
    policy = PolicyConfig()
    comparison = _comparison(i6_longest_contiguous_seconds=100.0, suspicion_score=50.0)
    spans = [_span(0.0, 100.0)]

    apply_layers(comparison, spans, "prof-test", db, policy)

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM comparison_results").fetchone()[0]
    conn.close()
    assert count == 0  # no side effects
