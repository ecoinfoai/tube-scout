"""Contract tests for source_video_cleanup audit vocabulary — T024 (spec 017 US3).

Validates that:
- Stage 1 Rich Table 어휘 (헤더 텍스트)
- Stage 2 prompt 메시지 한글
- audit row reason 어휘가 contract 와 글자 단위 일치:
  presented_failures, confirmed_yes, confirmed_no, timeout, interrupted,
  deleted, delete_failed_locked, delete_failed_io
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

NOW = datetime(2026, 5, 16, 8, 43, 42, tzinfo=UTC)

REQUIRED_AUDIT_REASONS = frozenset({
    "presented_failures",
    "confirmed_yes",
    "confirmed_no",
    "timeout",
    "interrupted",
    "deleted",
    "delete_failed_locked",
    "delete_failed_io",
})


def _make_failure(video_id: str = "abc123def45"):
    from tube_scout.models.content import FailureEntry

    return FailureEntry(
        video_id=video_id,
        title="1주차 1차시 (간호학과)",
        failed_stage="transcript",
        failure_reason="model_loading_failed",
        attempted_at=NOW,
    )


def _make_mp4(tmp_path: Path, name: str = "test.mp4") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x00" * 512)
    return p


def _make_audit_writer() -> MagicMock:
    return MagicMock()


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


def _collect_reasons(audit: MagicMock) -> list[str]:
    reasons = []
    for c in audit.append.call_args_list:
        args, kwargs = c
        row_dict = kwargs.get("row", args[1] if len(args) > 1 else {})
        if isinstance(row_dict, dict):
            reasons.append(row_dict.get("reason", ""))
    return reasons


# T024-1: present_failure_table 호출 시 audit reason = 'presented_failures' (글자 단위)
def test_contract_audit_reason_presented_failures(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import present_failure_table

    audit = _make_audit_writer()
    present_failure_table([_make_failure()], audit_writer=audit)

    reasons = _collect_reasons(audit)
    assert "presented_failures" in reasons, (
        f"Expected audit reason 'presented_failures', got: {reasons}"
    )


# T024-2: yes 응답 시 audit reason = 'confirmed_yes' (글자 단위)
def test_contract_audit_reason_confirmed_yes(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path)
    confirm_and_cleanup([str(mp4)], prompt_io=_YesIO(), audit_writer=audit)

    reasons = _collect_reasons(audit)
    assert "confirmed_yes" in reasons, (
        f"Expected 'confirmed_yes' in audit reasons, got: {reasons}"
    )


# T024-3: no 응답 시 audit reason = 'confirmed_no' (글자 단위)
def test_contract_audit_reason_confirmed_no(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path)
    confirm_and_cleanup([str(mp4)], prompt_io=_NoIO(), audit_writer=audit)

    reasons = _collect_reasons(audit)
    assert "confirmed_no" in reasons, (
        f"Expected 'confirmed_no' in audit reasons, got: {reasons}"
    )


# T024-4: EOF 시 audit reason = 'timeout' (글자 단위)
def test_contract_audit_reason_timeout(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path)
    confirm_and_cleanup([str(mp4)], prompt_io=_EofIO(), audit_writer=audit)

    reasons = _collect_reasons(audit)
    assert "timeout" in reasons, (
        f"Expected 'timeout' in audit reasons, got: {reasons}"
    )


# T024-5: Ctrl+C 시 audit reason = 'interrupted' (글자 단위)
def test_contract_audit_reason_interrupted(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path)
    confirm_and_cleanup([str(mp4)], prompt_io=_CtrlCIO(), audit_writer=audit)

    reasons = _collect_reasons(audit)
    assert "interrupted" in reasons, (
        f"Expected 'interrupted' in audit reasons, got: {reasons}"
    )


# T024-6: yes 응답 + 성공 시 audit reason = 'deleted' (글자 단위)
def test_contract_audit_reason_deleted(tmp_path: Path) -> None:
    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path)
    confirm_and_cleanup([str(mp4)], prompt_io=_YesIO(), audit_writer=audit)

    reasons = _collect_reasons(audit)
    assert "deleted" in reasons, (
        f"Expected 'deleted' in audit reasons, got: {reasons}"
    )


# T024-7: 파일 잠금 시 audit reason = 'delete_failed_locked' (글자 단위)
def test_contract_audit_reason_delete_failed_locked(tmp_path: Path) -> None:
    import errno
    from unittest.mock import patch

    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path, "locked.mp4")

    def locked_unlink(self: Path, missing_ok: bool = False) -> None:
        raise OSError(errno.EACCES, "Permission denied", str(self))

    with patch.object(Path, "unlink", locked_unlink):
        confirm_and_cleanup([str(mp4)], prompt_io=_YesIO(), audit_writer=audit)

    reasons = _collect_reasons(audit)
    assert "delete_failed_locked" in reasons, (
        f"Expected 'delete_failed_locked' in audit reasons, got: {reasons}"
    )


# T024-8: I/O 오류 시 audit reason = 'delete_failed_io' (글자 단위)
def test_contract_audit_reason_delete_failed_io(tmp_path: Path) -> None:
    import errno
    from unittest.mock import patch

    from tube_scout.services.source_video_cleanup import confirm_and_cleanup

    audit = _make_audit_writer()
    mp4 = _make_mp4(tmp_path, "ioerr.mp4")

    def io_unlink(self: Path, missing_ok: bool = False) -> None:
        raise OSError(errno.EIO, "Input/output error", str(self))

    with patch.object(Path, "unlink", io_unlink):
        confirm_and_cleanup([str(mp4)], prompt_io=_YesIO(), audit_writer=audit)

    reasons = _collect_reasons(audit)
    assert "delete_failed_io" in reasons, (
        f"Expected 'delete_failed_io' in audit reasons, got: {reasons}"
    )


# T024-9: Stage 1 출력에 '처리 실패 영상' 한글 어휘 포함 (Rich Table 헤더)
def test_contract_stage1_korean_header_in_output(tmp_path: Path, capsys) -> None:
    from tube_scout.services.source_video_cleanup import present_failure_table

    audit = _make_audit_writer()
    present_failure_table([_make_failure()], audit_writer=audit)

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "처리 실패" in combined or "실패 단계" in combined or "영상 제목" in combined, (
        "Stage 1 output must contain Korean header vocabulary from contract"
    )


# T024-10: audit reason 어휘가 CLEANUP_REASONS 상수와 일치
def test_contract_cleanup_reasons_vocabulary_matches_spec() -> None:
    from tube_scout.services.audit_writer import CLEANUP_REASONS

    assert "presented_failures" in CLEANUP_REASONS
    assert "confirmed_yes" in CLEANUP_REASONS
    assert "confirmed_no" in CLEANUP_REASONS
    assert "timeout" in CLEANUP_REASONS
    assert "interrupted" in CLEANUP_REASONS
    assert "deleted" in CLEANUP_REASONS
    assert "delete_failed_locked" in CLEANUP_REASONS
    assert "delete_failed_io" in CLEANUP_REASONS
