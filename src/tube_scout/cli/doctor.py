"""Environment diagnostics command — tube-scout doctor (F-12).

E-2.a/D-1.b/ADV-28/C-4/ADV-9/10: checks Python executable, Nix shell,
faster-whisper import, LD_LIBRARY_PATH CUDA presence, external binaries
(fpcalc, ffmpeg, sqlite3, nvidia-smi), and torch CUDA availability.
"""

from __future__ import annotations

import os
import shutil
import sys

from rich.console import Console
from rich.table import Table

_console = Console()


def _check_import(module: str) -> tuple[bool, str]:
    """Try importing module; return (ok, version_or_error)."""
    try:
        mod = __import__(module)
        ver = getattr(mod, "__version__", "ok")
        return True, str(ver)
    except ImportError as exc:
        return False, str(exc)


def _which_status(cmd: str) -> tuple[bool, str]:
    path = shutil.which(cmd)
    return (True, path) if path else (False, "not found")


def _ok(flag: bool) -> str:
    return "[green]OK[/green]" if flag else "[red]MISSING[/red]"


def doctor_command() -> None:
    """Print environment diagnostics for tube-scout runtime dependencies.

    Checks: Python interpreter, Nix shell, faster-whisper, LD_LIBRARY_PATH
    CUDA entries, external binaries, nvidia-smi, torch CUDA availability.
    Exit code: 0 always (informational only).
    """
    table = Table(title="tube-scout doctor", show_header=True, header_style="bold")
    table.add_column("항목", style="cyan", min_width=28)
    table.add_column("상태", min_width=10)
    table.add_column("세부 정보")

    # E-2.a: Python executable
    table.add_row("Python executable", "[green]OK[/green]", sys.executable)

    # D-1.b: IN_NIX_SHELL
    nix_val = os.environ.get("IN_NIX_SHELL", "")
    nix_ok = bool(nix_val)
    table.add_row(
        "IN_NIX_SHELL",
        "[green]set[/green]" if nix_ok else "[yellow]not set[/yellow]",
        nix_val or "(unset — not running inside nix develop)",
    )

    # ADV-28: faster_whisper import
    fw_ok, fw_detail = _check_import("faster_whisper")
    table.add_row("faster_whisper import", _ok(fw_ok), fw_detail)

    # ADV-28: LD_LIBRARY_PATH cuda grep
    ld = os.environ.get("LD_LIBRARY_PATH", "")
    cuda_in_ld = "cuda" in ld.lower() or "cudnn" in ld.lower() or "nvcuda" in ld.lower()
    ld_display = ld[:120] + "…" if len(ld) > 120 else (ld or "(unset)")
    table.add_row(
        "LD_LIBRARY_PATH (CUDA)",
        "[green]found[/green]" if cuda_in_ld else "[yellow]no cuda entry[/yellow]",
        ld_display,
    )

    # C-4: which fpcalc, ffmpeg, sqlite3
    for cmd in ("fpcalc", "ffmpeg", "sqlite3"):
        ok, detail = _which_status(cmd)
        table.add_row(f"which {cmd}", _ok(ok), detail)

    # ADV-9/10: nvidia-smi
    nv_ok, nv_detail = _which_status("nvidia-smi")
    table.add_row("which nvidia-smi", _ok(nv_ok), nv_detail)

    # ADV-9/10: torch.cuda.is_available
    try:
        import torch  # type: ignore[import-untyped]
        cuda_available = torch.cuda.is_available()
        device_count = torch.cuda.device_count() if cuda_available else 0
        torch_detail = (
            f"available — {device_count} device(s)" if cuda_available else "not available"
        )
        table.add_row(
            "torch.cuda.is_available",
            "[green]yes[/green]" if cuda_available else "[yellow]no[/yellow]",
            torch_detail,
        )
    except ImportError:
        table.add_row("torch.cuda.is_available", "[yellow]skip[/yellow]", "torch not installed")

    _console.print(table)
