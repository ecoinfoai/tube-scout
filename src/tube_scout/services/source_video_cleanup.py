"""Source video deletion stage for collect ingest --delete-source (spec 017 US3).

FR-011~FR-014, SC-003, SC-007: two-step prompt — show failure table, then
confirm deletion candidates. Unlinks archive mp4 + symlink on operator yes.
"""

from __future__ import annotations

import errno
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rich.console import Console
from rich.table import Table

from tube_scout.models.content import CleanupResult, FailureEntry


class PromptIO(Protocol):
    """Protocol for operator prompt I/O during the deletion confirmation step."""

    def ask_yes_no(self, message: str, *, default: bool = False) -> bool:
        """Prompt operator for a yes/no answer.

        Args:
            message: Question to display.
            default: Default answer if operator presses Enter without input.

        Returns:
            True for yes, False for no.
        """
        ...


def _append_audit(audit_writer: object, stage: str, row: dict) -> None:
    """Call audit_writer.append(stage, row=row) or append_row(stage, row) as available.

    Uses append() first (test mocks); falls back to append_row() for AuditWriter.
    """
    from tube_scout.services.audit_writer import AuditWriter
    if isinstance(audit_writer, AuditWriter):
        audit_writer.append_row(stage, row)
    else:
        audit_writer.append(stage, row=row)  # type: ignore[union-attr]


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def present_failure_table(
    failures: list[FailureEntry],
    *,
    console: Console | None = None,
    audit_writer: object,
) -> None:
    """Show a Rich table of processing-failed videos to the operator.

    Displays the failure table (Stage 1) then appends one audit row with
    reason=presented_failures regardless of failure count.

    Args:
        failures: List of FailureEntry from transcript/fingerprint stages.
        console: Rich Console instance; defaults to stderr Console if None.
        audit_writer: AuditWriter (or compatible mock) for audit rows.
    """
    _console = console or Console(stderr=True)

    if failures:
        table = Table(
            title="[처리 실패 영상 — 자동 보존됨]",
            show_header=True,
            header_style="bold red",
        )
        table.add_column("video_id")
        table.add_column("영상 제목")
        table.add_column("실패 단계")
        table.add_column("실패 사유")
        for f in failures:
            table.add_row(f.video_id, f.title, f.failed_stage, f.failure_reason)
        _console.print(table)
        _console.print(
            "다음 영상은 처리 실패로 인해 삭제 후보에서 자동 제외되었습니다 "
            "(재시도 매니페스트에 기록됨)."
        )
    else:
        _console.print("처리 실패 영상 없음 — 모든 영상이 삭제 후보입니다")

    _append_audit(audit_writer, "source_video_cleanup", {
        "video_id": "n/a",
        "result": "success",
        "reason": "presented_failures",
        "candidate_count": len(failures),
        "deleted_count": 0,
        "reclaimed_bytes": 0,
        "elapsed_ms": 0,
        "timestamp": _now_iso(),
    })


def _check_path_containment(path: Path, allowed_roots: list[Path]) -> None:
    """Raise ValueError if path is not inside any of the allowed_roots.

    Resolves symlinks on the candidate path to detect symlink chain escapes
    (T-04 latent critical: abs_path.resolve() may follow chains outside archive).

    Args:
        path: Candidate mp4 path to validate.
        allowed_roots: List of directories the path must be under.

    Raises:
        ValueError: path (or its resolved target) is outside all allowed_roots.
    """
    resolved = path.resolve()
    for root in allowed_roots:
        root_resolved = root.resolve()
        try:
            resolved.relative_to(root_resolved)
            return
        except ValueError:
            continue
    raise ValueError(
        f"Candidate path {path!r} (resolved: {resolved!r}) is outside all "
        f"allowed roots {[str(r) for r in allowed_roots]}. "
        "Refusing to delete — possible symlink escape."
    )


def confirm_and_cleanup(
    candidates: list[str],
    *,
    prompt_io: PromptIO | None = None,
    audit_writer: object,
    allowed_roots: list[Path] | None = None,
) -> CleanupResult:
    """Prompt operator for deletion confirmation, then unlink source mp4 files.

    Stage 2 of the --delete-source two-prompt flow. Records every transition
    (confirmed_yes / confirmed_no / timeout / interrupted / deleted /
    delete_failed_locked / delete_failed_io) in the audit log.

    Args:
        candidates: List of mp4 absolute path strings eligible for deletion.
        prompt_io: PromptIO implementation; uses Rich Confirm.ask if None.
        audit_writer: AuditWriter (or compatible mock) for audit rows.
        allowed_roots: If provided, each candidate must be under one of these
            directories (symlink-resolved). Raises ValueError otherwise (T-04).

    Returns:
        CleanupResult with deletion outcome.

    Raises:
        ValueError: Any candidate is outside allowed_roots (path containment).
    """
    t_start = time.monotonic()
    candidate_count = len(candidates)

    try:
        if prompt_io is not None:
            answer = prompt_io.ask_yes_no(
                f"Delete {candidate_count} source mp4 files? (y/N): ",
                default=False,
            )
        else:
            from rich.prompt import Confirm
            answer = Confirm.ask(
                f"Delete {candidate_count} source mp4 files?",
                default=False,
            )
    except EOFError:
        _append_audit(audit_writer, "source_video_cleanup", {
            "video_id": "n/a",
            "result": "success",
            "reason": "timeout",
            "candidate_count": candidate_count,
            "deleted_count": 0,
            "reclaimed_bytes": 0,
            "elapsed_ms": int((time.monotonic() - t_start) * 1000),
            "timestamp": _now_iso(),
        })
        return CleanupResult(
            presented_failure_count=0,
            deletion_candidate_count=candidate_count,
            operator_response="timeout",
            deleted_count=0,
            failed_to_delete_count=0,
            reclaimed_bytes=0,
            elapsed_seconds=time.monotonic() - t_start,
        )
    except KeyboardInterrupt:
        _append_audit(audit_writer, "source_video_cleanup", {
            "video_id": "n/a",
            "result": "success",
            "reason": "interrupted",
            "candidate_count": candidate_count,
            "deleted_count": 0,
            "reclaimed_bytes": 0,
            "elapsed_ms": int((time.monotonic() - t_start) * 1000),
            "timestamp": _now_iso(),
        })
        return CleanupResult(
            presented_failure_count=0,
            deletion_candidate_count=candidate_count,
            operator_response="interrupted",
            deleted_count=0,
            failed_to_delete_count=0,
            reclaimed_bytes=0,
            elapsed_seconds=time.monotonic() - t_start,
        )

    if not answer:
        _append_audit(audit_writer, "source_video_cleanup", {
            "video_id": "n/a",
            "result": "success",
            "reason": "confirmed_no",
            "candidate_count": candidate_count,
            "deleted_count": 0,
            "reclaimed_bytes": 0,
            "elapsed_ms": int((time.monotonic() - t_start) * 1000),
            "timestamp": _now_iso(),
        })
        return CleanupResult(
            presented_failure_count=0,
            deletion_candidate_count=candidate_count,
            operator_response="no",
            deleted_count=0,
            failed_to_delete_count=0,
            reclaimed_bytes=0,
            elapsed_seconds=time.monotonic() - t_start,
        )

    # operator said yes — perform deletions
    _append_audit(audit_writer, "source_video_cleanup", {
        "video_id": "n/a",
        "result": "success",
        "reason": "confirmed_yes",
        "candidate_count": candidate_count,
        "deleted_count": 0,
        "reclaimed_bytes": 0,
        "elapsed_ms": 0,
        "timestamp": _now_iso(),
    })

    deleted_count = 0
    failed_locked = 0
    failed_io = 0
    reclaimed_bytes = 0

    for mp4_str in candidates:
        mp4_path = Path(mp4_str)
        if allowed_roots:
            _check_path_containment(mp4_path, allowed_roots)
        try:
            size = mp4_path.stat().st_size if mp4_path.exists() else 0
            mp4_path.unlink(missing_ok=True)
            reclaimed_bytes += size
            deleted_count += 1
            _append_audit(audit_writer, "source_video_cleanup", {
                "video_id": mp4_path.stem,
                "result": "success",
                "reason": "deleted",
                "candidate_count": candidate_count,
                "deleted_count": deleted_count,
                "reclaimed_bytes": size,
                "elapsed_ms": int((time.monotonic() - t_start) * 1000),
                "timestamp": _now_iso(),
            })
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM):
                reason = "delete_failed_locked"
                failed_locked += 1
            else:
                reason = "delete_failed_io"
                failed_io += 1
            _append_audit(audit_writer, "source_video_cleanup", {
                "video_id": mp4_path.stem,
                "result": "fail",
                "reason": reason,
                "candidate_count": candidate_count,
                "deleted_count": deleted_count,
                "reclaimed_bytes": 0,
                "elapsed_ms": int((time.monotonic() - t_start) * 1000),
                "timestamp": _now_iso(),
            })

    elapsed = time.monotonic() - t_start
    return CleanupResult(
        presented_failure_count=0,
        deletion_candidate_count=candidate_count,
        operator_response="yes",
        deleted_count=deleted_count,
        failed_to_delete_count=failed_locked + failed_io,
        reclaimed_bytes=reclaimed_bytes,
        elapsed_seconds=elapsed,
    )
