"""Retry manifest persistence for failed transcript/fingerprint stages (spec 017 US3).

FR-015, FR-018, SC-008: load, save, and mutate retry_pending.json per channel alias.
Schema version 2: 3-tuple PK (video_id, mp4_filename, failed_stage).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from tube_scout.models.content import (
    FailureEntry,
    RetryManifestDelta,
    RetryManifestEntry,
)

_logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2


class RetryManifest:
    """In-memory representation of retry_pending.json.

    Attributes:
        schema_version: Integer schema version (2).
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
                    "mp4_filename": e.mp4_filename,
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

        Schema v1 entries are migrated to v2 by mapping:
          (video_id, None, "asr"|"fingerprint"|"audio_decode").

        Args:
            data: Parsed JSON dict.

        Returns:
            RetryManifest instance.

        Raises:
            ValueError: schema_version is unknown (not 1 or 2).
        """
        version = data.get("schema_version")
        if version not in (1, 2):
            raise ValueError(
                f"Unknown retry manifest schema_version: {version!r}. Expected 1 or 2."
            )

        raw_entries = data.get("entries", [])
        entries: list[RetryManifestEntry] = []

        for e in raw_entries:
            if version == 1:
                # v1: only video_id + failed_stage in {"transcript","fingerprint"}
                stage_v1 = e.get("failed_stage", "asr")
                # map legacy names to v2 enum
                stage_map = {"transcript": "asr", "fingerprint": "fingerprint"}
                failed_stage = stage_map.get(stage_v1, "asr")
                entries.append(
                    RetryManifestEntry(
                        video_id=e["video_id"],
                        mp4_filename=None,
                        title=e.get("title", ""),
                        failed_stage=failed_stage,  # type: ignore[arg-type]
                        failure_reason=e.get("failure_reason", ""),
                        last_attempt_at=datetime.fromisoformat(e["last_attempt_at"]),
                        attempt_count=e.get("attempt_count", 1),
                    )
                )
            else:
                entries.append(
                    RetryManifestEntry(
                        video_id=e.get("video_id"),
                        mp4_filename=e.get("mp4_filename"),
                        title=e.get("title", ""),
                        failed_stage=e["failed_stage"],
                        failure_reason=e.get("failure_reason", ""),
                        last_attempt_at=datetime.fromisoformat(e["last_attempt_at"]),
                        attempt_count=e.get("attempt_count", 1),
                    )
                )

        return cls(
            schema_version=_SCHEMA_VERSION,
            alias=data.get("alias", ""),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            entries=entries,
        )


def _pk(entry: RetryManifestEntry) -> tuple[str | None, str | None, str]:
    return (entry.video_id, entry.mp4_filename, entry.failed_stage)


def load_manifest(
    manifest_path: Path,
    expected_alias: str | None = None,
) -> RetryManifest:
    """Load retry_pending.json; return empty manifest if file does not exist.

    If a .recovery.json file exists alongside the manifest, merges its entries
    into the loaded manifest and removes the recovery file.

    Args:
        manifest_path: Path to retry_pending.json.
        expected_alias: If provided, raises ValueError when manifest alias differs.

    Returns:
        RetryManifest instance.

    Raises:
        ValueError: File exists but schema_version mismatches or alias mismatches.
    """
    recovery_path = manifest_path.with_suffix(".recovery.json")

    if not manifest_path.exists():
        base = RetryManifest(
            schema_version=_SCHEMA_VERSION,
            alias=expected_alias or "",
            updated_at=datetime.now(tz=UTC),
            entries=[],
        )
    else:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"retry_pending.json at {manifest_path} is corrupt "
                f"(invalid JSON): {exc}"
            ) from exc
        base = RetryManifest.from_dict(data)

        if expected_alias is not None and base.alias != expected_alias:
            if base.alias == "":
                base = RetryManifest(
                    schema_version=base.schema_version,
                    alias=expected_alias,
                    updated_at=base.updated_at,
                    entries=base.entries,
                )
            else:
                raise ValueError(
                    f"retry_pending.json alias mismatch: file has {base.alias!r}, "
                    f"expected {expected_alias!r}."
                )

    # Merge recovery entries if present
    if recovery_path.exists():
        try:
            rec_data = json.loads(recovery_path.read_text(encoding="utf-8"))
            rec_manifest = RetryManifest.from_dict(rec_data)
            existing_pks = {_pk(e) for e in base.entries}
            for e in rec_manifest.entries:
                if _pk(e) not in existing_pks:
                    base.entries.append(e)
            recovery_path.unlink(missing_ok=True)
            _logger.warning(
                "Merged %d entries from recovery file %s",
                len(rec_manifest.entries),
                recovery_path,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Could not merge recovery file %s: %s", recovery_path, exc)

    return base


def save_manifest(manifest_path: Path, manifest: RetryManifest) -> None:
    """Atomically write retry_pending.json (flock + tmp + fsync + rename, 0o600).

    On OSError, saves in-memory state to <manifest_path>.recovery.json
    as a fallback, then re-raises.

    Args:
        manifest_path: Destination path.
        manifest: RetryManifest to serialize.

    Raises:
        OSError: Write failed (recovery.json written as fallback).
    """
    import fcntl

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.schema_version = _SCHEMA_VERSION
    data = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2)

    lock_path = manifest_path.with_suffix(".lock")
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
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
            _write_recovery(manifest_path, data)
            raise
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def _write_recovery(manifest_path: Path, data: str) -> None:
    """Write serialized manifest to .recovery.json as OSError fallback."""
    recovery_path = manifest_path.with_suffix(".recovery.json")
    try:
        recovery_path.write_text(data, encoding="utf-8")
        _logger.warning("save_manifest failed; recovery written to %s", recovery_path)
    except OSError as exc2:
        _logger.error("Recovery write also failed: %s", exc2)


def add_or_update_failures(
    manifest: RetryManifest,
    failures: list[FailureEntry],
    *,
    now: datetime,
) -> RetryManifestDelta:
    """Add new failures or increment attempt_count for existing 3-tuple PK entries.

    PK = (video_id, mp4_filename, failed_stage). Each stage tracked independently.

    Args:
        manifest: Current retry manifest (mutated in-place).
        failures: List of FailureEntry from transcript/fingerprint stages.
        now: Timestamp to record as last_attempt_at.

    Returns:
        RetryManifestDelta describing the change.
    """
    existing: dict[tuple[str | None, str | None, str], RetryManifestEntry] = {
        _pk(e): e for e in manifest.entries
    }
    added = 0

    for failure in failures:
        mp4_filename = getattr(failure, "mp4_filename", None)
        # Map legacy failed_stage names to v2 enum
        stage_v2_map = {"transcript": "asr", "fingerprint": "fingerprint"}
        stage = stage_v2_map.get(failure.failed_stage, failure.failed_stage)

        pk = (failure.video_id if failure.video_id else None, mp4_filename, stage)

        if pk in existing:
            old = existing[pk]
            existing[pk] = RetryManifestEntry(
                video_id=old.video_id,
                mp4_filename=old.mp4_filename,
                title=old.title,
                failed_stage=old.failed_stage,
                failure_reason=failure.failure_reason,
                last_attempt_at=now,
                attempt_count=old.attempt_count + 1,
            )
        else:
            existing[pk] = RetryManifestEntry(
                video_id=failure.video_id if failure.video_id else None,
                mp4_filename=mp4_filename,
                title=failure.title,
                failed_stage=stage,  # type: ignore[arg-type]
                failure_reason=failure.failure_reason,
                last_attempt_at=now,
                attempt_count=1,
            )
            added += 1

    manifest.entries = list(existing.values())
    manifest.updated_at = now

    return RetryManifestDelta(
        added_count=added,
        resolved_count=0,
        remaining_count=len(manifest.entries),
        manifest_path=Path("."),
    )


def append_aborted_by_user(
    manifest_path: Path,
    *,
    channel_alias: str,
    video_id: str | None,
    mp4_filename: str | None,
    title: str,
    now: datetime,
) -> RetryManifestDelta:
    """Atomically append (or increment) an aborted_by_user entry.

    Loads ``manifest_path`` (creating an empty manifest if absent), upserts
    a RetryManifestEntry whose 3-tuple PK is
    ``(video_id, mp4_filename, "aborted_by_user")``, then saves. Designed
    for the SIGINT handler in unified_ingest (F-11 follow-up, 2026-05-17
    audit v3): without this call the in-flight video is never recorded in
    the retry queue and ``--resume`` silently drops it.

    At least one of ``video_id`` / ``mp4_filename`` must be non-None
    (enforced by RetryManifestEntry's PK validator).

    Args:
        manifest_path: Path to retry_pending.json (created if absent).
        channel_alias: Department alias persisted in the manifest header.
        video_id: YouTube video_id of the interrupted video, or None when
            ingest_mapping never produced one.
        mp4_filename: mp4 basename of the interrupted file, or None when
            the failure predates mp4 selection.
        title: Operator-facing video title.
        now: UTC timestamp recorded as last_attempt_at.

    Returns:
        RetryManifestDelta with added_count = 1 for new entries, 0 when an
        existing PK had its attempt_count incremented.

    Raises:
        OSError: Manifest write failed (a .recovery.json fallback is left
            behind by save_manifest).
    """
    manifest = load_manifest(manifest_path, expected_alias=channel_alias)

    pk = (video_id, mp4_filename, "aborted_by_user")
    existing_idx = next(
        (i for i, e in enumerate(manifest.entries) if _pk(e) == pk),
        None,
    )

    if existing_idx is None:
        manifest.entries.append(
            RetryManifestEntry(
                video_id=video_id,
                mp4_filename=mp4_filename,
                title=title,
                failed_stage="aborted_by_user",
                failure_reason="aborted_by_user",
                last_attempt_at=now,
                attempt_count=1,
            )
        )
        added = 1
    else:
        old = manifest.entries[existing_idx]
        manifest.entries[existing_idx] = RetryManifestEntry(
            video_id=old.video_id,
            mp4_filename=old.mp4_filename,
            title=old.title,
            failed_stage=old.failed_stage,
            failure_reason="aborted_by_user",
            last_attempt_at=now,
            attempt_count=old.attempt_count + 1,
        )
        added = 0

    manifest.updated_at = now
    save_manifest(manifest_path, manifest)

    return RetryManifestDelta(
        added_count=added,
        resolved_count=0,
        remaining_count=len(manifest.entries),
        manifest_path=manifest_path,
    )


def resolve_successes(
    manifest: RetryManifest,
    succeeded_video_ids: set[str],
    stage: str | None = None,
) -> RetryManifestDelta:
    """Remove successfully processed videos from the manifest.

    Args:
        manifest: Current retry manifest (mutated in-place).
        succeeded_video_ids: Video IDs that succeeded this run.
        stage: If provided, only remove entries matching this stage.

    Returns:
        RetryManifestDelta describing the change.
    """
    before = len(manifest.entries)

    def _keep(e: RetryManifestEntry) -> bool:
        if e.video_id not in succeeded_video_ids:
            return True
        if stage is not None and e.failed_stage != stage:
            return True
        return False

    manifest.entries = [e for e in manifest.entries if _keep(e)]
    resolved = before - len(manifest.entries)

    return RetryManifestDelta(
        added_count=0,
        resolved_count=resolved,
        remaining_count=len(manifest.entries),
        manifest_path=Path("."),
    )


def select_retry_targets(
    manifest: RetryManifest,
    *,
    max_attempts: int = 5,
    stage: str | None = None,
    overflow_path: Path | None = None,
) -> list[str | None]:
    """Return video_ids eligible for automated retry.

    Excludes entries where attempt_count >= max_attempts (operator must intervene).
    Each (video_id, mp4_filename, stage) triple is evaluated independently.
    Expired entries (attempt_count >= max_attempts) are written to overflow_path
    as a JSON manifest for operator review (ADV-54).

    Args:
        manifest: Current retry manifest.
        max_attempts: Entries at or above this count are excluded.
        stage: If provided, only return entries matching this stage.
        overflow_path: If provided, write expired entries here as JSON.

    Returns:
        List of video_id values (may include None for unmapped entries).
    """
    result = []
    expired: list[RetryManifestEntry] = []
    for e in manifest.entries:
        if e.attempt_count >= max_attempts:
            expired.append(e)
            continue
        if stage is not None and e.failed_stage != stage:
            continue
        result.append(e.video_id)

    if expired and overflow_path is not None:
        overflow_manifest = RetryManifest(
            schema_version=_SCHEMA_VERSION,
            alias=manifest.alias,
            updated_at=manifest.updated_at,
            entries=expired,
        )
        try:
            overflow_path.parent.mkdir(parents=True, exist_ok=True)
            overflow_path.write_text(
                json.dumps(overflow_manifest.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            _logger.warning(
                "Could not write overflow manifest to %s: %s", overflow_path, exc
            )

    return result
