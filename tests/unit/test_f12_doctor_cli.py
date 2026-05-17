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
# _check_ld_library_path — F-12 followup (2026-05-17 audit v3 incident)
#
# Behavior contract (replaces the older "keyword match → PASS" test):
#   * PASS  iff *all 4* target shared libs are present somewhere in
#           LD_LIBRARY_PATH directories.
#   * WARN  iff some but not all target libs are present (partial).
#   * FAIL  iff none of the 4 are present even though cuda-named store
#           paths are listed — the exact F-1 multi-output false-PASS
#           scenario where default ``out`` had only LICENSE.
#   * WARN  iff LD_LIBRARY_PATH is unset (unchanged).
#   * verbose_detail must always describe which libs are missing and
#           which listed cuda paths are empty (no .so files at all).
#
# Targets (faster-whisper / CTranslate2 GPU dlopen set, from flake.nix
# comment block, 2026-05-17):
#   libcudnn.so.9 / libnvrtc.so.12 / libcublas.so.12 / libcudart.so.12
# ---------------------------------------------------------------------------

_F12_TARGET_LIBS = (
    "libcudnn.so.9",
    "libnvrtc.so.12",
    "libcublas.so.12",
    "libcudart.so.12",
)


def _make_cuda_dir(tmp_path, name: str, libs: tuple[str, ...]) -> str:
    """Create a fake cuda store-path directory with the given .so stubs."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    # Mimic the F-1 multi-output trap: always drop a LICENSE so a "lib dir"
    # without .so files looks superficially valid.
    (d / "LICENSE").write_text("license stub")
    for lib in libs:
        (d / lib).write_bytes(b"\x7fELF stub")
    return str(d)


def test_check_ld_library_path_pass_when_all_four_libs_present(tmp_path) -> None:
    """PASS iff all 4 target CUDA libs are resolvable in LD_LIBRARY_PATH."""
    from tube_scout.cli.doctor import _PASS, _check_ld_library_path

    cudnn = _make_cuda_dir(tmp_path, "abc-cudnn-lib", ("libcudnn.so.9",))
    nvrtc = _make_cuda_dir(tmp_path, "def-cuda_nvrtc-lib", ("libnvrtc.so.12",))
    cublas = _make_cuda_dir(
        tmp_path, "ghi-libcublas-lib",
        ("libcublas.so.12", "libcublasLt.so.12"),
    )
    cudart = _make_cuda_dir(tmp_path, "jkl-cuda_cudart-lib", ("libcudart.so.12",))
    ld = ":".join([cudnn, nvrtc, cublas, cudart, "/usr/lib"])

    with patch.dict(os.environ, {"LD_LIBRARY_PATH": ld}, clear=False):
        r = _check_ld_library_path()

    assert r.status == _PASS, r
    # verbose_detail still useful: confirms which libs were located
    for lib in _F12_TARGET_LIBS:
        assert lib in r.verbose_detail


def test_check_ld_library_path_warn_when_partial_libs(tmp_path) -> None:
    """WARN iff some but not all 4 CUDA libs resolve (partial breakage)."""
    from tube_scout.cli.doctor import _WARN, _check_ld_library_path

    cudnn = _make_cuda_dir(tmp_path, "abc-cudnn-lib", ("libcudnn.so.9",))
    nvrtc = _make_cuda_dir(tmp_path, "def-cuda_nvrtc-lib", ("libnvrtc.so.12",))
    # libcublas + libcudart intentionally missing (mimic partial GC)
    cublas_empty = _make_cuda_dir(tmp_path, "ghi-libcublas-empty", ())
    ld = ":".join([cudnn, nvrtc, cublas_empty])

    with patch.dict(os.environ, {"LD_LIBRARY_PATH": ld}, clear=False):
        r = _check_ld_library_path()

    assert r.status == _WARN, r
    assert "libcublas.so.12" in r.verbose_detail
    assert "libcudart.so.12" in r.verbose_detail


def test_check_ld_library_path_fail_on_f1_multi_output_trap(tmp_path) -> None:
    """FAIL when cuda-named paths exist but contain zero target .so files.

    Reproduces the exact F-1 audit v3 incident: gpuLibPath pointed to
    multi-output derivations' default ``out`` which held only LICENSE,
    so doctor reported PASS while libcublas.so.12 was nowhere reachable.
    """
    from tube_scout.cli.doctor import _FAIL, _check_ld_library_path

    cudnn = _make_cuda_dir(tmp_path, "abc-cudnn-empty", ())
    nvrtc = _make_cuda_dir(tmp_path, "def-cuda_nvrtc-empty", ())
    cublas = _make_cuda_dir(tmp_path, "ghi-libcublas-empty", ())
    cudart = _make_cuda_dir(tmp_path, "jkl-cuda_cudart-empty", ())
    ld = ":".join([cudnn, nvrtc, cublas, cudart])

    with patch.dict(os.environ, {"LD_LIBRARY_PATH": ld}, clear=False):
        r = _check_ld_library_path()

    assert r.status == _FAIL, r
    # All 4 must be reported missing
    for lib in _F12_TARGET_LIBS:
        assert lib in r.verbose_detail


def test_check_ld_library_path_warn_when_unset() -> None:
    from tube_scout.cli.doctor import _WARN, _check_ld_library_path

    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    with patch.dict(os.environ, env, clear=True):
        r = _check_ld_library_path()

    assert r.status == _WARN
    assert "(unset)" in r.detail


def test_check_ld_library_path_verbose_lists_empty_cuda_paths(tmp_path) -> None:
    """verbose_detail must surface cuda-named paths that hold zero .so files."""
    from tube_scout.cli.doctor import _check_ld_library_path

    cudnn = _make_cuda_dir(tmp_path, "abc-cudnn-lib", ("libcudnn.so.9",))
    empty_cublas = _make_cuda_dir(tmp_path, "ghi-libcublas-empty", ())
    ld = ":".join([cudnn, empty_cublas])

    with patch.dict(os.environ, {"LD_LIBRARY_PATH": ld}, clear=False):
        r = _check_ld_library_path()

    # The empty store path should be named so the operator can act on it
    assert "ghi-libcublas-empty" in r.verbose_detail


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
