"""RED tests for F-12: doctor CLI module (E-2.a/D-1.b/ADV-28/C-4/ADV-9/10).

tube-scout doctor 명령: 환경 진단 체크리스트 출력.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# doctor_command importable from cli.doctor
# ---------------------------------------------------------------------------

def test_doctor_command_importable() -> None:
    """doctor_command must be importable from tube_scout.cli.doctor (F-12 API)."""
    from tube_scout.cli.doctor import doctor_command  # noqa: F401


# ---------------------------------------------------------------------------
# E-2.a: sys.executable path reported
# ---------------------------------------------------------------------------

def test_doctor_reports_python_executable(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """doctor must print Python executable row (E-2.a)."""
    from tube_scout.cli.doctor import doctor_command

    with patch("shutil.which", return_value=None):
        doctor_command()

    captured = capsys.readouterr()
    # Rich may truncate long paths; check for the row label instead
    assert "Python executable" in captured.out, (
        f"E-2.a: 'Python executable' row must appear in doctor output; got:\n{captured.out}"
    )


# ---------------------------------------------------------------------------
# D-1.b: IN_NIX_SHELL detection reported
# ---------------------------------------------------------------------------

def test_doctor_reports_nix_shell_present(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """doctor must report IN_NIX_SHELL=1 when env var is set (D-1.b)."""
    from tube_scout.cli.doctor import doctor_command
    import os

    with patch.dict(os.environ, {"IN_NIX_SHELL": "1"}), patch("shutil.which", return_value=None):
        doctor_command()

    captured = capsys.readouterr()
    assert "IN_NIX_SHELL" in captured.out or "nix" in captured.out.lower(), (
        f"D-1.b: IN_NIX_SHELL must appear in doctor output; got:\n{captured.out}"
    )


# ---------------------------------------------------------------------------
# ADV-28: faster_whisper import check reported
# ---------------------------------------------------------------------------

def test_doctor_reports_faster_whisper_importable(capsys: pytest.CaptureFixture) -> None:
    """doctor must check faster_whisper import and report result (ADV-28)."""
    from tube_scout.cli.doctor import doctor_command

    with patch("shutil.which", return_value=None):
        doctor_command()

    captured = capsys.readouterr()
    assert "faster" in captured.out.lower() or "whisper" in captured.out.lower(), (
        f"ADV-28: faster_whisper check must appear in doctor output; got:\n{captured.out}"
    )


# ---------------------------------------------------------------------------
# C-4: which(fpcalc) and which(ffmpeg) reported
# ---------------------------------------------------------------------------

def test_doctor_reports_fpcalc_found(capsys: pytest.CaptureFixture) -> None:
    """doctor must report fpcalc path when found (C-4)."""
    from tube_scout.cli.doctor import doctor_command

    def _fake_which(cmd: str) -> str | None:
        return f"/usr/bin/{cmd}" if cmd in ("fpcalc", "ffmpeg") else None

    with patch("shutil.which", side_effect=_fake_which):
        doctor_command()

    captured = capsys.readouterr()
    assert "fpcalc" in captured.out, (
        f"C-4: fpcalc must appear in doctor output; got:\n{captured.out}"
    )
    assert "ffmpeg" in captured.out, (
        f"C-4: ffmpeg must appear in doctor output; got:\n{captured.out}"
    )


def test_doctor_reports_fpcalc_missing(capsys: pytest.CaptureFixture) -> None:
    """doctor must report fpcalc MISSING when not found (C-4)."""
    from tube_scout.cli.doctor import doctor_command

    with patch("shutil.which", return_value=None):
        doctor_command()

    captured = capsys.readouterr()
    assert "fpcalc" in captured.out, (
        f"C-4: fpcalc must appear in doctor output even when missing; got:\n{captured.out}"
    )


# ---------------------------------------------------------------------------
# ADV-9/10: nvidia-smi and torch.cuda.is_available reported
# ---------------------------------------------------------------------------

def test_doctor_reports_nvidia_smi(capsys: pytest.CaptureFixture) -> None:
    """doctor must check nvidia-smi and report result (ADV-9/10)."""
    from tube_scout.cli.doctor import doctor_command

    def _fake_which(cmd: str) -> str | None:
        return "/usr/bin/nvidia-smi" if cmd == "nvidia-smi" else None

    with patch("shutil.which", side_effect=_fake_which):
        doctor_command()

    captured = capsys.readouterr()
    assert "nvidia" in captured.out.lower() or "gpu" in captured.out.lower(), (
        f"ADV-9/10: nvidia-smi check must appear in output; got:\n{captured.out}"
    )


# ---------------------------------------------------------------------------
# ADV-28: LD_LIBRARY_PATH cuda grep reported
# ---------------------------------------------------------------------------

def test_doctor_reports_ld_library_path(capsys: pytest.CaptureFixture) -> None:
    """doctor must report LD_LIBRARY_PATH and whether cuda appears in it (ADV-28)."""
    from tube_scout.cli.doctor import doctor_command
    import os

    with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/nix/store/abc-cudnn/lib:/usr/lib"}), \
         patch("shutil.which", return_value=None):
        doctor_command()

    captured = capsys.readouterr()
    assert "LD_LIBRARY_PATH" in captured.out or "cuda" in captured.out.lower(), (
        f"ADV-28: LD_LIBRARY_PATH must appear in doctor output; got:\n{captured.out}"
    )


# ---------------------------------------------------------------------------
# doctor registered as top-level app command in main.py
# ---------------------------------------------------------------------------

def test_doctor_registered_in_main_app() -> None:
    """'doctor' must be registered as a top-level command in main.app (F-12 registration)."""
    from tube_scout.cli.main import app

    command_names = {cmd.name for cmd in app.registered_commands}
    assert "doctor" in command_names, (
        f"F-12: 'doctor' must be registered in main.app; found: {command_names}"
    )
