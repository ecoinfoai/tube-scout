"""Audit CSV writer for transcript and fingerprint processing records (spec 012, FR-015).

Append-only CSV writer with atomic writes via tempfile+rename.
Header written once on file creation (data-model E-5).
"""

import csv
import os
import tempfile
from pathlib import Path

TRANSCRIPTS_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason", "source", "timestamp", "cookies_source"
)

FINGERPRINT_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason", "duration_sec", "timestamp", "cookies_source"
)


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

    def append_transcript_row(self, row: dict) -> None:
        """Append a row to transcripts_audit.csv.

        Args:
            row: Dict with keys matching TRANSCRIPTS_FIELDNAMES.
        """
        self._append_row(
            self._collect_dir / "transcripts_audit.csv",
            TRANSCRIPTS_FIELDNAMES,
            row,
        )

    def append_fingerprint_row(self, row: dict) -> None:
        """Append a row to fingerprint_audit.csv.

        Args:
            row: Dict with keys matching FINGERPRINT_FIELDNAMES.
        """
        self._append_row(
            self._collect_dir / "fingerprint_audit.csv",
            FINGERPRINT_FIELDNAMES,
            row,
        )
