"""OperatorAction repository over SQLite (T026).

Append-only audit log for operator CLI actions (add-department, oauth-consent,
token-refresh, status-check, verify). Read access is restricted to the
``admin status`` command and the ``GET /history`` operator-side filter.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from tube_scout.web.repo import db


@dataclass(frozen=True)
class OperatorActionRow:
    """In-memory view of an ``operator_actions`` row."""

    id: int
    action: str
    target_alias: str | None
    actor: str
    at: str
    result: str
    detail: str | None

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> OperatorActionRow:
        return cls(
            id=row["id"],
            action=row["action"],
            target_alias=row["target_alias"],
            actor=row["actor"],
            at=row["at"],
            result=row["result"],
            detail=row["detail"],
        )


class OperatorActionsRepo:
    """Repository for the ``operator_actions`` SQLite table (append-only)."""

    def __init__(self, conn_factory: Any | None = None) -> None:
        """Initialize the repository.

        Args:
            conn_factory: Callable returning a :class:`sqlite3.Connection`.
                Defaults to :func:`db.connect`.
        """
        self._connect = conn_factory or db.connect

    def record_action(
        self,
        *,
        action: str,
        target_alias: str | None,
        actor: str,
        result: str,
        detail: str | None,
    ) -> int:
        """Insert a new audit row.

        Args:
            action: One of ``add_department``, ``oauth_consent``,
                ``token_refresh``, ``status_check``, ``verify``.
            target_alias: Department alias if the action is scoped, else None.
            actor: Operator identifier (system user or env-derived name).
            result: ``success`` or ``failure``.
            detail: Optional English log detail (UI never reads this).

        Returns:
            The autoincremented ``id`` of the inserted row.

        Raises:
            ValueError: If ``actor`` is empty.
            sqlite3.IntegrityError: When action/result enum CHECK fails.
        """
        if not actor:
            raise ValueError("actor must be a non-empty string")
        now_iso = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO operator_actions
                        (action, target_alias, actor, at, result, detail)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (action, target_alias, actor, now_iso, result, detail),
                )
                return int(cursor.lastrowid or 0)
        finally:
            conn.close()

    def list_recent(self, *, limit: int = 50) -> list[OperatorActionRow]:
        """Return the most recent rows ordered by ``at`` DESC."""
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM operator_actions ORDER BY at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [OperatorActionRow.from_sqlite(r) for r in rows]
        finally:
            conn.close()
