"""Retry manifest persistence for failed transcript/fingerprint stages (spec 017 US3).

FR-015, FR-018, SC-008: load, save, and mutate retry_pending.json per channel alias.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from tube_scout.models.content import (
    FailureEntry,
    RetryManifestDelta,
    RetryManifestEntry,
)


class RetryManifest:
    """In-memory representation of retry_pending.json.

    Attributes:
        schema_version: Integer schema version (currently 1).
        alias: Department alias this manifest belongs to.
        updated_at: Last update timestamp (timezone-aware).
        entries: List of pending retry entries.
    """

    def __init__(
        self,
        schema_version: int,
        alias: str,
        updated_at: datetime,
        entries: list[RetryManifestEntry],
    ) -> None:
        self.schema_version = schema_version
        self.alias = alias
        self.updated_at = updated_at
        self.entries = entries

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "schema_version": self.schema_version,
            "alias": self.alias,
            "updated_at": self.updated_at.isoformat(),
            "entries": [
                {
                    "video_id": e.video_id,
                    "title": e.title,
                    "failed_stage": e.failed_stage,
                    "failure_reason": e.failure_reason,
                    "last_attempt_at": e.last_attempt_at.isoformat(),
                    "attempt_count": e.attempt_count,
                }
                for e in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> RetryManifest:
        """Deserialize from JSON-compatible dict.

        Args:
            data: Parsed JSON dict.

        Returns:
            RetryManifest instance.

        Raises:
            ValueError: schema_version is unknown.
        """
        if data.get("schema_version") != 1:
            raise ValueError(
                "Unknown retry manifest schema_version: "
                f"{data.get('schema_version')!r}. Expected 1."
            )
        entries = [
            RetryManifestEntry(
                video_id=e["video_id"],
                title=e["title"],
                failed_stage=e["failed_stage"],
                failure_reason=e["failure_reason"],
                last_attempt_at=datetime.fromisoformat(e["last_attempt_at"]),
                attempt_count=e["attempt_count"],
            )
            for e in data.get("entries", [])
        ]
        return cls(
            schema_version=data["schema_version"],
            alias=data.get("alias", ""),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            entries=entries,
        )


def load_manifest(
    manifest_path: Path,
    expected_alias: str | None = None,
) -> RetryManifest:
    """Load retry_pending.json; return empty manifest if file does not exist.

    Args:
        manifest_path: Path to retry_pending.json.
        expected_alias: If provided, raises ValueError when manifest alias differs.

    Returns:
        RetryManifest instance.

    Raises:
        ValueError: File exists but schema_version mismatches or alias mismatches.
    """
    if not manifest_path.exists():
        return RetryManifest(
            schema_version=1,
            alias=expected_alias or "",
            updated_at=datetime.now(tz=UTC),
            entries=[],
        )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"retry_pending.json at {manifest_path} is corrupt (invalid JSON): {exc}"
        ) from exc
    manifest = RetryManifest.from_dict(data)
    if expected_alias is not None and manifest.alias != expected_alias:
        raise ValueError(
            f"retry_pending.json alias mismatch: file has {manifest.alias!r}, "
            f"expected {expected_alias!r}."
        )
    return manifest


def save_manifest(manifest_path: Path, manifest: RetryManifest) -> None:
    """Atomically write retry_pending.json (tmp + fsync + rename, 0o600).

    Args:
        manifest_path: Destination path.
        manifest: RetryManifest to serialize.
    """
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2)
    fd, tmp_str = tempfile.mkstemp(
        dir=manifest_path.parent, prefix=manifest_path.name + ".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_str, 0o600)
        os.replace(tmp_str, manifest_path)
    except Exception:
        try:
            os.unlink(tmp_str)
        except OSError:
            pass
        raise


def add_or_update_failures(
    manifest: RetryManifest,
    failures: list[FailureEntry],
    *,
    now: datetime,
) -> RetryManifestDelta:
    """Add new failures to manifest or increment attempt_count for existing entries.

    For each failure:
    - If entry with same video_id exists, increment attempt_count and update
      last_attempt_at, failed_stage, failure_reason.
    - If entry absent, append new entry with attempt_count=1.

    Args:
        manifest: Current retry manifest (mutated in-place).
        failures: List of FailureEntry from transcript/fingerprint stages.
        now: Timestamp to record as last_attempt_at.

    Returns:
        RetryManifestDelta describing the change.
    """
    existing = {e.video_id: e for e in manifest.entries}
    added = 0

    for failure in failures:
        if failure.video_id in existing:
            entry = existing[failure.video_id]
            entry = RetryManifestEntry(
                video_id=entry.video_id,
                title=entry.title,
                failed_stage=failure.failed_stage,
                failure_reason=failure.failure_reason,
                last_attempt_at=now,
                attempt_count=entry.attempt_count + 1,
            )
            existing[failure.video_id] = entry
        else:
            entry = RetryManifestEntry(
                video_id=failure.video_id,
                title=failure.title,
                failed_stage=failure.failed_stage,
                failure_reason=failure.failure_reason,
                last_attempt_at=now,
                attempt_count=1,
            )
            existing[failure.video_id] = entry
            added += 1

    manifest.entries = list(existing.values())
    manifest.updated_at = now

    return RetryManifestDelta(
        added_count=added,
        resolved_count=0,
        remaining_count=len(manifest.entries),
        manifest_path=Path("."),
    )


def resolve_successes(
    manifest: RetryManifest,
    succeeded_video_ids: set[str],
) -> RetryManifestDelta:
    """Remove successfully processed videos from the manifest.

    Args:
        manifest: Current retry manifest (mutated in-place).
        succeeded_video_ids: Video IDs that succeeded this run.

    Returns:
        RetryManifestDelta describing the change.
    """
    before = len(manifest.entries)
    manifest.entries = [
        e for e in manifest.entries if e.video_id not in succeeded_video_ids
    ]
    resolved = before - len(manifest.entries)

    return RetryManifestDelta(
        added_count=0,
        resolved_count=resolved,
        remaining_count=len(manifest.entries),
        manifest_path=Path("."),  # caller replaces via save_manifest
    )


def select_retry_targets(
    manifest: RetryManifest,
    *,
    max_attempts: int = 5,
) -> list[str]:
    """Return video_ids eligible for automated retry.

    Excludes entries where attempt_count >= max_attempts (operator must intervene).

    Args:
        manifest: Current retry manifest.
        max_attempts: Entries at or above this count are excluded.

    Returns:
        List of video_id strings eligible for retry.
    """
    return [e.video_id for e in manifest.entries if e.attempt_count < max_attempts]
