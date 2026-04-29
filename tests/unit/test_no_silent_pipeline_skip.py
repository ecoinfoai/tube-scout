"""RED + GREEN: silent-skip lint guard (SILENT-1..15).

Spec: idea6 / FR-IDEA6-010 / ADR-IDEA6-007 + ADR-IDEA6-003 / T-IDEA6-H1.

Per phase2_architect_design ADR-IDEA6-008 (No Silent Pipeline Skip,
preserved as cross-cutting cleanup of ADR-007 + ADR-003) the
following patterns MUST be absent from ``src/tube_scout/cli/``:

1. ``except SystemExit:`` followed by ``pass`` or by a status="completed"
   StageResult (Tier 1 + Tier 3).
2. ``except SystemExit`` literal anywhere — caller should catch a
   specific UserFacingError sub-class instead of swallowing exit codes.
3. Path-missing silent return like ``if not <path>.exists(): return []``
   inside CLI orchestrators (Tier 2).

This file is the canonical regression gate for SC-1 acceptance
reinforcement.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

CLI_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "tube_scout" / "cli"
)


def _cli_python_files() -> list[Path]:
    return sorted(p for p in CLI_DIR.rglob("*.py") if p.name != "__init__.py")


def test_grep_no_except_systemexit() -> None:
    """Tier 1 lint: ``grep -rn 'except SystemExit'`` over cli/* == 0."""
    proc = subprocess.run(
        ["grep", "-rn", "except SystemExit", str(CLI_DIR)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0, (
        "Found `except SystemExit` in src/tube_scout/cli/ "
        "(Tier 1 silent-skip lint guard). Output:\n" + proc.stdout
    )


def test_ast_no_except_systemexit_pass() -> None:
    """Tier 1 ast: handler body == [Pass] for SystemExit is forbidden."""
    violations: list[str] = []
    for path in _cli_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    if (
                        h.type is not None
                        and isinstance(h.type, ast.Name)
                        and h.type.id == "SystemExit"
                        and len(h.body) == 1
                        and isinstance(h.body[0], ast.Pass)
                    ):
                        violations.append(f"{path}:{h.lineno}")
    assert not violations, (
        "Silent `except SystemExit: pass` found:\n  " + "\n  ".join(violations)
    )


def test_ast_no_systemexit_followed_by_status_completed() -> None:
    """Tier 3 ast: ``except SystemExit`` body assigning status="completed"."""
    pattern = re.compile(
        r"except\s+SystemExit[^:]*:\s*\n([^\n]*\n){0,5}.*status\s*=\s*[\"'](completed|success|ok)[\"']",
        re.MULTILINE,
    )
    violations: list[str] = []
    for path in _cli_python_files():
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            violations.append(str(path))
    assert not violations, (
        "Tier 3 false-success persistence (status=completed inside "
        "except SystemExit) found in:\n  " + "\n  ".join(violations)
    )
