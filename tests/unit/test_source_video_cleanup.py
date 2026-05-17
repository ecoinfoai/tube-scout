"""Unit tests for services/source_video_cleanup.py — T022 Acceptance Matrix 10 cases (spec 017 US3)."""

from __future__ import annotations

import errno
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

NOW = datetime(2026, 5, 16, 8, 43, 42, tzinfo=UTC)


def _make_failure(video_id: str = "abc123def45"):
    from tube_scout.models.content import FailureEntry

    return FailureEntry(
        video_id=video_id,
        title="1주차 1차시",
        failed_stage="transcript",
        failure_reason="model_loading_failed",
        attempted_at=NOW,
    )


def _make_mp4(tmp_path: Path, name: str = "vid001.mp4") -> Path:
    mp4 = tmp_path / name
    mp4.write_bytes(b"\x00" * 1024)
    return mp4


def _make_audit_writer() -> MagicMock:
    writer = MagicMock()
    writer.append = MagicMock()
    return writer


class _YesIO:
    def ask_yes_no(self, message: str, *, default: bool = False) -> bool:
        return True


class _NoIO:
    def ask_yes_no(self, message: str, *, default: bool = False) -> bool:
        return False


class _EofIO:
    def ask_yes_no(self, message: str, *, default: bool = False) -> bool:
        raise EOFError


class _CtrlCIO:
    def ask_yes_no(self, message: str, *, default: bool = False) -> bool:
        raise KeyboardInterrupt


def _audit_reasons(audit: MagicMock) -> list[str]:
    return [str(c) for c in audit.append.call_args_list]


# T022-1: zero failures + yes → unlink every video, audit confirmed_yes + deleted × N
def test_cleanup_no_failures_yes_unlinks_all(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import (
        confirm_and_cleanup,
        present_failure_table,
    )

    audit = _make_audit_writer()
    present_failure_table([], audit_writer=audit)

    mp4 = _make_mp4(tmp_path)
    result = confirm_and_cleanup([str(mp4)], prompt_io=_YesIO(), audit_writer=audit)

    assert result.operator_response == "yes"
    assert result.deleted_count == 1
    assert not mp4.exists()
    reasons = _audit_reasons(audit)
    assert any("confirmed_yes" in r for r in reasons)
    assert any("deleted" in r for r in reasons)


# T022-2: N failures + yes → only successes unlinked, audit presented_failures + confirmed_yes + deleted
def test_cleanup_with_failures_yes_unlinks_candidates_only(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import (
        confirm_and_cleanup,
        present_failure_table,
    )

    audit = _make_audit_writer()
    failures = [_make_failure("fail001")]
    present_failure_table(failures, audit_writer=audit)

    mp4 = _make_mp4(tmp_path)
    result = confirm_and_cleanup([str(mp4)], prompt_io=_YesIO(), audit_writer=audit)

    assert result.operator_response == "yes"
    assert result.deleted_count == 1
    reasons = _audit_reasons(audit)
    assert any("presented_failures" in r for r in reasons)
    assert any("confirmed_yes" in r for r in reasons)


# T022-3: zero failures + no → 0 unlinks, audit confirmed_no
def test_cleanup_no_failures_no_preserves_all(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import (
        confirm_and_cleanup,
        present_failure_table,
    )

    audit = _make_audit_writer()
    present_failure_table([], audit_writer=audit)

    mp4 = _make_mp4(tmp_path)
    result = confirm_and_cleanup([str(mp4)], prompt_io=_NoIO(), audit_writer=audit)

    assert result.operator_response == "no"
    assert result.deleted_count == 0
    assert mp4.exists()
    reasons = _audit_reasons(audit)
    assert any("confirmed_no" in r for r in reasons)


# T022-4: N failures + no → 0 unlinks, audit presented_failures + confirmed_no
def test_cleanup_with_failures_no_preserves_all(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import (
        confirm_and_cleanup,
        present_failure_table,
    )

    audit = _make_audit_writer()
    failures = [_make_failure("fail002")]
    present_failure_table(failures, audit_writer=audit)

    mp4 = _make_mp4(tmp_path)
    result = confirm_and_cleanup([str(mp4)], prompt_io=_NoIO(), audit_writer=audit)

    assert result.operator_response == "no"
    assert result.deleted_count == 0
    reasons = _audit_reasons(audit)
    assert any("presented_failures" in r for r in reasons)
    assert any("confirmed_no" in r for r in reasons)


# T022-5: EOF → unlink 0, audit timeout
def test_cleanup_eof_preserves_all(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path)
    result = confirm_and_cleanup([str(mp4)], prompt_io=_EofIO(), audit_writer=audit)

    assert result.operator_response == "timeout"
    assert result.deleted_count == 0
    assert mp4.exists()
    reasons = _audit_reasons(audit)
    assert any("timeout" in r for r in reasons)


# T022-6: Ctrl+C → 0 unlinks, audit interrupted, exception swallowed
def test_cleanup_ctrl_c_preserves_all_no_propagation(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path)
    result = confirm_and_cleanup([str(mp4)], prompt_io=_CtrlCIO(), audit_writer=audit)

    assert result.operator_response == "interrupted"
    assert result.deleted_count == 0
    assert mp4.exists()
    reasons = _audit_reasons(audit)
    assert any("interrupted" in r for r in reasons)


# T022-7: file locked → locked file audits delete_failed_locked, rest deleted
def test_cleanup_file_locked_partial_delete(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    ok_mp4 = _make_mp4(tmp_path, "ok.mp4")
    locked_mp4 = _make_mp4(tmp_path, "locked.mp4")

    original_unlink = Path.unlink

    def selective_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "locked.mp4":
            raise OSError(errno.EACCES, "Permission denied", str(self))
        original_unlink(self, missing_ok=missing_ok)

    with patch.object(Path, "unlink", selective_unlink):
        result = confirm_and_cleanup(
            [str(ok_mp4), str(locked_mp4)], prompt_io=_YesIO(), audit_writer=audit
        )

    assert result.deleted_count >= 1
    assert result.failed_to_delete_count >= 1
    reasons = _audit_reasons(audit)
    assert any("delete_failed_locked" in r for r in reasons)
    assert any("deleted" in r for r in reasons)


# T022-8: I/O error → I/O-affected file audits delete_failed_io, rest deleted
def test_cleanup_io_error_partial_delete(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    ok_mp4 = _make_mp4(tmp_path, "ok2.mp4")
    io_mp4 = _make_mp4(tmp_path, "ioerr.mp4")

    original_unlink = Path.unlink

    def selective_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "ioerr.mp4":
            raise OSError(errno.EIO, "Input/output error", str(self))
        original_unlink(self, missing_ok=missing_ok)

    with patch.object(Path, "unlink", selective_unlink):
        result = confirm_and_cleanup(
            [str(ok_mp4), str(io_mp4)], prompt_io=_YesIO(), audit_writer=audit
        )

    assert result.failed_to_delete_count >= 1
    reasons = _audit_reasons(audit)
    assert any("delete_failed_io" in r for r in reasons)


# T022-9: present_failure_table with 0 failures → audit presented_failures
def test_present_failure_table_zero_failures_logs_audit(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import present_failure_table

    audit = _make_audit_writer()
    present_failure_table([], audit_writer=audit)

    reasons = _audit_reasons(audit)
    assert any("presented_failures" in r for r in reasons)


# T022-10: present_failure_table with N failures → audit presented_failures
def test_present_failure_table_with_failures_logs_audit(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import present_failure_table

    audit = _make_audit_writer()
    failures = [_make_failure("vid_x"), _make_failure("vid_y")]
    present_failure_table(failures, audit_writer=audit)

    reasons = _audit_reasons(audit)
    assert any("presented_failures" in r for r in reasons)
