"""AnalysisResult repository over SQLite (T024).

Stores artifact paths + summary counts for completed jobs. Real artifacts
live under ``projects/{job_id}/`` and are referenced by relative path; the
repo never stores absolute paths (traversal protection at the route layer
adds the second guard).

``priority_summary`` is persisted as JSON text and roundtrips back to a typed
:class:`PrioritySummary` model (T020).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from tube_scout.web.repo import db


@dataclass(frozen=True)
class ResultRow:
    """In-memory view of an ``analysis_results`` row."""

    job_id: str
    report_v1v3_html: str | None
    report_v1v3_pdf: str | None
    report_v1v3_excel: str | None
    report_reuse_html: str | None
    report_reuse_excel: str | None
    matched_video_count: int
    suspicious_pair_count: int
    priority_summary: dict[str, int]
    generated_at: str

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> "ResultRow":
        return cls(
            job_id=row["job_id"],
            report_v1v3_html=row["report_v1v3_html"],
            report_v1v3_pdf=row["report_v1v3_pdf"],
            report_v1v3_excel=row["report_v1v3_excel"],
            report_reuse_html=row["report_reuse_html"],
            report_reuse_excel=row["report_reuse_excel"],
            matched_video_count=row["matched_video_count"],
            suspicious_pair_count=row["suspicious_pair_count"],
            priority_summary=json.loads(row["priority_summary"]),
            generated_at=row["generated_at"],
        )


_INSERT_SQL = """
INSERT INTO analysis_results (
    job_id,
    report_v1v3_html, report_v1v3_pdf, report_v1v3_excel,
    report_reuse_html, report_reuse_excel,
    matched_video_count, suspicious_pair_count,
    priority_summary, generated_at
) VALUES (
    :job_id,
    :report_v1v3_html, :report_v1v3_pdf, :report_v1v3_excel,
    :report_reuse_html, :report_reuse_excel,
    :matched_video_count, :suspicious_pair_count,
    :priority_summary, :generated_at
)
"""


class ResultsRepo:
    """Repository for the ``analysis_results`` SQLite table."""

    def __init__(self, conn_factory: Any | None = None) -> None:
        """Initialize the repository.

        Args:
            conn_factory: Callable returning a :class:`sqlite3.Connection`.
                Defaults to :func:`db.connect`.
        """
        self._connect = conn_factory or db.connect

    def insert_result(self, payload: dict[str, Any]) -> None:
        """Persist a result row.

        Args:
            payload: Dict containing the AnalysisResult fields. ``priority_summary``
                may be passed as a dict — it is serialized to JSON text.

        Raises:
            sqlite3.IntegrityError: When CHECK or FK constraints fail
                (orphan job_id, negative counts).
            ValueError: When ``payload.job_id`` is missing.
        """
        if not payload.get("job_id"):
            raise ValueError("payload.job_id is required")
        bound = dict(payload)
        if isinstance(bound.get("priority_summary"), dict):
            bound["priority_summary"] = json.dumps(
                bound["priority_summary"], ensure_ascii=False
            )
        conn = self._connect()
        try:
            with conn:
                conn.execute(_INSERT_SQL, bound)
        finally:
            conn.close()

    def get_result(self, job_id: str) -> ResultRow | None:
        """Return the result row for ``job_id`` or None when absent."""
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM analysis_results WHERE job_id = ?", (job_id,)
            ).fetchone()
            return ResultRow.from_sqlite(row) if row is not None else None
        finally:
            conn.close()
