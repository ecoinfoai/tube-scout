"""Professor pool resolver for spec 011 cross-channel content analysis.

Manages professor → (channel_alias, author_marker) mappings stored in
professor_pool and professor_pool_membership SQLite tables. Never directly
parses channels.json (boundary B-6); queries the DB for alias values.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tube_scout.models.reuse_v2 import CaptionPool, ProfessorMapping, VideoRef


def _now() -> str:
    return datetime.now(UTC).isoformat()


def map_professor(
    professor_id: str,
    display_name: str,
    channel_alias: str,
    author_marker: str,
    db_path: Path,
    registered_by: str,
    note: str | None = None,
) -> ProfessorMapping:
    """Register or extend a professor pool mapping.

    Inserts into professor_pool (idempotent via OR IGNORE) and
    professor_pool_membership. Idempotent for exact duplicates.

    Args:
        professor_id: Unique professor identifier (e.g. 'prof-park-jc').
        display_name: Human-readable name shown in reports.
        channel_alias: spec 003 channel alias to associate.
        author_marker: Author field from video metadata or '__channel_owner__'.
        db_path: Path to the content_reuse.db SQLite file.
        registered_by: Admin identifier performing the registration.
        note: Optional free-text notes stored in professor_pool.

    Returns:
        ProfessorMapping describing the registered mapping.

    Raises:
        TypeError: If db_path is not a Path.
        ValueError: If (channel_alias, '__channel_owner__') is already mapped
            to a different professor_id (one channel = one professor rule).
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    now = _now()
    conn = sqlite3.connect(str(db_path))
    try:
        # Check __channel_owner__ collision before any insert
        if author_marker == "__channel_owner__":
            row = conn.execute(
                "SELECT professor_id FROM professor_pool_membership "
                "WHERE channel_alias = ? AND author_marker = '__channel_owner__'",
                (channel_alias,),
            ).fetchone()
            if row and row[0] != professor_id:
                raise ValueError(
                    f"Channel '{channel_alias}' is already owned by '{row[0]}'; "
                    f"one channel = one professor under __channel_owner__ rule. "
                    f"Unmap the existing owner first with "
                    f"'tube-scout content professor unmap --alias {channel_alias}'."
                )

        conn.execute(
            "INSERT OR IGNORE INTO professor_pool "
            "(professor_id, display_name, created_at, created_by, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (professor_id, display_name, now, registered_by, note),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool_membership "
            "(professor_id, channel_alias, author_marker, registered_at, "
            "registered_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (professor_id, channel_alias, author_marker, now, registered_by),
        )
        conn.commit()
    finally:
        conn.close()

    return ProfessorMapping(
        professor_id=professor_id,
        display_name=display_name,
        channel_alias=channel_alias,
        author_marker=author_marker,
        registered_at=datetime.fromisoformat(now),
        registered_by=registered_by,
        notes=note,
    )


def unmap_professor(
    professor_id: str,
    channel_alias: str,
    author_marker: str,
    db_path: Path,
) -> bool:
    """Remove a single professor_pool_membership row.

    Args:
        professor_id: Professor identifier.
        channel_alias: Channel alias to remove.
        author_marker: Author marker of the membership row.
        db_path: Path to the SQLite database file.

    Returns:
        True if a row was removed, False if no matching row existed.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "DELETE FROM professor_pool_membership "
            "WHERE professor_id = ? AND channel_alias = ? AND author_marker = ?",
            (professor_id, channel_alias, author_marker),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_professors(db_path: Path) -> list[ProfessorMapping]:
    """List all registered professor mappings from the database.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        List of ProfessorMapping instances, one per membership row.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT m.professor_id, p.display_name, m.channel_alias,
                   m.author_marker, m.registered_at, m.registered_by, p.notes
            FROM professor_pool_membership m
            JOIN professor_pool p USING (professor_id)
            ORDER BY m.professor_id, m.channel_alias
            """
        ).fetchall()
    finally:
        conn.close()

    return [
        ProfessorMapping(
            professor_id=row["professor_id"],
            display_name=row["display_name"],
            channel_alias=row["channel_alias"],
            author_marker=row["author_marker"],
            registered_at=datetime.fromisoformat(row["registered_at"]),
            registered_by=row["registered_by"],
            notes=row["notes"],
        )
        for row in rows
    ]


def resolve_caption_pool(professor_id: str, db_path: Path) -> CaptionPool:
    """Collect all video references for a professor across registered channels.

    Queries professor_pool_membership for all (channel_alias, author_marker)
    rows, then joins with processing_status to enumerate video_ids. Never
    opens channels.json directly (boundary B-6); channel aliases are read
    from the DB only.

    Args:
        professor_id: Professor identifier to resolve.
        db_path: Path to the SQLite database file.

    Returns:
        CaptionPool containing all VideoRef entries for the professor.

    Raises:
        TypeError: If db_path is not a Path.
        ValueError: If professor_id has no registered memberships.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        memberships = conn.execute(
            "SELECT channel_alias, author_marker FROM professor_pool_membership "
            "WHERE professor_id = ?",
            (professor_id,),
        ).fetchall()

        if not memberships:
            raise ValueError(
                f"No professor mapping for '{professor_id}'. "
                f"Run 'tube-scout content professor map --professor-id {professor_id} "
                f"--alias <channel> --author <marker>' first."
            )

        video_refs: list[VideoRef] = []
        for m in memberships:
            alias = m["channel_alias"]
            marker = m["author_marker"]
            # Query video IDs for this channel from processing_status (boundary B-6:
            # channel alias is read from DB, not channels.json)
            vids = conn.execute(
                "SELECT video_id FROM processing_status WHERE channel_id = ?",
                (alias,),
            ).fetchall()
            for v in vids:
                video_refs.append(
                    VideoRef(
                        channel_alias=alias,
                        video_id=v["video_id"],
                        author_marker=marker,
                    )
                )
    finally:
        conn.close()

    return CaptionPool(professor_id=professor_id, video_refs=video_refs)
