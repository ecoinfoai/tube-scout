"""Audit CSV writer for transcript and fingerprint processing records.

spec 012 FR-015 + spec 013 FR-057~FR-060.
Append-only CSV with O(1) append + POSIX flock for concurrent safety.
Header written once on file creation (data-model E-5, E-12).
"""

import atexit
import csv
import logging
import os
import time
from pathlib import Path

_logger = logging.getLogger(__name__)

# ─── fieldnames (unified v2 — spec 012 shims inject missing defaults) ─────────

TRANSCRIPTS_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason",
    "source", "caption_source_detail", "timestamp", "cookies_source",
)

FINGERPRINT_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason",
    "duration_sec", "fingerprint_input_policy", "timestamp", "cookies_source",
)

# ─── spec 013 v2 stage fieldnames ─────────────────────────────────────────────

TAKEOUT_INGEST_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason",
    "mp4_filename", "match_confidence", "score", "timestamp",
    "raw_value", "elapsed_ms",
)
AUDIO_EXTRACT_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason",
    "input_kind", "output_path", "wav_size_bytes", "elapsed_s", "timestamp",
)
NORMALIZE_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason",
    "input_source", "normalizer_version", "timestamp",
)
ANALYZE_FIELDNAMES: tuple[str, ...] = (
    "pair_id", "source_video_id", "target_video_id",
    "result", "reason", "matching_mode", "elapsed_s", "timestamp",
)
REPORT_FIELDNAMES: tuple[str, ...] = (
    "professor", "channel", "result", "reason",
    "format", "output_path", "pair_count", "appendix_count", "timestamp",
)
KB_EXPORT_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason",
    "format", "output_path", "byte_count", "timestamp",
)

# ─── spec 017 E-8 stage fieldnames ────────────────────────────────────────────

INGEST_ORCHESTRATOR_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason",
    "channel_alias", "elapsed_ms", "timestamp",
)
SOURCE_VIDEO_CLEANUP_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason",
    "candidate_count", "deleted_count", "reclaimed_bytes", "elapsed_ms", "timestamp",
)

STAGE_FIELDNAMES: dict[str, tuple[str, ...]] = {
    "takeout_ingest":      TAKEOUT_INGEST_FIELDNAMES,
    "audio_extract":       AUDIO_EXTRACT_FIELDNAMES,
    "transcripts":         TRANSCRIPTS_FIELDNAMES,
    "fingerprint":         FINGERPRINT_FIELDNAMES,
    "normalize":           NORMALIZE_FIELDNAMES,
    "analyze":             ANALYZE_FIELDNAMES,
    "report":              REPORT_FIELDNAMES,
    "kb_export":           KB_EXPORT_FIELDNAMES,
    "ingest_orchestrator": INGEST_ORCHESTRATOR_FIELDNAMES,
    "source_video_cleanup": SOURCE_VIDEO_CLEANUP_FIELDNAMES,
}

# Closed vocabulary for ingest_orchestrator stage reason field (DOC-2).
# Each token must be documented here before use in caller code.
# Dead entries must be removed here and from all callers simultaneously.
# F-11 owns aborted_by_user activation; F-3b owns sub_reason extension.
ORCHESTRATOR_REASONS: frozenset[str] = frozenset({
    "started", "completed", "aborted_by_user", "failed_intermediate_stage",
    "stub_not_implemented", "registry_load_failed",
    "asr_transcribed", "captured",
    "asr_fail", "fp_fail",
    "already_transcribed", "already_fingerprinted",
    "forced_reprocess",
})
CLEANUP_REASONS: frozenset[str] = frozenset({
    "presented_failures", "confirmed_yes", "confirmed_no",
    "timeout", "interrupted",
    "deleted", "delete_failed_locked", "delete_failed_io",
})

VALID_RESULTS: frozenset[str] = frozenset({"success", "skip", "fail"})

_RETRY_DELAYS: tuple[float, ...] = (0.1, 0.2, 0.5)


def _flock_ex(fd: int) -> None:
    """Acquire exclusive POSIX flock; no-op on non-POSIX platforms."""
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
    except ImportError:
        pass  # Windows: skip flock, best-effort


def _flock_un(fd: int) -> None:
    """Release POSIX flock; no-op on non-POSIX platforms."""
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    except ImportError:
        pass


class AuditWriter:
    """Append-only audit CSV writer for spec 012 processing records.

    Writes are O(1) append with POSIX flock for concurrent worker safety.
    On persistent write failure, rows are buffered in memory and flushed
    to .audit_recovery.csv on process exit via atexit.

    Args:
        project_dir: Project root directory. Audit files are written under
            <project_dir>/01_collect/.
    """

    def __init__(self, project_dir: Path) -> None:
        self._collect_dir = project_dir / "01_collect"
        self._collect_dir.mkdir(parents=True, exist_ok=True)
        self._pending: list[tuple[Path, tuple[str, ...], dict]] = []
        atexit.register(self._flush_pending)

    def _append_row(
        self, csv_path: Path, fieldnames: tuple[str, ...], row: dict
    ) -> None:
        """Append one row via O(1) open-append + flock.

        Retries up to 3 times on OSError with exponential backoff.
        On persistent failure, buffers to in-memory pending list.
        """
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                self._do_append(csv_path, fieldnames, row)
                return
            except OSError as exc:
                if delay is None:
                    _logger.warning(
                        "audit_writer: write failed after %d attempts for %s: %s — buffering row",
                        attempt - 1, csv_path.name, exc,
                    )
                    self._pending.append((csv_path, fieldnames, row))
                    return
                _logger.debug("audit_writer: write attempt %d failed (%s), retrying in %.1fs", attempt, exc, delay)
                time.sleep(delay)

    def _do_append(
        self, csv_path: Path, fieldnames: tuple[str, ...], row: dict
    ) -> None:
        """Single O(1) append attempt with flock."""
        write_header = not csv_path.exists()
        fd = os.open(
            str(csv_path),
            os.O_CREAT | os.O_WRONLY | os.O_APPEND,
            0o600,
        )
        try:
            _flock_ex(fd)
            with os.fdopen(fd, "a", newline="", encoding="utf-8", closefd=False) as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        finally:
            _flock_un(fd)
            os.close(fd)

    def _flush_pending(self) -> None:
        """Write buffered rows to .audit_recovery.csv files on exit."""
        if not self._pending:
            return
        recovery = self._collect_dir / ".audit_recovery.csv"
        try:
            with recovery.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for csv_path, fieldnames, row in self._pending:
                    writer.writerow([csv_path.name] + [row.get(k, "") for k in fieldnames])
            _logger.warning(
                "audit_writer: flushed %d pending rows to %s", len(self._pending), recovery
            )
        except OSError as exc:
            _logger.error("audit_writer: recovery flush failed: %s", exc)
        self._pending.clear()

    def append_row(self, stage: str, row: dict) -> None:
        """Append a row to <project_dir>/01_collect/<stage>_audit.csv.

        Failures are logged and swallowed — callers must not abort on audit errors.

        Args:
            stage: One of STAGE_FIELDNAMES keys.
            row: Dict with at least all keys in STAGE_FIELDNAMES[stage].
                Extra keys are dropped (csv.DictWriter extrasaction='ignore').
        """
        try:
            if stage not in STAGE_FIELDNAMES:
                valid = sorted(STAGE_FIELDNAMES)
                raise KeyError(f"Unknown audit stage: {stage!r}. Valid stages: {valid}")
            if row.get("result") not in VALID_RESULTS:
                raise ValueError(
                    f"row['result'] must be one of {sorted(VALID_RESULTS)}, "
                    f"got {row.get('result')!r}"
                )
            if stage == "takeout_ingest":
                row = {"raw_value": "", "elapsed_ms": 0, **row}
            self._append_row(
                self._collect_dir / f"{stage}_audit.csv",
                STAGE_FIELDNAMES[stage],
                row,
            )
        except (KeyError, ValueError) as exc:
            _logger.warning("audit_writer.append_row: validation error (stage=%r): %s", stage, exc)

    def append_takeout_ingest_row(self, row: dict) -> None:
        """Append a row to takeout_ingest_audit.csv.

        Args:
            row: Dict with keys matching TAKEOUT_INGEST_FIELDNAMES.
                raw_value defaults to "" and elapsed_ms to 0 if absent (FR-023 shim).
        """
        row = {
            "raw_value": "",
            "elapsed_ms": 0,
            **row,
        }
        self.append_row("takeout_ingest", row)

    def append_transcript_row(self, row: dict) -> None:
        """Append a row to transcripts_audit.csv.

        Args:
            row: Dict with keys matching TRANSCRIPTS_FIELDNAMES.
                caption_source_detail defaults to "n/a" if absent (spec 012 shim).
        """
        row = {**row, "caption_source_detail": row.get("caption_source_detail", "n/a")}
        self.append_row("transcripts", row)

    def append_fingerprint_row(self, row: dict) -> None:
        """Append a row to fingerprint_audit.csv.

        Args:
            row: Dict with keys matching FINGERPRINT_FIELDNAMES.
                fingerprint_input_policy defaults to "n/a" if absent (spec 012 shim).
        """
        default = row.get("fingerprint_input_policy", "n/a")
        row = {**row, "fingerprint_input_policy": default}
        self.append_row("fingerprint", row)
