"""Actionable user-facing error class + renderer.

idea6 ADR-IDEA6-007: every operator-visible failure path raises
``UserFacingError`` carrying a ``next_command`` hint. The CLI wrapper
renders the exception via ``render_error`` and then propagates a
non-zero exit. Sub-classes (``TokenScopeError``,
``ScopeReauthRequired``, ``InteractiveAuthRequired``,
``SecretConfigError``, ``AliasNotFoundError``) inherit the contract so
downstream catch-sites only need to handle the base type.
"""

from __future__ import annotations

import sys
from typing import TextIO


class UserFacingError(Exception):
    """An error rendered to the operator with a recovery hint.

    Args:
        message: Human-readable description of what went wrong.
        next_command: The exact CLI command the operator should run
            next. MUST be supplied; Constitution II Fail-Fast.
    """

    def __init__(self, *, message: str, next_command: str) -> None:
        if not next_command:
            raise ValueError(
                "UserFacingError.next_command must be a non-empty string"
            )
        self.message = message
        self.next_command = next_command
        super().__init__(message)


def render_error(exc: UserFacingError, stream: TextIO | None = None) -> None:
    """Print an actionable error block to stderr.

    Format:
        Error: <message>
          Try: <next_command>

    Args:
        exc: The error to render. Sub-classes of ``UserFacingError`` work.
        stream: Override the output stream (defaults to ``sys.stderr``).
    """
    out = stream if stream is not None else sys.stderr
    out.write(f"Error: {exc.message}\n")
    out.write(f"  Try: {exc.next_command}\n")
