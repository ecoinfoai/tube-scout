"""Audit CSV writer for transcript and fingerprint processing records.

spec 012 FR-015 + spec 013 FR-057~FR-060.
Append-only CSV with atomic writes via tempfile+rename.
Header written once on file creation (data-model E-5, E-12).
"""

import csv
import os
import tempfile
from pathlib import Path

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

# spec 017 E-8 (FR-017) + spec 018 (FR-018F) reason vocabulary
# Idempotency-guard reasons: already_transcribed, already_fingerprinted,
# already_transcribed_and_fingerprinted (data-model §5 / contract idempotency-guard §8).
ORCHESTRATOR_REASONS: frozenset[str] = frozenset({
    "started", "completed", "aborted_by_user", "failed_intermediate_stage",
    "stub_not_implemented", "registry_load_failed",
    "asr_transcribed", "captured",
    "asr_fail", "fp_fail",
    "already_transcribed", "already_fingerprinted",
    "already_transcribed_and_fingerprinted",
    "forced_reprocess",
})
CLEANUP_REASONS: frozenset[str] = frozenset({
    "presented_failures", "confirmed_yes", "confirmed_no",
    "timeout", "interrupted",
    "deleted", "delete_failed_locked", "delete_failed_io",
})

VALID_RESULTS: frozenset[str] = frozenset({"success", "skip", "fail"})


class AuditWriter:
    """Append-only audit CSV writer for spec 012 processing records.

    Args:
        project_dir: Project root directory. Audit files are written under
            <project_dir>/01_collect/.
    """

    def __init__(self, project_dir: Path) -> None:
        self._collect_dir = project_dir / "01_collect"
        self._collect_dir.mkdir(parents=True, exist_ok=True)

    def _append_row(
        self, csv_path: Path, fieldnames: tuple[str, ...], row: dict
    ) -> None:
        """Append a single row to csv_path using atomic tempfile+rename."""
        write_header = not csv_path.exists()

        # Read existing content if file already exists
        existing = csv_path.read_bytes() if csv_path.exists() else b""

        # Write to temp file in same directory (same filesystem for atomic rename)
        fd, tmp_path_str = tempfile.mkstemp(
            dir=self._collect_dir, prefix=csv_path.name + ".tmp"
        )
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                if existing:
                    f.write(existing.decode("utf-8"))
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
            os.replace(tmp_path_str, csv_path)
        except Exception:
            try:
                os.unlink(tmp_path_str)
            except OSError:
                pass
            raise

    def append_row(self, stage: str, row: dict) -> None:
        """Append a row to <project_dir>/01_collect/<stage>_audit.csv.

        Args:
            stage: One of STAGE_FIELDNAMES keys.
            row: Dict with at least all keys in STAGE_FIELDNAMES[stage].
                Extra keys are dropped (csv.DictWriter extrasaction='ignore').

        Raises:
            KeyError: stage not in STAGE_FIELDNAMES.
            ValueError: row['result'] not in VALID_RESULTS.
        """
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
