"""RED then GREEN: tests/manual is excluded from default pytest collection.

Spec: idea6 / FR-IDEA6-009 / SC-7 / T-IDEA6-I1.

The default ``pytest tests/`` invocation MUST NOT collect any test
case from ``tests/manual/`` (they require live OAuth credentials and
break CI). Operators opt-in with ``pytest --run-manual tests/manual/``.

This is exercised via subprocess so we observe the actual collection
behaviour rather than fixture mocking.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_collection_excludes_manual() -> None:
    """``pytest --collect-only tests/`` does not list any manual test."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout + proc.stderr
    assert "tests/manual/" not in output, (
        "tests/manual/* was collected by the default suite; expected exclusion. "
        f"output:\n{output}"
    )


def test_run_manual_opt_in_collects_manual_dir() -> None:
    """``pytest --run-manual tests/manual/`` opts back in to manual tests."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--run-manual",
            "--collect-only",
            "-q",
            "tests/manual/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout + proc.stderr
    assert "tests/manual/" in output, (
        "Expected --run-manual to collect tests/manual; got:\n" + output
    )
