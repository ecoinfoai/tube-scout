"""SQLite connection factory + schema bootstrap (T021).

Single source of truth for the admin web UI persistence layer:

- ``connect()`` returns a :class:`sqlite3.Connection` with WAL mode, foreign
  keys, and length() casting enabled.
- ``bootstrap()`` is idempotent — runs ``CREATE TABLE IF NOT EXISTS`` for the
  5 entities defined in data-model.md plus their indexes and a
  ``schema_migrations`` version row.
- ``checkpoint()`` runs ``PRAGMA wal_checkpoint(TRUNCATE)`` for the shutdown
  hook (architect ADR R-3).

Constitution V (Local-First): SQLite single file under ``$STATE_DIR``;
no external broker.
Constitution II (Fail-Fast): ``connect()`` enables ``foreign_keys=ON`` so FK
violations surface immediately rather than silently inserting orphans.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tube_scout.web.paths import get_state_dir

CURRENT_SCHEMA_VERSION = 1

_DB_FILENAME = "admin.db"


def db_path() -> Path:
    """Return the absolute path to ``admin.db`` under the current state dir."""
    return get_state_dir() / _DB_FILENAME


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with the project's standard pragmas.

    Args:
        path: Override database file location. Defaults to :func:`db_path`.

    Returns:
        :class:`sqlite3.Connection` with row factory set to :class:`sqlite3.Row`,
        WAL journal mode enabled, foreign keys enabled, and a 5s busy timeout.

    Raises:
        sqlite3.OperationalError: If the path's parent directory is missing
            (caller must :func:`tube_scout.web.paths.ensure_runtime_dirs`).
    """
    target = path or db_path()
    if not target.parent.exists():
        raise sqlite3.OperationalError(
            f"State directory missing: {target.parent}. "
            "Call ensure_runtime_dirs() before connect()."
        )
    conn = sqlite3.connect(
        str(target),
        timeout=5.0,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_jobs (
        job_id TEXT PRIMARY KEY,
        department_alias TEXT NOT NULL,
        professor_name TEXT NOT NULL,
        course_name TEXT NOT NULL,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('pending','running','completed','failed','interrupted')
        ),
        current_stage TEXT CHECK (
            current_stage IN (
                'listing','metadata','transcripts','retention',
                'analytics','reuse_detection','reporting','done'
            ) OR current_stage IS NULL
        ),
        processed_count INTEGER NOT NULL DEFAULT 0
            CHECK (processed_count >= 0),
        total_count INTEGER NOT NULL DEFAULT 0
            CHECK (total_count >= 0 AND total_count >= processed_count),
        result_dir TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        error_code TEXT,
        error_detail TEXT,
        created_by TEXT NOT NULL,
        CHECK (period_start <= period_end)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_jobs_started_at_desc
        ON analysis_jobs (started_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_jobs_status_dept
        ON analysis_jobs (status, department_alias)
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_results (
        job_id TEXT PRIMARY KEY
            REFERENCES analysis_jobs(job_id) ON DELETE CASCADE,
        report_v1v3_html TEXT,
        report_v1v3_pdf TEXT,
        report_v1v3_excel TEXT,
        report_reuse_html TEXT,
        report_reuse_excel TEXT,
        matched_video_count INTEGER NOT NULL DEFAULT 0
            CHECK (matched_video_count >= 0),
        suspicious_pair_count INTEGER NOT NULL DEFAULT 0
            CHECK (suspicious_pair_count >= 0),
        priority_summary TEXT NOT NULL,
        generated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reuse_review_status (
        pair_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL
            REFERENCES analysis_jobs(job_id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'unreviewed' CHECK (
            status IN ('unreviewed','confirmed_duplicate','false_positive')
        ),
        updated_at TEXT,
        updated_by TEXT,
        note TEXT CHECK (note IS NULL OR length(note) <= 512)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_review_status
        ON reuse_review_status (status)
    """,
    """
    CREATE TABLE IF NOT EXISTS operator_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL CHECK (
            action IN (
                'add_department','oauth_consent','token_refresh',
                'status_check','verify'
            )
        ),
        target_alias TEXT,
        actor TEXT NOT NULL,
        at TEXT NOT NULL,
        result TEXT NOT NULL CHECK (result IN ('success','failure')),
        detail TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_op_at_desc
        ON operator_actions (at DESC)
    """,
)


def bootstrap(path: Path | None = None) -> None:
    """Create all tables and indexes if missing; record the schema version.

    Idempotent — safe to call on every app startup. Honors ``foreign_keys=ON``
    via :func:`connect`.

    Args:
        path: Override database file location for tests; defaults to
            :func:`db_path`.

    Raises:
        sqlite3.OperationalError: When the SQL itself is malformed (regression).
    """
    from tube_scout.web.paths import ensure_runtime_dirs

    ensure_runtime_dirs()
    conn = connect(path=path)
    try:
        with conn:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            cursor = conn.execute(
                "SELECT MAX(version) FROM schema_migrations"
            )
            current = cursor.fetchone()[0]
            if current is None or current < CURRENT_SCHEMA_VERSION:
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, datetime('now'))",
                    (CURRENT_SCHEMA_VERSION,),
                )
    finally:
        conn.close()


def checkpoint(path: Path | None = None) -> None:
    """Run ``PRAGMA wal_checkpoint(TRUNCATE)``.

    Called from the app lifespan ``shutdown`` hook (architect ADR R-3) so the
    WAL sidecar is flushed and truncated before the process exits, leaving a
    clean ``admin.db`` file for backup or restart.

    Args:
        path: Override database file location for tests.
    """
    conn = connect(path=path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
