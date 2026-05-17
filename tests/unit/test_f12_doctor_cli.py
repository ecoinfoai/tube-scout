"""Tests for F-12: doctor CLI (E-2.a/D-1.b/ADV-28/C-4/ADV-9/10/ADV-31).

Covers _CheckResult API, individual check functions, --exit-code flag, and
main.app command registration.  All checks use mocking — no network/HF calls.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import surface
# ---------------------------------------------------------------------------

def test_run_checks_importable() -> None:
    from tube_scout.cli.doctor import _run_checks  # noqa: F401


def test_check_result_is_named_tuple() -> None:
    from tube_scout.cli.doctor import _CheckResult

    r = _CheckResult(label="x", status="[green]PASS[/green]", detail="ok")
    assert r.label == "x"
    assert r.verbose_detail == ""


# ---------------------------------------------------------------------------
# _check_nix_shell
# ---------------------------------------------------------------------------

def test_check_nix_shell_pass_when_set() -> None:
    from tube_scout.cli.doctor import _PASS, _check_nix_shell

    with patch.dict(os.environ, {"IN_NIX_SHELL": "1"}, clear=False):
        r = _check_nix_shell()

    assert r.status == _PASS
    assert "IN_NIX_SHELL" in r.detail


def test_check_nix_shell_warn_when_absent() -> None:
    from tube_scout.cli.doctor import _WARN, _check_nix_shell

    env = {k: v for k, v in os.environ.items() if k not in ("IN_NIX_SHELL", "NIX_DEVELOP_PROFILE")}
    with patch.dict(os.environ, env, clear=True):
        r = _check_nix_shell()

    assert r.status == _WARN


# ---------------------------------------------------------------------------
# _check_faster_whisper
# ---------------------------------------------------------------------------

def test_check_faster_whisper_pass_when_importable() -> None:
    from tube_scout.cli.doctor import _PASS, _check_faster_whisper

    fake_fw = MagicMock()
    fake_fw.__version__ = "1.1.0"
    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        r = _check_faster_whisper()

    assert r.status == _PASS
    assert "1.1.0" in r.detail


def test_check_faster_whisper_fail_when_missing() -> None:
    from tube_scout.cli.doctor import _FAIL, _check_faster_whisper

    with patch.dict(sys.modules, {"faster_whisper": None}):
        r = _check_faster_whisper()

    assert r.status == _FAIL
    assert "uv sync" in r.detail


# ---------------------------------------------------------------------------
# _check_ld_library_path
# ---------------------------------------------------------------------------

def test_check_ld_library_path_pass_with_cuda() -> None:
    from tube_scout.cli.doctor import _PASS, _check_ld_library_path

    env = {"LD_LIBRARY_PATH": "/nix/store/abc-cudnn/lib:/usr/lib"}
    with patch.dict(os.environ, env, clear=False):
        r = _check_ld_library_path()

    assert r.status == _PASS


def test_check_ld_library_path_warn_when_unset() -> None:
    from tube_scout.cli.doctor import _WARN, _check_ld_library_path

    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    with patch.dict(os.environ, env, clear=True):
        r = _check_ld_library_path()

    assert r.status == _WARN
    assert "(unset)" in r.detail


# ---------------------------------------------------------------------------
# _check_which (fpcalc proxy)
# ---------------------------------------------------------------------------

def test_check_which_pass_when_found() -> None:
    from tube_scout.cli.doctor import _PASS, _check_which

    with patch("shutil.which", return_value="/usr/bin/fpcalc"):
        r = _check_which("fpcalc")

    assert r.status == _PASS
    assert "/usr/bin/fpcalc" in r.detail


def test_check_which_fail_when_missing() -> None:
    from tube_scout.cli.doctor import _FAIL, _check_which

    with patch("shutil.which", return_value=None):
        r = _check_which("fpcalc")

    assert r.status == _FAIL


# ---------------------------------------------------------------------------
# _check_nvidia_smi
# ---------------------------------------------------------------------------

def test_check_nvidia_smi_warn_when_absent() -> None:
    from tube_scout.cli.doctor import _WARN, _check_nvidia_smi

    with patch("shutil.which", return_value=None):
        r = _check_nvidia_smi()

    assert r.status == _WARN


# ---------------------------------------------------------------------------
# _check_sqlite_version
# ---------------------------------------------------------------------------

def test_check_sqlite_version_pass_for_modern() -> None:
    import sqlite3

    from tube_scout.cli.doctor import _PASS, _check_sqlite_version

    with patch.object(sqlite3, "sqlite_version_info", (3, 35, 0)):
        r = _check_sqlite_version()

    assert r.status == _PASS


def test_check_sqlite_version_fail_for_old() -> None:
    import sqlite3

    from tube_scout.cli.doctor import _FAIL, _check_sqlite_version

    with patch.object(sqlite3, "sqlite_version_info", (3, 34, 9)):
        r = _check_sqlite_version()

    assert r.status == _FAIL
    assert "3.35.0" in r.detail


# ---------------------------------------------------------------------------
# doctor_command --exit-code behaviour
# ---------------------------------------------------------------------------

def test_doctor_exit_code_raises_on_fail() -> None:
    """--exit-code must cause SystemExit(1) when at least one check is FAIL."""
    from tube_scout.cli.doctor import _FAIL, _CheckResult, doctor_command

    failing = [_CheckResult("x", _FAIL, "broken")]
    with patch("tube_scout.cli.doctor._run_checks", return_value=failing), \
         pytest.raises(SystemExit) as exc_info:
        doctor_command(verbose=False, exit_code=True)

    assert exc_info.value.code == 1


def test_doctor_no_exit_code_does_not_raise() -> None:
    """Without --exit-code, doctor must not raise even when a check is FAIL."""
    from tube_scout.cli.doctor import _FAIL, _CheckResult, doctor_command

    failing = [_CheckResult("x", _FAIL, "broken")]
    with patch("tube_scout.cli.doctor._run_checks", return_value=failing):
        doctor_command(verbose=False, exit_code=False)   # must not raise


# ---------------------------------------------------------------------------
# main.app registration
# ---------------------------------------------------------------------------

def test_doctor_registered_in_main_app() -> None:
    """'doctor' must be registered as a top-level command in main.app (F-12)."""
    from tube_scout.cli.main import app

    command_names = {cmd.name for cmd in app.registered_commands}
    assert "doctor" in command_names, (
        f"F-12: 'doctor' must be in main.app; found: {command_names}"
    )
