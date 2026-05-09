"""Deterministic SQLite fixture builders for spec 011 tests.

Each function creates a fresh database at the given path and returns
the same path. All builders are deterministic: the same call always
produces the same schema state and seed data so tests can rely on
stable assertions without side effects.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_SPEC007_SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_fp_hash ON fingerprint_hashes(sha256_hash);

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
CREATE INDEX IF NOT EXISTS idx_cr_grade ON comparison_results(grade);
CREATE INDEX IF NOT EXISTS idx_cr_review ON comparison_results(review_status);

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
"""

_V2_MIGRATION = """
ALTER TABLE comparison_results ADD COLUMN matching_mode TEXT NOT NULL DEFAULT 'M-default';
ALTER TABLE comparison_results ADD COLUMN professor_id TEXT;
ALTER TABLE comparison_results ADD COLUMN i6_longest_contiguous_seconds REAL;
ALTER TABLE comparison_results ADD COLUMN i7_distribution_dispersion REAL;
ALTER TABLE comparison_results ADD COLUMN i8_position_diversity REAL;
ALTER TABLE comparison_results ADD COLUMN reuse_pattern TEXT;
ALTER TABLE comparison_results ADD COLUMN layer_attribution TEXT;
ALTER TABLE comparison_results ADD COLUMN baseline_subtracted_length_seconds REAL;
ALTER TABLE comparison_results ADD COLUMN pre_subtraction_i2 REAL;
ALTER TABLE comparison_results ADD COLUMN pre_subtraction_i6 REAL;

CREATE INDEX IF NOT EXISTS idx_cr_mode ON comparison_results(matching_mode);
CREATE INDEX IF NOT EXISTS idx_cr_prof ON comparison_results(professor_id);
CREATE INDEX IF NOT EXISTS idx_cr_pattern ON comparison_results(reuse_pattern);

CREATE TABLE IF NOT EXISTS professor_pool (
    professor_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS professor_pool_membership (
    professor_id TEXT NOT NULL,
    channel_alias TEXT NOT NULL,
    author_marker TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    PRIMARY KEY (professor_id, channel_alias, author_marker),
    FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
);

CREATE TABLE IF NOT EXISTS baseline_corpus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    professor_id TEXT NOT NULL,
    phrase_normalized TEXT NOT NULL,
    phrase_raw TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    source_video_ids TEXT,
    seeded INTEGER NOT NULL DEFAULT 0,
    registered_at TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    UNIQUE(professor_id, phrase_normalized),
    FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
);

CREATE TABLE IF NOT EXISTS phrase_whitelist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    professor_id TEXT NOT NULL,
    phrase_normalized TEXT NOT NULL,
    phrase_raw TEXT NOT NULL,
    reason TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    UNIQUE(professor_id, phrase_normalized),
    FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
);

CREATE TABLE IF NOT EXISTS pair_checkpoint (
    run_id TEXT PRIMARY KEY,
    professor_id TEXT NOT NULL,
    matching_mode TEXT NOT NULL,
    pair_count_total INTEGER NOT NULL,
    pair_count_done INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    last_pair_at TEXT,
    status TEXT NOT NULL,
    CHECK (status IN ('in_progress', 'completed', 'aborted'))
);

CREATE TABLE IF NOT EXISTS match_spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id INTEGER NOT NULL,
    span_index INTEGER NOT NULL,
    start_a_seconds REAL NOT NULL,
    end_a_seconds REAL NOT NULL,
    start_b_seconds REAL NOT NULL,
    end_b_seconds REAL NOT NULL,
    length_seconds REAL NOT NULL,
    matched_text_sample TEXT,
    baseline_subtracted INTEGER NOT NULL DEFAULT 0,
    whitelisted INTEGER NOT NULL DEFAULT 0,
    UNIQUE (comparison_id, span_index),
    FOREIGN KEY (comparison_id) REFERENCES comparison_results(id)
);
CREATE INDEX IF NOT EXISTS idx_span_cmp ON match_spans(comparison_id);

CREATE TABLE IF NOT EXISTS _schema_version (
    spec TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""

_NOW = "2026-05-09T00:00:00+00:00"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _apply_v2_migration(conn: sqlite3.Connection) -> None:
    """Apply spec 011 v2 migration DDL, skipping already-present columns.

    Args:
        conn: Open SQLite connection with spec 007 schema already applied.
    """
    cursor = conn.execute("PRAGMA table_info(comparison_results)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("matching_mode", "TEXT NOT NULL DEFAULT 'M-default'"),
        ("professor_id", "TEXT"),
        ("i6_longest_contiguous_seconds", "REAL"),
        ("i7_distribution_dispersion", "REAL"),
        ("i8_position_diversity", "REAL"),
        ("reuse_pattern", "TEXT"),
        ("layer_attribution", "TEXT"),
        ("baseline_subtracted_length_seconds", "REAL"),
        ("pre_subtraction_i2", "REAL"),
        ("pre_subtraction_i6", "REAL"),
    ]
    for col_name, col_def in new_columns:
        if col_name not in existing_cols:
            conn.execute(
                f"ALTER TABLE comparison_results ADD COLUMN {col_name} {col_def}"
            )

    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_cr_mode ON comparison_results(matching_mode);
        CREATE INDEX IF NOT EXISTS idx_cr_prof ON comparison_results(professor_id);
        CREATE INDEX IF NOT EXISTS idx_cr_pattern ON comparison_results(reuse_pattern);

        CREATE TABLE IF NOT EXISTS professor_pool (
            professor_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS professor_pool_membership (
            professor_id TEXT NOT NULL,
            channel_alias TEXT NOT NULL,
            author_marker TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL,
            PRIMARY KEY (professor_id, channel_alias, author_marker),
            FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
        );

        CREATE TABLE IF NOT EXISTS baseline_corpus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id TEXT NOT NULL,
            phrase_normalized TEXT NOT NULL,
            phrase_raw TEXT NOT NULL,
            occurrences INTEGER NOT NULL DEFAULT 1,
            source_video_ids TEXT,
            seeded INTEGER NOT NULL DEFAULT 0,
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL,
            UNIQUE(professor_id, phrase_normalized),
            FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
        );

        CREATE TABLE IF NOT EXISTS phrase_whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id TEXT NOT NULL,
            phrase_normalized TEXT NOT NULL,
            phrase_raw TEXT NOT NULL,
            reason TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL,
            UNIQUE(professor_id, phrase_normalized),
            FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
        );

        CREATE TABLE IF NOT EXISTS pair_checkpoint (
            run_id TEXT PRIMARY KEY,
            professor_id TEXT NOT NULL,
            matching_mode TEXT NOT NULL,
            pair_count_total INTEGER NOT NULL,
            pair_count_done INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            last_pair_at TEXT,
            status TEXT NOT NULL,
            CHECK (status IN ('in_progress', 'completed', 'aborted'))
        );

        CREATE TABLE IF NOT EXISTS match_spans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comparison_id INTEGER NOT NULL,
            span_index INTEGER NOT NULL,
            start_a_seconds REAL NOT NULL,
            end_a_seconds REAL NOT NULL,
            start_b_seconds REAL NOT NULL,
            end_b_seconds REAL NOT NULL,
            length_seconds REAL NOT NULL,
            matched_text_sample TEXT,
            baseline_subtracted INTEGER NOT NULL DEFAULT 0,
            whitelisted INTEGER NOT NULL DEFAULT 0,
            UNIQUE (comparison_id, span_index),
            FOREIGN KEY (comparison_id) REFERENCES comparison_results(id)
        );

        CREATE INDEX IF NOT EXISTS idx_span_cmp ON match_spans(comparison_id);

        CREATE TABLE IF NOT EXISTS _schema_version (
            spec TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
    """)

    conn.execute(
        "INSERT OR REPLACE INTO _schema_version (spec, version, applied_at) VALUES (?, ?, ?)",
        ("spec-011", "v1", _NOW),
    )
    conn.commit()


def build_clean_v2_db(path: Path) -> Path:
    """Build a fresh spec 011 v2-migrated SQLite database.

    Creates the full v2 schema including all spec 007 tables and all
    spec 011 extension tables. Idempotent: recreates the file each call.

    Args:
        path: Filesystem path for the new SQLite file. Parent dirs are
            created automatically.

    Returns:
        The same ``path`` after the database has been initialised.
    """
    if not isinstance(path, Path):
        raise TypeError(f"path must be a Path, got {type(path).__name__}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(str(path))
    conn.executescript(_SPEC007_SCHEMA)
    _apply_v2_migration(conn)
    conn.close()
    return path


def build_spec007_legacy_db(path: Path) -> Path:
    """Build a spec 007 legacy SQLite database without v2 migration.

    Creates only the original spec 007 schema so that backward-compat
    tests can verify that ``migrate_to_v2`` handles pre-existing databases
    correctly.

    Args:
        path: Filesystem path for the new SQLite file.

    Returns:
        The same ``path`` after the database has been initialised.
    """
    if not isinstance(path, Path):
        raise TypeError(f"path must be a Path, got {type(path).__name__}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(str(path))
    conn.executescript(_SPEC007_SCHEMA)

    # 10 sample comparison rows — used by backward-compat tests to confirm
    # that migrate_to_v2 preserves all existing rows and their column values.
    legacy_rows = [
        (f"legacy_vid_{i:03d}", f"legacy_vid_{i+10:03d}",
         "prof-test", f"CS{100+i}", i % 8 + 1, 1,
         2024, 2025, 0,
         round(0.60 + i * 0.03, 2),
         round(0.15 - i * 0.01, 2),
         2, 30.0 + i,
         round(0.55 + i * 0.03, 2),
         "high" if i < 5 else "moderate",
         _NOW)
        for i in range(10)
    ]
    conn.executemany(
        """
        INSERT INTO comparison_results
            (source_video_id, target_video_id, professor, course, week, session,
             year_from, year_to, i1_hash_match, i2_cosine_similarity,
             i3_change_rate, i4_new_term_count, i5_duration_diff_seconds,
             suspicion_score, grade, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        legacy_rows,
    )
    conn.commit()
    conn.close()
    return path


def build_200_vid_pool(path: Path, professor_id: str) -> Path:
    """Build a v2 database pre-populated with a 200-video professor pool.

    Used by performance budget tests (SC-001: nC2 analysis ≤ 30 min for
    200 videos). Inserts 200 processing_status rows and 200 fingerprint
    rows with deterministic fake hashes. Note: embeddings.parquet is not
    written by this builder — tests that need embedding vectors should
    create a synthetic parquet alongside the DB using polars.

    Args:
        path: Filesystem path for the new SQLite file.
        professor_id: Professor identifier to use for pool membership rows.

    Returns:
        The same ``path`` after the database has been initialised.

    Raises:
        TypeError: If ``path`` is not a Path or ``professor_id`` is not a str.
        ValueError: If ``professor_id`` is empty.
    """
    if not isinstance(path, Path):
        raise TypeError(f"path must be a Path, got {type(path).__name__}")
    if not isinstance(professor_id, str):
        raise TypeError(
            f"professor_id must be a str, got {type(professor_id).__name__}"
        )
    if not professor_id.strip():
        raise ValueError("professor_id must not be empty")

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(str(path))
    conn.executescript(_SPEC007_SCHEMA)
    _apply_v2_migration(conn)

    conn.execute(
        "INSERT OR IGNORE INTO professor_pool "
        "(professor_id, display_name, created_at, created_by) VALUES (?, ?, ?, ?)",
        (professor_id, "Test Professor", _NOW, "fixture"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool_membership "
        "(professor_id, channel_alias, author_marker, registered_at, registered_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (professor_id, "ch-test", "__channel_owner__", _NOW, "fixture"),
    )

    status_rows = []
    fp_rows = []
    for i in range(200):
        vid = f"pool_vid_{i:04d}"
        fake_hash = f"deadbeef{i:056x}"[:64]
        status_rows.append(
            (vid, "ch-test", "fingerprinted", "auto_generated", _NOW, _NOW, _NOW)
        )
        fp_rows.append((vid, fake_hash, 5000 + i * 10, i, _NOW))

    conn.executemany(
        "INSERT OR IGNORE INTO processing_status "
        "(video_id, channel_id, status, caption_source, collected_at, fingerprinted_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        status_rows,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO fingerprint_hashes "
        "(video_id, sha256_hash, full_text_length, embedding_row_index, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        fp_rows,
    )
    conn.commit()
    conn.close()
    return path


def build_4000_pair_partial(path: Path, completed_count: int) -> Path:
    """Build a v2 database with a partially-completed 4000-pair nC2 run.

    Simulates an interrupted overnight run where ``completed_count`` pairs
    already have results. Used by resume/checkpoint tests (FR-031).

    Args:
        path: Filesystem path for the new SQLite file.
        completed_count: Number of comparison_results rows to pre-populate
            (must be between 0 and 4000 inclusive).

    Returns:
        The same ``path`` after the database has been initialised.

    Raises:
        TypeError: If ``path`` is not a Path or ``completed_count`` is not an int.
        ValueError: If ``completed_count`` is not in [0, 4000].
    """
    if not isinstance(path, Path):
        raise TypeError(f"path must be a Path, got {type(path).__name__}")
    if not isinstance(completed_count, int):
        raise TypeError(
            f"completed_count must be an int, got {type(completed_count).__name__}"
        )
    if not (0 <= completed_count <= 4000):
        raise ValueError(
            f"completed_count must be between 0 and 4000, got {completed_count}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(str(path))
    conn.executescript(_SPEC007_SCHEMA)
    _apply_v2_migration(conn)

    professor_id = "prof-perf-test"
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool "
        "(professor_id, display_name, created_at, created_by) VALUES (?, ?, ?, ?)",
        (professor_id, "Perf Test Professor", _NOW, "fixture"),
    )

    conn.execute(
        "INSERT OR IGNORE INTO pair_checkpoint "
        "(run_id, professor_id, matching_mode, pair_count_total, pair_count_done, "
        " started_at, last_pair_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "nc2-prof-perf-test-20260509-0000",
            professor_id,
            "M-nC2",
            4000,
            completed_count,
            _NOW,
            _NOW if completed_count > 0 else None,
            "in_progress" if completed_count < 4000 else "completed",
        ),
    )

    # Build deterministic (src, tgt) pair list and insert completed rows
    pair_index = 0
    rows: list[tuple] = []
    outer = 0
    while pair_index < completed_count and outer < 100:
        inner = outer + 1
        while pair_index < completed_count and inner < 100:
            src = f"perf_vid_{outer:04d}"
            tgt = f"perf_vid_{inner:04d}"
            rows.append((
                src, tgt,
                "M-nC2", professor_id,
                0, 0.72, 0.15, 2, 30.0,
                0.65, "moderate",
                "UNREVIEWED",
                _NOW,
            ))
            pair_index += 1
            inner += 1
        outer += 1

    conn.executemany(
        """
        INSERT OR IGNORE INTO comparison_results
            (source_video_id, target_video_id, matching_mode, professor_id,
             i1_hash_match, i2_cosine_similarity, i3_change_rate, i4_new_term_count,
             i5_duration_diff_seconds, suspicion_score, grade, review_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return path
