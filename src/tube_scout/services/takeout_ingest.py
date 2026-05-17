"""Takeout ingestion service: CSV parsing, evidence mapping, DB persistence.

FR-001~FR-009: parse Takeout CSV metadata, assemble channel work dir,
run evidence-score mapping, persist to SQLite v4, write audit CSV.
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from tube_scout.models.config import ChannelRegistration
from tube_scout.models.content import ChannelMetadata, VideoMetadata
from tube_scout.services.audit_writer import AuditWriter
from tube_scout.services.evidence_score import decide_mapping

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FR-008 ignored categories
# ---------------------------------------------------------------------------

_IGNORED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^동영상 녹화"),
    re.compile(r"^동영상 텍스트"),
    re.compile(r"^댓글"),
    re.compile(r"^재생목록"),
    re.compile(r"^구독정보"),
    re.compile(r"^시청 기록"),
    re.compile(r"^검색 기록"),
]

_YT_SUBDIR = "YouTube 및 YouTube Music"
_META_SUBDIR = "동영상 메타데이터"
_CHANNEL_SUBDIR = "채널"
_VIDEO_SUBDIR = "동영상"

# Minimum required columns — real Takeout export (defect-4 fix: drop absent URL column)
_VIDEO_CSV_REQUIRED = {
    "동영상 ID",
    "동영상 제목(원본)",
    "근사치 길이(밀리초)",
    "채널 ID",
    "개인 정보 보호",
    "동영상 생성 타임스탬프",
}

# Real Takeout channel CSV required columns (defect-3 fix)
_CHANNEL_CSV_REQUIRED = {"채널 ID", "채널 제목(원본)"}

# R-4 / FR-005: Korean privacy labels from Takeout CSV → canonical English values
_PRIVACY_MAPPING: dict[str, Literal["public", "unlisted", "private"]] = {
    "공개": "public",
    "일부 공개": "unlisted",
    "비공개": "private",
}


# ---------------------------------------------------------------------------
# IngestResult
# ---------------------------------------------------------------------------


class IngestResult(BaseModel):
    """Summary result of a single ingest_takeout() call."""

    channel_id: str
    channel_alias: str
    total_videos: int
    new_videos: int
    high_confidence_mappings: int
    medium_confidence_mappings: int
    ambiguous_mappings: int
    unmapped_filenames: int
    ignored_csv_count: int
    dry_run: bool
    mp4_present_count: int = 0
    mp4_absent_count: int = 0
    elapsed_seconds: float = 0.0
    mp4_video_id_map: dict[str, str] = Field(default_factory=dict)
    # ADV-34/35: unmapped mp4 entries for retry_pending (ingest_mapping + ingest_no_mp4)
    unmapped_mp4_entries: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# internal: alias registry loader (injectable for tests)
# ---------------------------------------------------------------------------


def _load_alias_registry() -> dict[str, ChannelRegistration]:
    """Load channel alias registry from auth tokens directory.

    Returns:
        Dict mapping alias → ChannelRegistration.
    """
    from tube_scout.services.auth import load_registry

    return load_registry()


# ---------------------------------------------------------------------------
# parse_takeout_csv_metadata
# ---------------------------------------------------------------------------


def parse_takeout_csv_metadata(
    takeout_dir: Path,
) -> tuple[ChannelMetadata, list[VideoMetadata]]:
    """Parse Takeout export metadata CSVs.

    Args:
        takeout_dir: Takeout decompressed root. Supports two layouts:
            (a) archive root containing a ``Takeout/`` sub-directory, or
            (b) the ``Takeout/`` directory itself (contains
            ``YouTube 및 YouTube Music/`` directly).

    Returns:
        (channel_meta, video_meta_list) tuple, video_meta deduped by video_id.
        Unknown-privacy rows are silently dropped; use _parse_takeout_full()
        internally when audit emission is required.

    Raises:
        FileNotFoundError: Required CSVs not found under takeout_dir.
        ValueError: Required columns absent from CSV.
    """
    channel_meta, videos, _ = _parse_takeout_full(takeout_dir)
    return channel_meta, videos


def _parse_takeout_full(
    takeout_dir: Path,
) -> tuple[ChannelMetadata, list[VideoMetadata], list[dict]]:
    """Internal parser that also returns unknown-privacy rows for audit.

    Args:
        takeout_dir: Takeout decompressed root (archive root or Takeout/ itself).

    Returns:
        3-tuple of (channel_meta, video_list, pending_unknown_privacy_rows).
        The third element is a list of {"video_id": ..., "raw_value": ...} dicts
        for rows whose privacy label was not found in _PRIVACY_MAPPING.

    Raises:
        FileNotFoundError: Required directory or CSV not found.
        ValueError: Required CSV columns absent or CSV malformed.
    """
    # defect-12: auto-detect yt_dir — accept either an archive root or the Takeout/ dir
    candidate_a = takeout_dir / "Takeout" / _YT_SUBDIR
    candidate_b = takeout_dir / _YT_SUBDIR
    if candidate_a.exists():
        yt_dir = candidate_a
    elif candidate_b.exists():
        yt_dir = candidate_b
    else:
        raise FileNotFoundError(
            f"Neither '{takeout_dir}/Takeout/{_YT_SUBDIR}' "
            f"nor '{takeout_dir}/{_YT_SUBDIR}' exists"
        )

    meta_dir = yt_dir / _META_SUBDIR
    channel_dir = yt_dir / _CHANNEL_SUBDIR

    # Parse 채널.csv (Korean filename, matched verbatim)
    channel_csv_files = (
        list(channel_dir.glob("채널.csv")) if channel_dir.exists() else []
    )
    if not channel_csv_files:
        raise FileNotFoundError(f"채널.csv not found under {channel_dir}")
    channel_meta = _parse_channel_csv(channel_csv_files[0])

    # Parse all 동영상*.csv files (split CSV support) — defect-8 fix: exact glob union
    if not meta_dir.exists():
        raise FileNotFoundError(f"동영상 메타데이터 directory not found: {meta_dir}")

    video_csv_files = sorted(
        set(meta_dir.glob("동영상.csv")) | set(meta_dir.glob("동영상(*).csv"))
    )
    if not video_csv_files:
        raise FileNotFoundError(f"No 동영상*.csv files found under {meta_dir}")

    seen: dict[str, VideoMetadata] = {}
    pending_unknown_privacy_rows: list[dict] = []
    now = datetime.datetime.now(tz=datetime.UTC)

    for csv_path in video_csv_files:
        # defect-8: skip ignored-category files that happen to match the broader glob
        if _is_ignored(csv_path.name):
            continue
        with csv_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError(f"Empty or invalid CSV: {csv_path}")
            actual_cols = set(reader.fieldnames)
            missing = _VIDEO_CSV_REQUIRED - actual_cols
            if missing:
                raise ValueError(f"Missing required columns in {csv_path}: {missing}")
            for row in reader:
                video_id = row["동영상 ID"].strip()
                if not video_id or video_id in seen:
                    continue
                duration_ms_str = row["근사치 길이(밀리초)"].strip()
                duration_ms = float(duration_ms_str) if duration_ms_str else 0.0
                created_at_str = row["동영상 생성 타임스탬프"].strip()
                created_at = None
                if created_at_str:
                    try:
                        created_at = datetime.datetime.fromisoformat(
                            created_at_str.replace("Z", "+00:00")
                        )
                    except ValueError:
                        created_at = None

                # defect-7 / FR-005: Korean privacy → English via _PRIVACY_MAPPING
                raw_privacy = row["개인 정보 보호"].strip()
                privacy_status = _PRIVACY_MAPPING.get(raw_privacy)
                if privacy_status is None:
                    # Unknown privacy value — skip row, accumulate for audit
                    pending_unknown_privacy_rows.append({
                        "video_id": video_id,
                        "raw_value": raw_privacy,
                    })
                    continue

                vm = VideoMetadata(
                    video_id=video_id,
                    channel_id=channel_meta.channel_id,
                    title=row["동영상 제목(원본)"].strip(),
                    duration_seconds=duration_ms / 1000.0,
                    language=row.get("동영상 오디오 언어", "").strip() or None,
                    category=row.get("동영상 카테고리", "").strip() or None,
                    privacy_status=privacy_status,
                    created_at=created_at,
                    source="takeout",
                    ingested_at=now,
                )
                seen[video_id] = vm

    return channel_meta, list(seen.values()), pending_unknown_privacy_rows


def _parse_channel_csv(csv_path: Path) -> ChannelMetadata:
    """Parse the Korean 채널.csv file and return a minimal ChannelMetadata.

    Args:
        csv_path: Path to 채널.csv.

    Returns:
        ChannelMetadata with channel_id and title populated.

    Raises:
        ValueError: Required columns missing.
    """
    now = datetime.datetime.now(tz=datetime.UTC)
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Empty 채널.csv: {csv_path}")
        actual_cols = set(reader.fieldnames)
        missing = _CHANNEL_CSV_REQUIRED - actual_cols
        if missing:
            raise ValueError(f"Missing columns in 채널.csv: {missing}")
        for row in reader:
            return ChannelMetadata(
                channel_id=row["채널 ID"].strip(),
                channel_alias="__unknown__",
                title=row["채널 제목(원본)"].strip() or None,
                country=row.get("채널 국가", "").strip()[:2] or None,
                source="takeout",
                ingested_at=now,
            )
    raise ValueError(f"채널.csv has no data rows: {csv_path}")


# ---------------------------------------------------------------------------
# assemble_channel_work_dir
# ---------------------------------------------------------------------------


def assemble_channel_work_dir(
    takeout_dir: Path,
    channel_alias: str,
    work_root: Path,
    use_symlinks: bool = True,
) -> Path:
    """Assemble per-channel unified work dir with mp4 symlinks (or copies).

    Idempotency guarantee (FR-020): existing symlinks are detected via
    ``dest.exists() or dest.is_symlink()`` and skipped.  Only mp4 files
    absent from the work dir are added, so repeated calls with the same or
    overlapping archive parts never duplicate or overwrite links.

    Args:
        takeout_dir: Takeout root.
        channel_alias: spec 003 alias.
        work_root: data/ directory root.
        use_symlinks: True=symlink (POSIX), False=copy.

    Returns:
        Channel work_dir path (``work_root/<alias>/``).

    Raises:
        OSError: Symlink creation failed.
    """
    work_dir = work_root / channel_alias
    video_dir = work_dir / _VIDEO_SUBDIR
    video_dir.mkdir(parents=True, exist_ok=True)

    # Resolve yt_dir using the same auto-discovery logic
    candidate_a = takeout_dir / "Takeout" / _YT_SUBDIR
    candidate_b = takeout_dir / _YT_SUBDIR
    yt_dir = candidate_a if candidate_a.exists() else candidate_b

    src_video_dir = yt_dir / _VIDEO_SUBDIR
    if not src_video_dir.exists():
        return work_dir

    takeout_dir_resolved = takeout_dir.resolve()
    for mp4 in src_video_dir.glob("*.mp4"):
        dest = video_dir / mp4.name
        if dest.exists() or dest.is_symlink():
            continue
        if use_symlinks:
            target = mp4.resolve()
            try:
                target.relative_to(takeout_dir_resolved)
            except ValueError:
                raise ValueError(
                    f"mp4 path '{mp4}' resolves to '{target}', "
                    f"which is outside takeout_dir '{takeout_dir_resolved}'. "
                    "Refusing to ingest — possible symlink escape (T-04)."
                )
            dest.symlink_to(target)
        else:
            import shutil

            shutil.copy2(mp4, dest)

    return work_dir


# ---------------------------------------------------------------------------
# ingest_takeout
# ---------------------------------------------------------------------------


def ingest_takeout(
    takeout_dir: Path,
    channel_alias: str,
    db_path: Path,
    work_root: Path,
    *,
    use_symlinks: bool = True,
    dry_run: bool = False,
) -> IngestResult:
    """End-to-end Takeout ingestion (FR-001/FR-002/FR-009).

    Args:
        takeout_dir: Takeout root.
        channel_alias: Self-hosted alias (validated via spec 003 registry).
        db_path: content_reuse.db path (v3+ required; v4 migration auto).
        work_root: data/ root.
        use_symlinks: See assemble_channel_work_dir.
        dry_run: True → no DB writes, mapping results to stdout only.

    Returns:
        IngestResult — count summary.

    Raises:
        ValueError: alias not registered.
        FileNotFoundError: takeout_dir path error.
    """
    _t_start = time.monotonic()

    # SEC-4: resolve symlinks at entry to prevent symlink escape
    takeout_dir = takeout_dir.resolve()

    if not takeout_dir.exists():
        raise FileNotFoundError(f"takeout_dir not found: {takeout_dir}")

    _logger.info(
        "ingest_takeout: alias=%s takeout_dir=%s dry_run=%s",
        channel_alias,
        takeout_dir,
        dry_run,
    )

    # Step 1: Validate alias
    registry = _load_alias_registry()
    if channel_alias not in registry:
        raise ValueError(
            f"Channel alias '{channel_alias}' is not registered. "
            f"Available aliases: {sorted(registry)}"
        )

    # Resolve yt_dir
    candidate_a = takeout_dir / "Takeout" / _YT_SUBDIR
    candidate_b = takeout_dir / _YT_SUBDIR
    yt_dir = candidate_a if candidate_a.exists() else candidate_b

    ignored_csv_count = 0
    now_iso = datetime.datetime.now(tz=datetime.UTC).isoformat()

    audit_writer = AuditWriter(work_root / channel_alias)

    # Detect and audit ignored categories under yt_dir top-level (FR-008)
    if yt_dir.exists():
        for item in yt_dir.iterdir():
            if _is_ignored(item.name):
                ignored_csv_count += 1
                if not dry_run:
                    audit_writer.append_row(
                        "takeout_ingest",
                        {
                            "video_id": "n/a",
                            "result": "skip",
                            "reason": "ignored_by_policy",
                            "mp4_filename": item.name,
                            "match_confidence": "n/a",
                            "score": 0,
                            "timestamp": now_iso,
                            "raw_value": "",
                            "elapsed_ms": 0,
                        },
                    )

    # Detect and audit ignored category files inside meta_dir (defect-8, FR-011)
    meta_dir = yt_dir / _META_SUBDIR
    if meta_dir.exists():
        for item in meta_dir.iterdir():
            if _is_ignored(item.name):
                ignored_csv_count += 1
                if not dry_run:
                    audit_writer.append_row(
                        "takeout_ingest",
                        {
                            "video_id": "n/a",
                            "result": "skip",
                            "reason": "ignored_by_policy",
                            "mp4_filename": item.name,
                            "match_confidence": "n/a",
                            "score": 0,
                            "timestamp": now_iso,
                            "raw_value": "",
                            "elapsed_ms": 0,
                        },
                    )

    # Step 2: Parse metadata CSVs
    channel_meta, video_list, pending_unknown_privacy_rows = _parse_takeout_full(
        takeout_dir
    )

    # B-9: Validate channel_id consistency between registry and archive CSV
    reg_channel_id = registry[channel_alias].channel_id
    csv_channel_id = channel_meta.channel_id
    if not csv_channel_id:
        raise ValueError(
            f"Archive CSV channel_id is empty or missing for alias '{channel_alias}'. "
            "The Takeout archive may be corrupt or from a different account. "
            "Resolve before ingesting."
        )
    if reg_channel_id and csv_channel_id != reg_channel_id:
        _logger.warning(
            "channel_id mismatch for alias '%s': registry=%r, archive=%r",
            channel_alias,
            reg_channel_id,
            csv_channel_id,
        )
        raise ValueError(
            f"Channel ID mismatch for alias '{channel_alias}': "
            f"registry={reg_channel_id!r}, archive CSV={csv_channel_id!r}. "
            "Resolve the inconsistency before ingesting."
        )

    channel_meta = channel_meta.model_copy(update={"channel_alias": channel_alias})

    # Audit unknown privacy rows (defect-7, FR-005)
    if not dry_run:
        for entry in pending_unknown_privacy_rows:
            audit_writer.append_row(
                "takeout_ingest",
                {
                    "video_id": entry["video_id"],
                    "result": "skip",
                    "reason": "unknown_privacy_value",
                    "mp4_filename": "n/a",
                    "match_confidence": "n/a",
                    "score": 0,
                    "timestamp": now_iso,
                    "raw_value": entry["raw_value"],
                    "elapsed_ms": 0,
                },
            )

    # Step 3+4: Evidence score mapping for mp4 files
    src_video_dir = yt_dir / _VIDEO_SUBDIR
    high_count = medium_count = ambiguous_count = unmapped_count = 0
    mp4_video_id_map: dict[str, str | None] = {}
    unmapped_mp4_entries: list[dict] = []

    if src_video_dir.exists():
        for mp4 in sorted(src_video_dir.glob("*.mp4")):
            decision = decide_mapping(mp4, video_list)
            mp4_video_id_map[mp4.name] = decision.video_id
            if decision.confidence == "high":
                high_count += 1
            elif decision.confidence == "medium":
                medium_count += 1
            elif decision.confidence == "ambiguous":
                ambiguous_count += 1
            else:
                unmapped_count += 1
                # ADV-34: unmapped mp4 → retry_pending (ingest_mapping)
                unmapped_mp4_entries.append({
                    "video_id": None,
                    "mp4_filename": mp4.name,
                    "failed_stage": "ingest_mapping",
                    "failure_reason": f"no_match score={decision.score}",
                })
            if not dry_run:
                audit_writer.append_row(
                    "takeout_ingest",
                    {
                        "video_id": decision.video_id or "n/a",
                        "result": "success" if decision.video_id else "skip",
                        "reason": decision.confidence or "no_match",
                        "mp4_filename": mp4.name,
                        "match_confidence": decision.confidence or "none",
                        "score": decision.score,
                        "timestamp": now_iso,
                        "raw_value": "",
                        "elapsed_ms": int((time.monotonic() - _t_start) * 1000),
                    },
                )

    # Count mp4-present vs mp4-absent (FR-022)
    mapped_video_ids = set(vid for vid in mp4_video_id_map.values() if vid)
    mp4_present_count = len(mapped_video_ids)
    mp4_absent_count = 0

    for vm in video_list:
        if vm.video_id not in mapped_video_ids:
            mp4_absent_count += 1
            # ADV-35: video without mp4 in archive → retry_pending (ingest_no_mp4)
            unmapped_mp4_entries.append({
                "video_id": vm.video_id,
                "mp4_filename": None,
                "failed_stage": "ingest_no_mp4",
                "failure_reason": "no_mp4_in_archive",
            })
            if not dry_run:
                audit_writer.append_row(
                    "takeout_ingest",
                    {
                        "video_id": vm.video_id,
                        "result": "skip",
                        "reason": "no_mp4_in_archive",
                        "mp4_filename": "n/a",
                        "match_confidence": "n/a",
                        "score": 0,
                        "timestamp": now_iso,
                        "raw_value": "",
                        "elapsed_ms": int((time.monotonic() - _t_start) * 1000),
                    },
                )

    elapsed_seconds = time.monotonic() - _t_start

    if dry_run:
        return IngestResult(
            channel_id=channel_meta.channel_id,
            channel_alias=channel_alias,
            total_videos=len(video_list),
            new_videos=0,
            high_confidence_mappings=high_count,
            medium_confidence_mappings=medium_count,
            ambiguous_mappings=ambiguous_count,
            unmapped_filenames=unmapped_count,
            ignored_csv_count=ignored_csv_count,
            dry_run=True,
            mp4_present_count=mp4_present_count,
            mp4_absent_count=mp4_absent_count,
            elapsed_seconds=elapsed_seconds,
            unmapped_mp4_entries=unmapped_mp4_entries,
        )

    # Step 5: Persist to SQLite v4
    _ensure_v4(db_path)
    new_videos = _persist_metadata(db_path, channel_meta, video_list, channel_alias)

    # Step 6: Write channel_meta.json + videos_meta.json atomic
    work_dir = work_root / channel_alias
    work_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(
        work_dir / "channel_meta.json", channel_meta.model_dump(mode="json")
    )
    _write_json_atomic(
        work_dir / "videos_meta.json",
        [v.model_dump(mode="json") for v in video_list],
    )

    # Step 7: Assemble work_dir with mp4 symlinks
    assemble_channel_work_dir(takeout_dir, channel_alias, work_root, use_symlinks)

    # Build absolute path → video_id map for unified ingest downstream.
    # T-04 symlink containment is enforced at symlink creation in
    # assemble_channel_work_dir, so pre-existing symlinks from prior
    # multi-part ingest calls (FR-020) are trusted here.
    video_dir = work_dir / _VIDEO_SUBDIR
    abs_mp4_video_id_map: dict[str, str] = {}
    for filename, video_id in mp4_video_id_map.items():
        if video_id:
            abs_path = video_dir / filename
            if abs_path.exists() or abs_path.is_symlink():
                abs_mp4_video_id_map[str(abs_path.resolve())] = video_id

    elapsed_seconds = time.monotonic() - _t_start

    _logger.info(
        "ingest_takeout complete: alias=%s new=%d high=%d medium=%d "
        "ambiguous=%d unmapped=%d absent=%d elapsed=%.1fs",
        channel_alias,
        new_videos,
        high_count,
        medium_count,
        ambiguous_count,
        unmapped_count,
        mp4_absent_count,
        elapsed_seconds,
    )

    return IngestResult(
        channel_id=channel_meta.channel_id,
        channel_alias=channel_alias,
        total_videos=len(video_list),
        new_videos=new_videos,
        high_confidence_mappings=high_count,
        medium_confidence_mappings=medium_count,
        ambiguous_mappings=ambiguous_count,
        unmapped_filenames=unmapped_count,
        ignored_csv_count=ignored_csv_count,
        dry_run=False,
        mp4_present_count=mp4_present_count,
        mp4_absent_count=mp4_absent_count,
        elapsed_seconds=elapsed_seconds,
        mp4_video_id_map=abs_mp4_video_id_map,
        unmapped_mp4_entries=unmapped_mp4_entries,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _is_ignored(name: str) -> bool:
    """Return True if the filename matches an ignored-category pattern."""
    return any(p.match(name) for p in _IGNORED_PATTERNS)


def _ensure_v4(db_path: Path) -> None:
    """Bootstrap or migrate SQLite DB to schema v4 in-place."""
    from tube_scout.storage.content_db import (
        ContentDB,
        migrate_to_v2,
        migrate_to_v3,
        migrate_to_v4,
    )

    # Bootstrap full schema if new DB
    if not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # ContentDB.__init__ creates v1 schema tables
        db = ContentDB(db_path)
        db.close()
        migrate_to_v2(db_path)
        migrate_to_v3(db_path)
        migrate_to_v4(db_path)
        return

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
    if version < 2:
        migrate_to_v2(db_path)
    if version < 3:
        migrate_to_v3(db_path)
    migrate_to_v4(db_path)


def _persist_metadata(
    db_path: Path,
    channel_meta: ChannelMetadata,
    video_list: list[VideoMetadata],
    channel_alias: str,
) -> int:
    """Persist channel and video metadata using INSERT OR IGNORE.

    Idempotency guarantee (R-8 first-write-wins): video_metadata uses
    ``INSERT OR IGNORE`` so duplicate video_id rows from a later archive
    part are silently discarded — the original title/duration/privacy are
    preserved.  channel_metadata uses ``ON CONFLICT DO UPDATE`` limited to
    ``takeout_root_hint`` and ``ingested_at`` so channel title is also
    never overwritten.

    Args:
        db_path: SQLite database path (v4 schema required).
        channel_meta: Channel metadata to upsert.
        video_list: List of video metadata to insert (duplicates ignored).
        channel_alias: Alias for the channel record.

    Returns:
        Number of newly inserted video rows (0 on pure duplicate ingest).
    """
    now_iso = datetime.datetime.now(tz=datetime.UTC).isoformat()
    new_videos = 0

    with sqlite3.connect(db_path) as conn:
        # Upsert channel_metadata: on conflict update root_hint + ingested_at only
        conn.execute(
            """
            INSERT INTO channel_metadata
                (channel_id, channel_alias, title, country, privacy_status,
                 source, takeout_root_hint, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                takeout_root_hint = excluded.takeout_root_hint,
                ingested_at = excluded.ingested_at
            """,
            (
                channel_meta.channel_id,
                channel_alias,
                channel_meta.title,
                channel_meta.country,
                channel_meta.privacy_status,
                channel_meta.source,
                None,
                now_iso,
            ),
        )

        for vm in video_list:
            created_at_str = vm.created_at.isoformat() if vm.created_at else None
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO video_metadata
                    (video_id, channel_id, title, duration_seconds, language,
                     category, privacy_status, created_at, source,
                     match_confidence, mp4_relative_path, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vm.video_id,
                    vm.channel_id,
                    vm.title,
                    vm.duration_seconds,
                    vm.language,
                    vm.category,
                    vm.privacy_status,
                    created_at_str,
                    vm.source,
                    vm.match_confidence,
                    vm.mp4_relative_path,
                    now_iso,
                ),
            )
            if cur.rowcount > 0:
                new_videos += 1

    return new_videos


def _write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON to path atomically via a temp-file rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
