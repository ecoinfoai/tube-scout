"""Stage-aware progress reporter with TTY/non-TTY auto-detection.

spec 013 FR-061.
"""

import sys
import time
from typing import Protocol


class ProgressReporter(Protocol):
    """Stage-aware progress reporter (TTY/non-TTY auto-adaptive)."""

    def update(self, video_id: str, n: int) -> None:
        """Update progress.

        Args:
            video_id: Current video ID (or pair_id for analyze stage).
            n: 1-based progress count.
        """

    def __enter__(self) -> "ProgressReporter": ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool | None: ...


class TTYProgressReporter:
    """Rich progress bar for interactive TTY sessions."""

    def __init__(self, stage: str, total: int) -> None:
        """Initialize TTY reporter.

        Args:
            stage: Pipeline stage name.
            total: Total item count.
        """
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TaskProgressColumn,
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )

        self._stage = stage
        self._total = total
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn(f"[bold blue]{stage}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[video_id]}"),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
        )
        self._task_id = None

    def __enter__(self) -> "TTYProgressReporter":
        self._progress.__enter__()
        self._task_id = self._progress.add_task("", total=self._total, video_id="")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool | None:
        return self._progress.__exit__(exc_type, exc_val, exc_tb)

    def update(self, video_id: str, n: int) -> None:
        """Update rich progress bar.

        Args:
            video_id: Current video ID.
            n: 1-based progress count.
        """
        self._progress.update(self._task_id, completed=n, video_id=video_id)


class NonTTYProgressReporter:
    """Structured stdout log lines for non-interactive (cron/pipe) sessions."""

    def __init__(
        self,
        stage: str,
        total: int,
        throttle_n: int,
        throttle_seconds: float,
    ) -> None:
        """Initialize NonTTY reporter.

        Args:
            stage: Pipeline stage name.
            total: Total item count.
            throttle_n: Emit a line every N items.
            throttle_seconds: Emit a line every K seconds (whichever fires first).
        """
        self._stage = stage
        self._total = total
        self._throttle_n = throttle_n
        self._throttle_seconds = throttle_seconds
        self._start_time: float | None = None
        self._last_emit_time: float = 0.0
        self._last_emit_n: int = 0

    def __enter__(self) -> "NonTTYProgressReporter":
        self._start_time = time.monotonic()
        self._last_emit_time = self._start_time
        sys.stdout.write(f"[{self._stage}] starting total={self._total}\n")
        sys.stdout.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed = time.monotonic() - (self._start_time or 0)
        sys.stdout.write(f"[{self._stage}] finished elapsed={elapsed:.1f}s\n")
        sys.stdout.flush()
        return None

    def update(self, video_id: str, n: int) -> None:
        """Emit a structured log line when throttle conditions are met.

        Args:
            video_id: Current video ID.
            n: 1-based progress count.
        """
        now = time.monotonic()
        n_condition = (n - self._last_emit_n) < self._throttle_n
        t_condition = (now - self._last_emit_time) < self._throttle_seconds
        if n_condition and t_condition and n < self._total:
            return
        elapsed = now - (self._start_time or now)
        eta = (self._total - n) * (elapsed / n) if n > 3 else 0.0
        eta_str = f"ETA={eta:.0f}s" if eta > 0 else "ETA=?"
        sys.stdout.write(
            f"[{self._stage}] video_id={video_id}"
            f" N={n}/total={self._total}"
            f" elapsed={elapsed:.1f}s {eta_str}\n"
        )
        sys.stdout.flush()
        self._last_emit_time = now
        self._last_emit_n = n


def make_progress_reporter(
    stage: str,
    total: int,
    *,
    force_tty: bool | None = None,
    nontty_throttle_n: int = 1,
    nontty_throttle_seconds: float = 60.0,
) -> ProgressReporter:
    """Create a stage-aware progress reporter, auto-detecting TTY.

    Args:
        stage: Pipeline stage name ('takeout_ingest', 'audio_extract', etc.).
        total: Total item count (video count or pair count).
        force_tty: None=auto-detect via sys.stdout.isatty(), True/False=forced.
        nontty_throttle_n: Emit every N items in non-TTY mode.
        nontty_throttle_seconds: Emit every K seconds in non-TTY mode.

    Returns:
        TTYProgressReporter or NonTTYProgressReporter.
    """
    use_tty = sys.stdout.isatty() if force_tty is None else force_tty
    if use_tty:
        return TTYProgressReporter(stage, total)
    return NonTTYProgressReporter(
        stage, total, nontty_throttle_n, nontty_throttle_seconds
    )
