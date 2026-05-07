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
            raise ValueError("UserFacingError.next_command must be a non-empty string")
        self.message = message
        self.next_command = next_command
        super().__init__(message)


class LegacyTokenChannelMismatch(UserFacingError):
    """Legacy token channel_id does not match any registered alias.

    Args:
        channel_id: The channel_id embedded in the legacy token.
        token_path: Filesystem path of the legacy token file.
    """

    def __init__(self, *, channel_id: str, token_path: str) -> None:
        super().__init__(
            message=(
                f"Legacy token at '{token_path}' carries channel_id '{channel_id}'"
                " which is not registered as any alias. The file has been deleted."
            ),
            next_command="tube-scout auth --channel <name>",
        )


class LegacyTokenCorrupt(UserFacingError):
    """Legacy token file could not be parsed (corrupt or empty).

    Args:
        token_path: Filesystem path of the legacy token file.
        reason: Short description of the parse failure.
    """

    def __init__(self, *, token_path: str, reason: str) -> None:
        super().__init__(
            message=(
                f"Legacy token at '{token_path}' is corrupt and cannot be migrated"
                f" ({reason}). The file has been deleted."
            ),
            next_command="tube-scout auth --channel <name>",
        )


class MultipleAliasesNoSelection(UserFacingError):
    """Multiple aliases registered but no --channel flag provided.

    Args:
        aliases: List of currently registered alias names.
    """

    def __init__(self, *, aliases: list[str]) -> None:
        alias_list = ", ".join(aliases)
        first = aliases[0] if aliases else "<alias>"
        super().__init__(
            message=(
                f"Multiple channel aliases registered ({alias_list})."
                " Specify one with --channel."
            ),
            next_command=f"tube-scout collect <subcommand> --channel {first}",
        )


class NoAliasRegistered(UserFacingError):
    """No channel aliases are registered yet."""

    def __init__(self) -> None:
        super().__init__(
            message="No channel aliases are registered.",
            next_command="tube-scout auth --channel <name>",
        )


class ClientTypeNotSupportedForDeviceFlow(UserFacingError):
    """OAuth client type does not support device-code flow (HTTP 401 invalid_client).

    Google returns 401 invalid_client when the OAuth client is a "Desktop app"
    rather than a "TVs and Limited Input devices" type. Fall back to
    browser-redirect flow, or re-create the client in Google Cloud Console.

    Args:
        alias: The channel alias for which auth was attempted.
    """

    def __init__(self, *, alias: str) -> None:
        super().__init__(
            message=(
                f"Device-code flow for '{alias}' failed: the OAuth client type"
                " does not support device authorization (invalid_client). In"
                " production, create a 'TVs and Limited Input devices' OAuth"
                " client in Google Cloud Console. Falling back to"
                " browser-redirect flow."
            ),
            next_command=f"tube-scout auth --channel {alias} --browser-redirect",
        )


class DeviceCodeTimeout(UserFacingError):
    """Device-code flow polling timed out before operator confirmed.

    Args:
        alias: The channel alias for which auth was attempted.
    """

    def __init__(self, *, alias: str) -> None:
        super().__init__(
            message=(
                f"Device-code authorization for '{alias}' timed out."
                " No partial token has been written."
            ),
            next_command=f"tube-scout auth --channel {alias}",
        )


class DeviceCodeAccessDenied(UserFacingError):
    """Device-code flow was denied by the operator.

    Args:
        alias: The channel alias for which auth was attempted.
    """

    def __init__(self, *, alias: str) -> None:
        super().__init__(
            message=f"Device-code authorization for '{alias}' was denied.",
            next_command=f"tube-scout auth --channel {alias}",
        )


class LatestProjectMissing(UserFacingError):
    """No 'latest' project exists when a consumer command needs one."""

    def __init__(self) -> None:
        super().__init__(
            message=(
                "No 'latest' project found. Run 'collect videos' first"
                " to create a project."
            ),
            next_command="tube-scout collect videos --channel <alias>",
        )


class ProducerCommandRequiresChannel(UserFacingError):
    """A producer command was invoked without a resolvable channel alias.

    Args:
        command: The CLI command string that requires a channel.
    """

    def __init__(self, *, command: str) -> None:
        super().__init__(
            message=f"'{command}' requires a channel alias.",
            next_command=f"tube-scout {command} --channel <alias>",
        )


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
