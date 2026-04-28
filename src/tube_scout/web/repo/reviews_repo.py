"""ReviewStatus repository over SQLite (T025).

Owns ``reuse_review_status``: per-pair review state for spec-007 reuse
detection (confirmed_duplicate / false_positive / unreviewed). The repo
exposes UPSERT semantics so the operator can flip a pair's verdict
idempotently from the result-page form.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from tube_scout.web.repo import db


@dataclass(frozen=True)
class ReviewRow:
    """In-memory view of a ``reuse_review_status`` row."""

    pair_id: str
    job_id: str
    status: str
    updated_at: str | None
    updated_by: str | None
    note: str | None

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> "ReviewRow":
        return cls(
            pair_id=row["pair_id"],
            job_id=row["job_id"],
            status=row["status"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            note=row["note"],
        )


_UPSERT_SQL = """
INSERT INTO reuse_review_status (
    pair_id, job_id, status, updated_at, updated_by, note
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(pair_id) DO UPDATE SET
    job_id = excluded.job_id,
    status = excluded.status,
    updated_at = excluded.updated_at,
    updated_by = excluded.updated_by,
    note = excluded.note
"""


class ReviewsRepo:
    """Repository for the ``reuse_review_status`` SQLite table."""

    def __init__(self, conn_factory: Any | None = None) -> None:
        """Initialize the repository.

        Args:
            conn_factory: Callable returning a :class:`sqlite3.Connection`.
                Defaults to :func:`db.connect`.
        """
        self._connect = conn_factory or db.connect

    def upsert_review(
        self,
        *,
        pair_id: str,
        job_id: str,
        status: str,
        updated_by: str | None,
        note: str | None,
    ) -> None:
        """Insert-or-update a review row for ``pair_id``.

        Args:
            pair_id: Spec-007 pair identifier.
            job_id: Job that originally surfaced the pair.
            status: ``unreviewed`` | ``confirmed_duplicate`` | ``false_positive``.
            updated_by: Operator identifier (single-user but logged for audit).
            note: Optional free-text up to 512 chars.

        Raises:
            ValueError: If ``pair_id`` or ``job_id`` is empty.
            sqlite3.IntegrityError: When status enum CHECK fails, note length
                CHECK fails, or FK to analysis_jobs is broken.
        """
        if not pair_id:
            raise ValueError("pair_id must be a non-empty string")
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        now_iso = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    _UPSERT_SQL,
                    (pair_id, job_id, status, now_iso, updated_by, note),
                )
        finally:
            conn.close()

    def find_by_pair(self, pair_id: str) -> ReviewRow | None:
        """Return the review row for ``pair_id`` or None."""
        if not pair_id:
            raise ValueError("pair_id must be a non-empty string")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM reuse_review_status WHERE pair_id = ?",
                (pair_id,),
            ).fetchone()
            return ReviewRow.from_sqlite(row) if row is not None else None
        finally:
            conn.close()

    def list_for_job(self, job_id: str) -> list[ReviewRow]:
        """Return all review rows tied to ``job_id``."""
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM reuse_review_status WHERE job_id = ? "
                "ORDER BY pair_id",
                (job_id,),
            ).fetchall()
            return [ReviewRow.from_sqlite(r) for r in rows]
        finally:
            conn.close()

    def list_resolved_pair_ids(self) -> list[str]:
        """Return ``pair_id`` of pairs already marked confirmed/false_positive.

        Used by the reuse-detection pipeline stage to filter out previously
        resolved pairs from new alerts (spec FR-020).
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT pair_id FROM reuse_review_status "
                "WHERE status IN ('confirmed_duplicate', 'false_positive')"
            ).fetchall()
            return [r["pair_id"] for r in rows]
        finally:
            conn.close()
