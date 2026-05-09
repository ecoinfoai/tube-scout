"""SQLite storage wrapper for content reuse detection data.

Manages processing status, fingerprint hashes, comparison results,
and quality check results in a single SQLite database per project.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA_SQL = """
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


class ContentDB:
    """SQLite wrapper for content reuse detection storage.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize database and create schema if needed.

        Args:
            db_path: Path to the SQLite database file.
        """
        if not isinstance(db_path, Path):
            raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def _now(self) -> str:
        """Return current UTC timestamp as ISO string."""
        return datetime.now(UTC).isoformat()

    # ─── processing_status ───

    def upsert_processing_status(
        self,
        video_id: str,
        channel_id: str,
        status: str,
        *,
        caption_source: str | None = None,
        error_message: str | None = None,
        collected_at: str | None = None,
        fingerprinted_at: str | None = None,
    ) -> None:
        """Insert or update a video's processing status.

        Args:
            video_id: YouTube video ID.
            channel_id: Channel the video belongs to.
            status: Processing state.
            caption_source: How captions were obtained.
            error_message: Error message if failed.
            collected_at: When caption was collected.
            fingerprinted_at: When fingerprint was generated.
        """
        self._conn.execute(
            """
            INSERT INTO processing_status
                (video_id, channel_id, status, caption_source, error_message,
                 collected_at, fingerprinted_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                status = excluded.status,
                caption_source = COALESCE(
                    excluded.caption_source,
                    processing_status.caption_source
                ),
                error_message = excluded.error_message,
                collected_at = COALESCE(
                    excluded.collected_at,
                    processing_status.collected_at
                ),
                fingerprinted_at = COALESCE(
                    excluded.fingerprinted_at,
                    processing_status.fingerprinted_at
                ),
                updated_at = excluded.updated_at
            """,
            (video_id, channel_id, status, caption_source, error_message,
             collected_at, fingerprinted_at, self._now()),
        )
        self._conn.commit()

    def get_processing_status(self, video_id: str) -> dict[str, Any] | None:
        """Get processing status for a video.

        Args:
            video_id: YouTube video ID.

        Returns:
            Status dict or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM processing_status WHERE video_id = ?", (video_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_processing_status(
        self,
        *,
        status: str | None = None,
        channel_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List processing statuses with optional filters.

        Args:
            status: Filter by processing status.
            channel_id: Filter by channel ID.

        Returns:
            List of status dicts.
        """
        query = "SELECT * FROM processing_status WHERE 1=1"
        params: list[Any] = []
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if channel_id is not None:
            query += " AND channel_id = ?"
            params.append(channel_id)
        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    # ─── fingerprint_hashes ───

    def upsert_fingerprint(
        self,
        video_id: str,
        sha256_hash: str,
        full_text_length: int,
        *,
        embedding_row_index: int | None = None,
    ) -> None:
        """Insert or update a fingerprint hash.

        Args:
            video_id: YouTube video ID.
            sha256_hash: SHA-256 hex digest.
            full_text_length: Character count.
            embedding_row_index: Row index in embeddings.parquet.
        """
        self._conn.execute(
            """
            INSERT INTO fingerprint_hashes
                (video_id, sha256_hash, full_text_length,
                 embedding_row_index, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                sha256_hash = excluded.sha256_hash,
                full_text_length = excluded.full_text_length,
                embedding_row_index = COALESCE(
                    excluded.embedding_row_index,
                    fingerprint_hashes.embedding_row_index
                ),
                created_at = excluded.created_at
            """,
            (video_id, sha256_hash, full_text_length, embedding_row_index, self._now()),
        )
        self._conn.commit()

    def get_fingerprint(self, video_id: str) -> dict[str, Any] | None:
        """Get fingerprint for a video.

        Args:
            video_id: YouTube video ID.

        Returns:
            Fingerprint dict or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM fingerprint_hashes WHERE video_id = ?", (video_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def find_by_hash(self, sha256_hash: str) -> list[dict[str, Any]]:
        """Find all videos with a given hash.

        Args:
            sha256_hash: SHA-256 hex digest to search.

        Returns:
            List of fingerprint dicts with matching hash.
        """
        cursor = self._conn.execute(
            "SELECT * FROM fingerprint_hashes WHERE sha256_hash = ?", (sha256_hash,)
        )
        return [dict(row) for row in cursor.fetchall()]

    # ─── comparison_results ───

    def insert_comparison(
        self,
        *,
        source_video_id: str,
        target_video_id: str,
        professor: str,
        course: str,
        week: int,
        session: int,
        year_from: int,
        year_to: int,
        i1_hash_match: bool = False,
        i2_cosine_similarity: float | None = None,
        i3_change_rate: float | None = None,
        i4_new_term_count: int | None = None,
        i5_duration_diff_seconds: float | None = None,
        suspicion_score: float | None = None,
        grade: str | None = None,
    ) -> int:
        """Insert a new comparison result.

        Args:
            source_video_id: Video from year A.
            target_video_id: Video from year B.
            professor: Matched professor name.
            course: Matched course name.
            week: Matched week number.
            session: Matched session number.
            year_from: Source video year.
            year_to: Target video year.
            i1_hash_match: SHA-256 hash match.
            i2_cosine_similarity: Cosine similarity score.
            i3_change_rate: Text change rate.
            i4_new_term_count: New term count.
            i5_duration_diff_seconds: Duration difference.
            suspicion_score: Composite score.
            grade: Priority grade.

        Returns:
            ID of the inserted comparison.

        Raises:
            sqlite3.IntegrityError: If pair already exists.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO comparison_results
                (source_video_id, target_video_id, professor, course, week, session,
                 year_from, year_to, i1_hash_match, i2_cosine_similarity,
                 i3_change_rate, i4_new_term_count, i5_duration_diff_seconds,
                 suspicion_score, grade, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_video_id, target_video_id, professor, course, week, session,
             year_from, year_to, int(i1_hash_match), i2_cosine_similarity,
             i3_change_rate, i4_new_term_count, i5_duration_diff_seconds,
             suspicion_score, grade, self._now()),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_comparison(self, comparison_id: int) -> dict[str, Any] | None:
        """Get a comparison result by ID.

        Args:
            comparison_id: Comparison ID.

        Returns:
            Comparison dict or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM comparison_results WHERE id = ?", (comparison_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_comparisons(
        self,
        *,
        review_status: str | None = None,
        grade: str | None = None,
        order_by_suspicion: bool = False,
    ) -> list[dict[str, Any]]:
        """List comparison results with optional filters.

        Args:
            review_status: Filter by review status.
            grade: Filter by grade.
            order_by_suspicion: Sort by suspicion_score descending.

        Returns:
            List of comparison dicts.
        """
        query = "SELECT * FROM comparison_results WHERE 1=1"
        params: list[Any] = []
        if review_status is not None:
            query += " AND review_status = ?"
            params.append(review_status)
        if grade is not None:
            query += " AND grade = ?"
            params.append(grade)
        if order_by_suspicion:
            query += " ORDER BY suspicion_score DESC"
        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def update_review_status(
        self,
        comparison_id: int,
        review_status: str,
        *,
        reviewed_by: str | None = None,
    ) -> None:
        """Update the review status of a comparison.

        Args:
            comparison_id: Comparison ID.
            review_status: New review status.
            reviewed_by: Reviewer identifier.

        Raises:
            ValueError: If comparison_id does not exist.
        """
        cursor = self._conn.execute(
            """
            UPDATE comparison_results
            SET review_status = ?, reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (review_status, self._now(), reviewed_by, comparison_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Comparison ID {comparison_id} not found")
        self._conn.commit()

    # ─── quality_results ───

    def upsert_quality_result(
        self,
        video_id: str,
        *,
        q001_voice_present: bool = False,
        q002_min_duration: bool = False,
        q003_course_relevance: float | None = None,
        q004_silence_ratio: float | None = None,
        q005_speech_density: float | None = None,
        pass_count: int = 0,
    ) -> None:
        """Insert or update a quality check result.

        Args:
            video_id: YouTube video ID.
            q001_voice_present: Has extractable captions.
            q002_min_duration: Duration >= 5 minutes.
            q003_course_relevance: Proportion of course-related terms.
            q004_silence_ratio: Ratio of inter-segment gaps.
            q005_speech_density: Characters per minute.
            pass_count: Number of rules passed.
        """
        self._conn.execute(
            """
            INSERT INTO quality_results
                (video_id, q001_voice_present, q002_min_duration,
                 q003_course_relevance, q004_silence_ratio, q005_speech_density,
                 pass_count, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                q001_voice_present = excluded.q001_voice_present,
                q002_min_duration = excluded.q002_min_duration,
                q003_course_relevance = excluded.q003_course_relevance,
                q004_silence_ratio = excluded.q004_silence_ratio,
                q005_speech_density = excluded.q005_speech_density,
                pass_count = excluded.pass_count,
                checked_at = excluded.checked_at
            """,
            (video_id, int(q001_voice_present), int(q002_min_duration),
             q003_course_relevance, q004_silence_ratio, q005_speech_density,
             pass_count, self._now()),
        )
        self._conn.commit()

    def get_quality_result(self, video_id: str) -> dict[str, Any] | None:
        """Get quality check result for a video.

        Args:
            video_id: YouTube video ID.

        Returns:
            Quality result dict or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM quality_results WHERE video_id = ?", (video_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


# ─── spec 011 v2 migration ───

_V2_NEW_COLUMNS: list[tuple[str, str]] = [
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

_V2_NEW_TABLES_SQL = """
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
    length_seconds REAL NOT NULL CHECK (length_seconds >= 0),
    matched_text_sample TEXT,
    baseline_subtracted INTEGER NOT NULL DEFAULT 0,
    whitelisted INTEGER NOT NULL DEFAULT 0,
    UNIQUE (comparison_id, span_index),
    FOREIGN KEY (comparison_id) REFERENCES comparison_results(id)
);

CREATE TABLE IF NOT EXISTS _schema_version (
    spec TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""

_V2_NEW_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_cr_mode ON comparison_results(matching_mode);
CREATE INDEX IF NOT EXISTS idx_cr_prof ON comparison_results(professor_id);
CREATE INDEX IF NOT EXISTS idx_cr_pattern ON comparison_results(reuse_pattern);
CREATE INDEX IF NOT EXISTS idx_span_cmp ON match_spans(comparison_id);
"""


def migrate_to_v2(db_path: Path) -> None:
    """Apply spec 011 v2 schema migration to an existing content_reuse.db.

    Idempotent: safe to call multiple times. Skips columns and tables that
    already exist. All DDL executes inside a single transaction; any failure
    triggers a full rollback leaving the DB in its pre-migration state.

    Migration order (per contracts/db_schema.md §1):
      1. Read existing schema state.
      2. ALTER comparison_results — add 10 new columns (missing only).
      3. CREATE 6 new tables + _schema_version (IF NOT EXISTS).
      4. CREATE 4 new indexes (IF NOT EXISTS).
      5. Backfill matching_mode = 'M-default' for legacy NULL rows.
      6. PRAGMA integrity_check.
      7. Stamp _schema_version ('spec-011', 'v1').

    Args:
        db_path: Path to the SQLite database file.

    Raises:
        TypeError: If db_path is not a Path instance.
        RuntimeError: If integrity_check fails or a required schema element
            is missing after migration. Message includes actionable next step.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute("BEGIN")

        # Step 1 — read existing columns
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(comparison_results)").fetchall()
        }
        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        # Step 2 — ALTER missing columns
        for col_name, col_def in _V2_NEW_COLUMNS:
            if col_name not in existing_cols:
                conn.execute(
                    f"ALTER TABLE comparison_results ADD COLUMN {col_name} {col_def}"
                )

        # Step 3 — CREATE new tables (IF NOT EXISTS handles idempotency)
        conn.executescript(_V2_NEW_TABLES_SQL)

        # Step 4 — CREATE new indexes
        conn.executescript(_V2_NEW_INDEXES_SQL)

        # Step 5 — backfill matching_mode for legacy rows that predate DEFAULT
        conn.execute(
            "UPDATE comparison_results SET matching_mode = 'M-default' "
            "WHERE matching_mode IS NULL"
        )

        conn.execute("COMMIT")

        # Step 6 — integrity check (outside transaction, read-only check)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise RuntimeError(
                f"SQLite integrity check failed for {db_path}. "
                "Restore from backup or remove the file and re-collect."
            )

        # Step 7 — verify required schema elements exist
        final_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(comparison_results)").fetchall()
        }
        for col_name, _ in _V2_NEW_COLUMNS:
            if col_name not in final_cols:
                raise RuntimeError(
                    f"Migration verification failed: column '{col_name}' missing "
                    f"from comparison_results in {db_path}. Re-run migrate_to_v2."
                )

        final_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in (
            "professor_pool", "professor_pool_membership", "baseline_corpus",
            "phrase_whitelist", "pair_checkpoint", "match_spans", "_schema_version",
        ):
            if table not in final_tables:
                raise RuntimeError(
                    f"Migration verification failed: table '{table}' missing "
                    f"in {db_path}. Re-run migrate_to_v2."
                )

        # Stamp schema version
        applied_at = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO _schema_version (spec, version, applied_at) "
            "VALUES (?, ?, ?)",
            ("spec-011", "v1", applied_at),
        )
        conn.commit()

    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
