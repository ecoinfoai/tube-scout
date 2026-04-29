"""RED + GREEN: silent-skip lint guard (SILENT-1..15).

Spec: idea6 / FR-IDEA6-010 / ADR-IDEA6-007 + ADR-IDEA6-003 / T-IDEA6-H1.

Per phase2_architect_design ADR-IDEA6-008 (preserved as cross-cutting
cleanup of ADR-007 + ADR-003) the following patterns MUST be absent
from ``src/tube_scout/cli/``:

1. Tier 1 (silent absorption): ``except SystemExit:`` whose handler
   body is a single ``pass`` (the original SILENT-1..4 shape).
2. Tier 3 (structured-persistence false-success): ``except SystemExit``
   whose handler unconditionally records ``status="completed"`` /
   ``"success"`` / ``"ok"`` (the original H-7 shape). A handler that
   distinguishes ``exc.code != 0`` and only records ``"completed"`` in
   the zero-exit branch is acceptable.
3. (T2 path-missing return): asserted ad-hoc by call-site fix tasks.

This file is the canonical regression gate for the SC-1 acceptance
reinforcement ("pipeline 의 어떤 Step 실패도 silent 흡수되지 않는다").
"""

from __future__ import annotations

import ast
from pathlib import Path

CLI_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "tube_scout" / "cli"
)


def _cli_python_files() -> list[Path]:
    return sorted(p for p in CLI_DIR.rglob("*.py") if p.name != "__init__.py")


def _is_systemexit_handler(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return False
    if isinstance(handler.type, ast.Name) and handler.type.id == "SystemExit":
        return True
    return False


def test_no_systemexit_pass_handler() -> None:
    """Tier 1: ``try/except SystemExit: pass`` is forbidden."""
    violations: list[str] = []
    for path in _cli_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not _is_systemexit_handler(handler):
                    continue
                if len(handler.body) == 1 and isinstance(
                    handler.body[0], ast.Pass
                ):
                    violations.append(f"{path}:{handler.lineno}")
    assert not violations, (
        "Silent `except SystemExit: pass` found:\n  "
        + "\n  ".join(violations)
    )


def _handler_unconditional_completion(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler body unconditionally records status='completed'.

    "Unconditional" means: there is at least one assignment/keyword
    setting ``status`` to a literal completion value, AND there is no
    ``If`` node guarding it. Handlers that branch on ``exc.code`` and
    only record completion in the zero-exit branch are acceptable.
    """
    has_completion_literal = False
    body_has_branching_if = False
    for sub in ast.walk(ast.Module(body=list(handler.body), type_ignores=[])):
        if isinstance(sub, ast.If):
            body_has_branching_if = True
        if isinstance(sub, ast.keyword) and sub.arg == "status":
            if (
                isinstance(sub.value, ast.Constant)
                and isinstance(sub.value.value, str)
                and sub.value.value.lower() in {"completed", "success", "ok"}
            ):
                has_completion_literal = True
    return has_completion_literal and not body_has_branching_if


def test_no_systemexit_unconditional_false_success() -> None:
    """Tier 3: ``except SystemExit`` with unconditional status='completed'."""
    violations: list[str] = []
    for path in _cli_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not _is_systemexit_handler(handler):
                    continue
                if _handler_unconditional_completion(handler):
                    violations.append(f"{path}:{handler.lineno}")
    assert not violations, (
        "Tier 3 false-success persistence (unconditional status=completed in "
        "`except SystemExit` handler):\n  " + "\n  ".join(violations)
    )
