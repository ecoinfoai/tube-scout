"""AnalysisJob repository over SQLite (T023).

Owns the ``analysis_jobs`` table: insert pending jobs, transition through the
state machine (pending → running → {completed | failed | interrupted}),
update progress counters, and query history.

Constitution II (Fail-Fast):
- Stage transitions are guarded by ``STAGE_ORDER`` so the runner cannot
  silently regress (raises :class:`StageRegressionError`).
- Empty inputs to public methods raise ``ValueError`` at the entry point.

Concurrency note: SQLite WAL handles single-writer multi-reader fine. The
runner serializes writes per job by holding a per-department flock (T034)
and only this repo writes to ``analysis_jobs``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from tube_scout.web.models import STAGE_ORDER
from tube_scout.web.repo import db


class StageRegressionError(ValueError):
    """Raised when a transition would move ``current_stage`` backwards."""


@dataclass(frozen=True)
class JobRow:
    """In-memory view of an ``analysis_jobs`` row."""

    job_id: str
    department_alias: str
    professor_name: str
    course_name: str
    period_start: str
    period_end: str
    status: str
    current_stage: str | None
    processed_count: int
    total_count: int
    result_dir: str | None
    started_at: str
    completed_at: str | None
    error_code: str | None
    error_detail: str | None
    created_by: str

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> JobRow:
        return cls(
            job_id=row["job_id"],
            department_alias=row["department_alias"],
            professor_name=row["professor_name"],
            course_name=row["course_name"],
            period_start=str(row["period_start"]),
            period_end=str(row["period_end"]),
            status=row["status"],
            current_stage=row["current_stage"],
            processed_count=row["processed_count"],
            total_count=row["total_count"],
            result_dir=row["result_dir"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            created_by=row["created_by"],
        )


_INSERT_SQL = """
INSERT INTO analysis_jobs (
    job_id, department_alias, professor_name, course_name,
    period_start, period_end, status, current_stage,
    processed_count, total_count, result_dir,
    started_at, completed_at, error_code, error_detail, created_by
) VALUES (
    :job_id, :department_alias, :professor_name, :course_name,
    :period_start, :period_end, 'pending', NULL,
    0, 0, NULL,
    :started_at, NULL, NULL, NULL, :created_by
)
"""


class JobsRepo:
    """Repository for the ``analysis_jobs`` SQLite table."""

    def __init__(self, conn_factory: Any | None = None) -> None:
        """Initialize the repository.

        Args:
            conn_factory: Callable returning a :class:`sqlite3.Connection`.
                Defaults to :func:`db.connect`.
        """
        self._connect = conn_factory or db.connect

    def insert_pending(self, payload: dict[str, Any]) -> None:
        """Insert a new job in ``pending`` state.

        Args:
            payload: Dict with the form-validated job fields plus ``started_at``
                and ``created_by``.

        Raises:
            sqlite3.IntegrityError: When CHECK constraints fail (period
                inversion, processed > total, etc.).
        """
        if not payload.get("job_id"):
            raise ValueError("payload.job_id is required")
        conn = self._connect()
        try:
            with conn:
                conn.execute(_INSERT_SQL, payload)
        finally:
            conn.close()

    def find_by_id(self, job_id: str) -> JobRow | None:
        """Return the job with ``job_id`` or None."""
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM analysis_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return JobRow.from_sqlite(row) if row is not None else None
        finally:
            conn.close()

    def transition_to(
        self,
        job_id: str,
        *,
        status: str,
        current_stage: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        """Transition a job to a new ``status`` (and optionally ``current_stage``).

        Enforces:
        - SQLite CHECK on the status enum (unknown → IntegrityError).
        - Monotonic stage transitions via :class:`STAGE_ORDER` lookup
          (regression → :class:`StageRegressionError`).

        Args:
            job_id: Existing job identifier.
            status: New status value (validated by SQLite CHECK).
            current_stage: New stage value, must not regress.
            error_code: Optional internal error code (recorded for failed jobs).
            error_detail: Optional English log detail (UI never reads it).
            completed_at: ISO-8601 string for completion timestamp.

        Raises:
            ValueError: If ``job_id`` is empty.
            StageRegressionError: If ``current_stage`` would move backwards.
            sqlite3.IntegrityError: If ``status`` violates the CHECK enum.
        """
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        if current_stage is not None:
            existing = self.find_by_id(job_id)
            if existing is not None and existing.current_stage is not None:
                old_idx = STAGE_ORDER.get(existing.current_stage, 0)
                new_idx = STAGE_ORDER.get(current_stage, 0)
                if new_idx < old_idx:
                    raise StageRegressionError(
                        f"stage regression: {existing.current_stage} → "
                        f"{current_stage} (job_id={job_id})"
                    )
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE analysis_jobs SET
                        status = ?,
                        current_stage = COALESCE(?, current_stage),
                        error_code = COALESCE(?, error_code),
                        error_detail = COALESCE(?, error_detail),
                        completed_at = COALESCE(?, completed_at)
                    WHERE job_id = ?
                    """,
                    (
                        status,
                        current_stage,
                        error_code,
                        error_detail,
                        completed_at,
                        job_id,
                    ),
                )
        finally:
            conn.close()

    def update_progress(
        self,
        job_id: str,
        *,
        processed_count: int,
        total_count: int,
    ) -> None:
        """Update the progress counters for a job.

        Args:
            job_id: Existing job identifier.
            processed_count: Cumulative processed-item count for the stage.
            total_count: Total items in the stage.

        Raises:
            ValueError: If ``job_id`` empty or counts negative.
            sqlite3.IntegrityError: When CHECK ``total_count >= processed_count``
                fails.
        """
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        if processed_count < 0 or total_count < 0:
            raise ValueError("counts must be non-negative")
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE analysis_jobs SET processed_count = ?, "
                    "total_count = ? WHERE job_id = ?",
                    (processed_count, total_count, job_id),
                )
        finally:
            conn.close()

    def find_in_progress_for_department(self, alias: str) -> list[JobRow]:
        """Return jobs in ``pending`` or ``running`` for the given department."""
        if not alias:
            raise ValueError("alias must be a non-empty string")
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM analysis_jobs
                WHERE department_alias = ?
                  AND status IN ('pending', 'running')
                """,
                (alias,),
            ).fetchall()
            return [JobRow.from_sqlite(r) for r in rows]
        finally:
            conn.close()

    def list_history(
        self,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobRow]:
        """Return jobs ordered by ``started_at`` DESC, optionally filtered.

        Args:
            filters: Optional dict supporting ``status`` (list[str]) and
                ``department`` (str) keys.
            limit: Maximum rows to return (1..200).
            offset: Pagination offset.

        Returns:
            List of :class:`JobRow`.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        sql = "SELECT * FROM analysis_jobs"
        params: list[Any] = []
        clauses: list[str] = []
        if filters:
            statuses = filters.get("status")
            if statuses:
                placeholders = ",".join(["?"] * len(statuses))
                clauses.append(f"status IN ({placeholders})")
                params.extend(statuses)
            dept = filters.get("department")
            if dept:
                clauses.append("department_alias = ?")
                params.append(dept)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [JobRow.from_sqlite(r) for r in rows]
        finally:
            conn.close()

    def list_running_at_shutdown(self) -> Iterable[str]:
        """Return ``job_id`` of all jobs in ``pending`` or ``running``.

        Used by the lifespan shutdown hook (R-1) to mark them as
        ``interrupted`` before exit.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT job_id FROM analysis_jobs "
                "WHERE status IN ('pending', 'running')"
            ).fetchall()
            return [r["job_id"] for r in rows]
        finally:
            conn.close()


def utc_now_iso() -> str:
    """Return the current UTC time in ISO-8601 format with offset."""
    return datetime.now(UTC).isoformat()
