"""Environment diagnostics command — tube-scout doctor (F-12).

E-2.a/D-1.b/ADV-28/C-4/ADV-9/10/ADV-31: checks Python interpreter, Nix devShell,
faster-whisper import, LD_LIBRARY_PATH CUDA presence, external binaries,
GPU visibility, and sqlite3 version baseline.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from typing import NamedTuple

import typer
from rich.console import Console
from rich.table import Table

_console = Console()

_PASS = "[green]PASS[/green]"
_WARN = "[yellow]WARN[/yellow]"
_FAIL = "[red]FAIL[/red]"


class _CheckResult(NamedTuple):
    label: str
    status: str  # _PASS / _WARN / _FAIL
    detail: str
    verbose_detail: str = ""  # shown only with --verbose


def _check_python() -> _CheckResult:
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return _CheckResult(
        "Python interpreter",
        _PASS,
        f"{ver} — {sys.executable}",
    )


def _check_nix_shell() -> _CheckResult:
    nix_val = os.environ.get("IN_NIX_SHELL", "")
    profile = os.environ.get("NIX_DEVELOP_PROFILE", "")
    if nix_val:
        detail = f"IN_NIX_SHELL={nix_val!r}"
        if profile:
            detail += f", NIX_DEVELOP_PROFILE={profile[:60]}"
        return _CheckResult("devShell (Nix)", _PASS, detail)
    return _CheckResult(
        "devShell (Nix)",
        _WARN,
        "IN_NIX_SHELL not set — run inside 'nix develop'",
    )


def _check_faster_whisper() -> _CheckResult:
    try:
        import faster_whisper  # type: ignore[import-untyped]  # noqa: F401

        ver = getattr(faster_whisper, "__version__", "unknown")
        return _CheckResult("faster_whisper import", _PASS, f"v{ver}")
    except ImportError as exc:
        return _CheckResult(
            "faster_whisper import",
            _FAIL,
            "ImportError — uv sync --extra asr",
            str(exc),
        )


# F-12 followup (2026-05-17 audit v3 incident): the 4 shared libraries
# faster-whisper / CTranslate2 dlopen at first GPU model load. Each MUST
# resolve via LD_LIBRARY_PATH or the process raises a generic
# RuntimeError. Keep this list in sync with the flake.nix gpuLibPath
# comment block.
_F12_TARGET_CUDA_LIBS: tuple[str, ...] = (
    "libcudnn.so.9",
    "libnvrtc.so.12",
    "libcublas.so.12",
    "libcudart.so.12",
)

_F12_CUDA_KEYWORDS: tuple[str, ...] = (
    "cuda",
    "cudnn",
    "cublas",
    "cudart",
    "nvcuda",
)


def _check_ld_library_path() -> _CheckResult:
    ld = os.environ.get("LD_LIBRARY_PATH", "")
    if not ld:
        return _CheckResult(
            "LD_LIBRARY_PATH (CUDA)",
            _WARN,
            "(unset)",
            "",
        )

    cuda_paths = [
        p
        for p in ld.split(":")
        if p and any(k in p.lower() for k in _F12_CUDA_KEYWORDS)
    ]
    if not cuda_paths:
        return _CheckResult(
            "LD_LIBRARY_PATH (CUDA)",
            _WARN,
            "set but no cuda/cudnn/cublas entry found",
            ld[:200],
        )

    # F-1 follow-up: keyword match alone is the false-PASS trap. Verify
    # that each target .so actually exists somewhere in cuda_paths.
    found: dict[str, str] = {}
    missing: list[str] = []
    for lib in _F12_TARGET_CUDA_LIBS:
        hit = next(
            (p for p in cuda_paths if os.path.isfile(os.path.join(p, lib))),
            None,
        )
        if hit is not None:
            found[lib] = hit
        else:
            missing.append(lib)

    empty_paths = [
        p
        for p in cuda_paths
        if not any(
            os.path.isfile(os.path.join(p, lib)) for lib in _F12_TARGET_CUDA_LIBS
        )
    ]

    total = len(_F12_TARGET_CUDA_LIBS)
    found_count = len(found)
    summary = f"{found_count}/{total} CUDA libs resolvable"
    if missing:
        summary += f" (missing: {', '.join(missing)})"

    verbose_parts = [
        "found: " + (", ".join(sorted(found)) if found else "(none)"),
    ]
    if missing:
        verbose_parts.append("missing: " + ", ".join(missing))
    if empty_paths:
        verbose_parts.append("empty cuda paths: " + ", ".join(empty_paths))
    verbose_detail = " | ".join(verbose_parts)

    if found_count == total:
        status = _PASS
    elif found_count == 0:
        status = _FAIL
    else:
        status = _WARN

    return _CheckResult(
        "LD_LIBRARY_PATH (CUDA)",
        status,
        summary,
        verbose_detail,
    )


def _check_which(cmd: str) -> _CheckResult:
    path = shutil.which(cmd)
    if path:
        return _CheckResult(f"which {cmd}", _PASS, path)
    return _CheckResult(f"which {cmd}", _FAIL, "not found — install via nix/system")


def _check_nvidia_smi(*, verbose: bool = False) -> _CheckResult:
    path = shutil.which("nvidia-smi")
    if not path:
        return _CheckResult("nvidia-smi", _WARN, "not found — GPU may be absent")
    if verbose:
        import subprocess

        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            first_line = (
                out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
            )
            return _CheckResult("nvidia-smi", _PASS, path, first_line)
        except Exception as exc:
            return _CheckResult("nvidia-smi", _WARN, path, f"query failed: {exc}")
    return _CheckResult("nvidia-smi", _PASS, path)


def _check_torch_cuda() -> _CheckResult:
    try:
        import torch  # type: ignore[import-untyped]

        avail = torch.cuda.is_available()
        count = torch.cuda.device_count() if avail else 0
        if avail:
            return _CheckResult(
                "torch.cuda.is_available",
                _PASS,
                f"True — {count} device(s)",
            )
        return _CheckResult(
            "torch.cuda.is_available",
            _WARN,
            "False — no CUDA device visible to torch",
        )
    except ImportError:
        return _CheckResult(
            "torch.cuda.is_available",
            _WARN,
            "torch not installed (uv sync --extra ml-sentiment or asr)",
        )


def _check_sqlite_version() -> _CheckResult:
    vi = sqlite3.sqlite_version_info
    ver_str = ".".join(str(x) for x in vi)
    if vi >= (3, 35, 0):
        return _CheckResult("sqlite3 version", _PASS, ver_str)
    return _CheckResult(
        "sqlite3 version",
        _FAIL,
        f"{ver_str} — ≥3.35.0 required (RETURNING clause, F-18 baseline)",
    )


def _run_checks(*, verbose: bool) -> list[_CheckResult]:
    return [
        _check_python(),
        _check_nix_shell(),
        _check_faster_whisper(),
        _check_ld_library_path(),
        _check_which("fpcalc"),
        _check_which("ffmpeg"),
        _check_which("sqlite3"),
        _check_nvidia_smi(verbose=verbose),
        _check_torch_cuda(),
        _check_sqlite_version(),
    ]


def doctor_command(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show raw output for each check."
    ),
    exit_code: bool = typer.Option(
        False,
        "--exit-code",
        help="Exit 1 if any check is FAIL (default: always exit 0).",
    ),
) -> None:
    """Print environment diagnostics for tube-scout runtime dependencies.

    Checks Python interpreter, Nix devShell, faster-whisper, LD_LIBRARY_PATH CUDA,
    external binaries (fpcalc/ffmpeg/sqlite3/nvidia-smi), torch CUDA, sqlite3 version.
    """
    results = _run_checks(verbose=verbose)

    table = Table(title="tube-scout doctor", show_header=True, header_style="bold")
    table.add_column("항목", style="cyan", min_width=28)
    table.add_column("상태", min_width=8)
    table.add_column("세부 정보")
    if verbose:
        table.add_column("raw")

    any_fail = False
    for r in results:
        if "FAIL" in r.status:
            any_fail = True
        if verbose:
            table.add_row(r.label, r.status, r.detail, r.verbose_detail)
        else:
            table.add_row(r.label, r.status, r.detail)

    _console.print(table)

    if exit_code and any_fail:
        raise SystemExit(1)
