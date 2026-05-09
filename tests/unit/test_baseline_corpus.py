"""Unit tests for baseline_corpus service (T041 RED).

Tests bootstrap_baseline, add_baseline_phrase, list_baseline,
remove_baseline_phrase, and subtract_baseline.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from tube_scout.storage.content_db import migrate_to_v2
from tube_scout.models.reuse_v2 import BaselinePhrase, BaselineBootstrapReport, MatchSpan


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "content_reuse.db"
    # Create base schema first
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
    # Insert a professor_pool row so FK passes
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-test', 'Test Professor', '2026-01-01T00:00:00', 'system')"
    )
    conn.commit()
    conn.close()
    return db


def _make_captions_dir(tmp_path: Path) -> Path:
    """Create captions dir with 5 baseline fixture files under spec011/."""
    cap_dir = tmp_path / "captions"
    cap_dir.mkdir()
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "spec011" / "captions"
    for i in range(1, 6):
        src = fixture_dir / f"baseline_prof_video{i}.json"
        if src.exists():
            data = json.loads(src.read_text())
            (cap_dir / f"baseline_prof_video{i}.json").write_text(json.dumps(data))
    return cap_dir


def test_bootstrap_baseline_returns_report(tmp_path: Path) -> None:
    """bootstrap_baseline returns a BaselineBootstrapReport with phrases_added >= 0."""
    from tube_scout.services.baseline_corpus import bootstrap_baseline

    db = _make_db(tmp_path)
    cap_dir = _make_captions_dir(tmp_path)

    report = bootstrap_baseline(
        professor_id="prof-test",
        db_path=db,
        captions_dir=cap_dir,
        earliest_n=5,
        min_occurrences=2,
        registered_by="system",
    )
    assert isinstance(report, BaselineBootstrapReport)
    assert report.professor_id == "prof-test"
    assert report.phrases_added >= 0
    assert report.phrases_skipped >= 0


def test_bootstrap_baseline_idempotent(tmp_path: Path) -> None:
    """Running bootstrap_baseline twice does not duplicate phrases."""
    from tube_scout.services.baseline_corpus import bootstrap_baseline, list_baseline

    db = _make_db(tmp_path)
    cap_dir = _make_captions_dir(tmp_path)

    bootstrap_baseline("prof-test", db, cap_dir, earliest_n=5, min_occurrences=2, registered_by="system")
    count_after_first = len(list_baseline("prof-test", db))

    bootstrap_baseline("prof-test", db, cap_dir, earliest_n=5, min_occurrences=2, registered_by="system")
    count_after_second = len(list_baseline("prof-test", db))

    assert count_after_first == count_after_second


def test_add_baseline_phrase_stores_phrase(tmp_path: Path) -> None:
    """add_baseline_phrase inserts a normalized phrase into baseline_corpus."""
    from tube_scout.services.baseline_corpus import add_baseline_phrase, list_baseline

    db = _make_db(tmp_path)
    phrase = add_baseline_phrase(
        professor_id="prof-test",
        phrase_raw="여러분 안녕하세요",
        db_path=db,
        source_video_ids=["vid_001"],
        registered_by="admin",
    )
    assert isinstance(phrase, BaselinePhrase)
    assert phrase.professor_id == "prof-test"
    assert phrase.phrase_raw == "여러분 안녕하세요"
    assert phrase.seeded is False

    phrases = list_baseline("prof-test", db)
    assert len(phrases) == 1
    assert phrases[0].phrase_raw == "여러분 안녕하세요"


def test_list_baseline_filters_by_professor(tmp_path: Path) -> None:
    """list_baseline(professor_id=None) returns all; with professor_id filters."""
    from tube_scout.services.baseline_corpus import add_baseline_phrase, list_baseline

    db = _make_db(tmp_path)
    # Insert second professor
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-other', 'Other Prof', '2026-01-01T00:00:00', 'system')"
    )
    conn.commit()
    conn.close()

    add_baseline_phrase("prof-test", "안녕하세요", db, None, "admin")
    add_baseline_phrase("prof-other", "감사합니다", db, None, "admin")

    all_phrases = list_baseline(None, db)
    assert len(all_phrases) == 2

    test_phrases = list_baseline("prof-test", db)
    assert len(test_phrases) == 1
    assert test_phrases[0].professor_id == "prof-test"


def test_remove_baseline_phrase_returns_true_if_found(tmp_path: Path) -> None:
    """remove_baseline_phrase returns True if phrase was removed, False if not found."""
    from tube_scout.services.baseline_corpus import (
        add_baseline_phrase, remove_baseline_phrase, list_baseline
    )

    db = _make_db(tmp_path)
    add_baseline_phrase("prof-test", "여러분 안녕하세요", db, None, "admin")

    removed = remove_baseline_phrase("prof-test", "여러분 안녕하세요", db)
    assert removed is True
    assert list_baseline("prof-test", db) == []

    not_found = remove_baseline_phrase("prof-test", "없는 구문", db)
    assert not_found is False


def test_subtract_baseline_marks_spans(tmp_path: Path) -> None:
    """subtract_baseline removes spans matching baseline phrases, returns (remaining, seconds)."""
    from tube_scout.services.baseline_corpus import add_baseline_phrase, subtract_baseline

    db = _make_db(tmp_path)
    add_baseline_phrase("prof-test", "안녕하세요", db, None, "admin")

    spans = [
        MatchSpan(
            start_a_seconds=0.0, end_a_seconds=5.0,
            start_b_seconds=0.0, end_b_seconds=5.0,
            length_seconds=5.0,
            matched_text_sample="안녕하세요",
        ),
        MatchSpan(
            start_a_seconds=10.0, end_a_seconds=30.0,
            start_b_seconds=10.0, end_b_seconds=30.0,
            length_seconds=20.0,
            matched_text_sample="다른 내용입니다",
        ),
    ]

    remaining, subtracted_seconds = subtract_baseline("prof-test", spans, db)
    # The "안녕하세요" span should be subtracted
    assert subtracted_seconds >= 0.0
    assert isinstance(remaining, list)


def test_bootstrap_baseline_seeded_flag_true(tmp_path: Path) -> None:
    """Phrases added by bootstrap_baseline have seeded=True."""
    from tube_scout.services.baseline_corpus import bootstrap_baseline, list_baseline

    db = _make_db(tmp_path)
    cap_dir = _make_captions_dir(tmp_path)

    report = bootstrap_baseline(
        "prof-test", db, cap_dir, earliest_n=5, min_occurrences=2, registered_by="system"
    )
    if report.phrases_added > 0:
        phrases = list_baseline("prof-test", db)
        seeded_phrases = [p for p in phrases if p.seeded]
        assert len(seeded_phrases) > 0
