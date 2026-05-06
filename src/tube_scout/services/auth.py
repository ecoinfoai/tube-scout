"""OAuth2 authentication for YouTube Analytics API.

Supports both single-channel (legacy) and multi-channel token management.
"""

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from tube_scout.models.config import DEFAULT_API_TIMEOUT_SECONDS, ChannelRegistration

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
REQUIRED_SCOPES = frozenset(SCOPES)
TOKEN_FILE = "token.json"

_ALIAS_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")


def _validate_alias(alias: str) -> None:
    """Raise UserFacingError if alias is unsafe for use as a filesystem path component.

    Allowed charset: ASCII alphanumeric, hyphens, underscores; 1–32 chars;
    must not start with a hyphen or dot. Rejects path-traversal sequences,
    null bytes, non-ASCII, and leading special characters.

    Args:
        alias: The channel alias string to validate.

    Raises:
        UserFacingError: If alias contains unsafe characters or fails length check.
    """
    from tube_scout.cli.errors import UserFacingError

    if not alias or not _ALIAS_RE.match(alias):
        raise UserFacingError(
            message=(
                f"Invalid channel alias {alias!r}. "
                "Aliases must be 1–32 ASCII characters: letters, digits, "
                "hyphens, underscores; must not start with a hyphen."
            ),
            next_command="tube-scout auth --channel <safe-alias>",
        )


class ScopeReauthRequired(Exception):
    """Stored token lacks one or more required OAuth scopes (FR-IDEA6-005).

    Raised when ``_verify_scopes`` finds the credentials missing any
    member of :data:`REQUIRED_SCOPES`. Carries an actionable
    ``next_command`` so the CLI can render it via ``cli.errors.render_error``.
    """

    def __init__(self, alias: str, missing: list[str]) -> None:
        self.alias = alias
        self.missing = missing
        self.message = (
            f"Stored token for '{alias}' is missing required scope(s): "
            + ", ".join(missing)
        )
        self.next_command = (
            f"tube-scout auth --revoke {alias} && "
            f"tube-scout auth --channel {alias}"
        )
        super().__init__(self.message)


class InteractiveAuthRequired(Exception):
    """OAuth flow needs a TTY but stdin is not interactive (NFR-IDEA6-003 / B7).

    Raised by :func:`authenticate` and :func:`register_channel` before
    they would otherwise call ``flow.run_local_server`` and silently
    block forever in a headless / systemd context.
    """

    def __init__(self, alias: str = "default") -> None:
        self.alias = alias
        self.message = (
            f"OAuth flow requires a TTY for channel '{alias}'."
        )
        self.next_command = (
            f"ssh to host and run tube-scout auth --channel {alias}"
        )
        super().__init__(self.message)


def has_required_scopes(creds: Credentials) -> bool:
    """Return True iff ``creds`` carries every scope in REQUIRED_SCOPES.

    Treats both ``creds.scopes`` and the optional ``granted_scopes``
    attribute as authoritative; the union must cover REQUIRED_SCOPES.
    """
    if creds is None:
        return False
    granted: set[str] = set()
    for attr in ("scopes", "granted_scopes"):
        value = getattr(creds, attr, None)
        if value:
            granted.update(value)
    return REQUIRED_SCOPES.issubset(granted)


def _verify_scopes(creds: Credentials, alias: str = "default") -> None:
    """Raise :class:`ScopeReauthRequired` if any required scope is missing."""
    if not has_required_scopes(creds):
        granted: set[str] = set()
        for attr in ("scopes", "granted_scopes"):
            value = getattr(creds, attr, None)
            if value:
                granted.update(value)
        missing = sorted(REQUIRED_SCOPES - granted)
        raise ScopeReauthRequired(alias=alias, missing=missing)


def _require_tty(alias: str = "default") -> None:
    """Raise :class:`InteractiveAuthRequired` if stdin is not a TTY."""
    import sys

    if not sys.stdin.isatty():
        raise InteractiveAuthRequired(alias=alias)


def _secure_write(path: Path, content: str) -> None:
    """Write content to file atomically with 0o600 permissions.

    Args:
        path: Target file path.
        content: String content to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp", prefix=".token_")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp_path, 0o600)
        os.rename(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


def _default_client_secret_path() -> Path:
    """Return path to client secret JSON.

    idea6 ADR-IDEA6-004 (D-4 fix): delegates to
    ``services.secret_loader.resolve_client_secret_path`` which now
    accepts both ``TUBE_SCOUT_CLIENT_SECRET`` (path) and
    ``TUBE_SCOUT_CLIENT_SECRET_B64`` (base64-encoded JSON, decoded to a
    0o600 tmpfile). The thin wrapper preserves the historical
    public name so existing callers keep working.

    Returns:
        Path to the client secret JSON file (real or tmpfs).

    Raises:
        SecretConfigError: A :class:`UserFacingError` sub-class — kept
            distinct from :class:`ValueError` to enable centralised
            actionable rendering at the CLI boundary.
    """
    from tube_scout.services.secret_loader import resolve_client_secret_path

    return resolve_client_secret_path()


def _token_path() -> Path:
    """Return path to cached OAuth token."""
    config_dir = Path.home() / ".config" / "tube-scout"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / TOKEN_FILE


def _tokens_dir() -> Path:
    """Return the tokens directory path.

    Returns:
        Path to tokens directory. Uses TUBE_SCOUT_TOKENS_DIR env var
        if set, otherwise ~/.config/tube-scout/tokens/.
    """
    env_dir = os.environ.get("TUBE_SCOUT_TOKENS_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".config" / "tube-scout" / "tokens"


# ─── Legacy single-channel auth ───


def authenticate() -> Credentials:
    """Authenticate via OAuth2 and return credentials.

    Returns:
        Authenticated Google OAuth2 credentials.

    Raises:
        FileNotFoundError: If client secret file is not found.
    """
    token_path = _token_path()
    creds: Credentials | None = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        _verify_scopes(creds, alias="default")
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        # idea6 NFR-IDEA6-003 §"Headless guard" (B7): refuse to call
        # flow.run_local_server when stdin is not a TTY (e.g. systemd
        # context) because it would silently block on a port no one is
        # connecting to.
        _require_tty(alias="default")
        client_secret = _default_client_secret_path()
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        creds = flow.run_local_server(port=8080)

    _verify_scopes(creds, alias="default")
    _secure_write(token_path, creds.to_json())
    return creds


def _authorized_http(creds: Credentials) -> AuthorizedHttp:
    """Create an AuthorizedHttp transport with default timeout.

    Args:
        creds: Authenticated Google OAuth2 credentials.

    Returns:
        AuthorizedHttp with timeout configured.
    """
    http = httplib2.Http(timeout=DEFAULT_API_TIMEOUT_SECONDS)
    return AuthorizedHttp(creds, http=http)


def build_data_client() -> Any:
    """Build and return an authenticated YouTube Data API client.

    Returns:
        YouTube Data API v3 client resource (with OAuth, can access unlisted videos).
    """
    creds = authenticate()
    return build("youtube", "v3", http=_authorized_http(creds))


def build_analytics_client() -> Any:
    """Build and return an authenticated YouTube Analytics API client.

    Returns:
        YouTube Analytics API client resource.
    """
    creds = authenticate()
    return build("youtubeAnalytics", "v2", http=_authorized_http(creds))


def build_reporting_client() -> Any:
    """Build and return an authenticated YouTube Reporting API client.

    Returns:
        YouTube Reporting API v1 client resource.
    """
    creds = authenticate()
    return build("youtubereporting", "v1", http=_authorized_http(creds))


# ─── Multi-channel registry management ───


def load_registry(tokens_path: Path | None = None) -> dict[str, ChannelRegistration]:
    """Load channel registry from channels.json.

    Args:
        tokens_path: Path to tokens directory. Defaults to _tokens_dir().

    Returns:
        Dictionary mapping alias to ChannelRegistration.

    Raises:
        json.JSONDecodeError: If channels.json is corrupt.
    """
    tokens_path = tokens_path or _tokens_dir()
    tokens_path.mkdir(parents=True, exist_ok=True)
    channels_file = tokens_path / "channels.json"
    if not channels_file.exists():
        return {}

    raw = channels_file.read_text(encoding="utf-8")
    data = json.loads(raw)
    return {alias: ChannelRegistration(**entry) for alias, entry in data.items()}


def save_registry(
    tokens_path: Path | None,
    registry: dict[str, ChannelRegistration],
) -> None:
    """Save channel registry to channels.json.

    Args:
        tokens_path: Path to tokens directory. Defaults to _tokens_dir().
        registry: Dictionary mapping alias to ChannelRegistration.
    """
    tokens_path = tokens_path or _tokens_dir()
    tokens_path.mkdir(parents=True, exist_ok=True)
    channels_file = tokens_path / "channels.json"
    data = {alias: reg.model_dump() for alias, reg in registry.items()}
    _secure_write(
        channels_file,
        json.dumps(data, ensure_ascii=False, indent=2),
    )


def update_last_used(tokens_path: Path | None, alias: str) -> None:
    """Update the last_used_at timestamp for a channel.

    Args:
        tokens_path: Path to tokens directory. Defaults to _tokens_dir().
        alias: Channel alias to update.

    Raises:
        KeyError: If alias is not registered.
    """
    _validate_alias(alias)
    tokens_path = tokens_path or _tokens_dir()
    registry = load_registry(tokens_path)
    if alias not in registry:
        raise KeyError(f"Channel '{alias}' is not registered")
    registry[alias].last_used_at = datetime.now(UTC).isoformat()
    save_registry(tokens_path, registry)


# ─── Multi-channel auth operations ───


def list_channels() -> list[ChannelRegistration]:
    """List all registered channels.

    Returns:
        List of ChannelRegistration objects.
    """
    registry = load_registry(_tokens_dir())
    return list(registry.values())


def authenticate_channel(alias: str) -> Credentials:
    """Authenticate using a stored per-channel token.

    Args:
        alias: Channel alias to authenticate.

    Returns:
        Authenticated Google OAuth2 credentials.

    Raises:
        KeyError: If alias is not registered.
        FileNotFoundError: If token file is missing.
        ValueError: If token is expired and has no refresh_token.
        google.auth.exceptions.RefreshError: If token refresh fails.
    """
    _validate_alias(alias)
    tokens_path = _tokens_dir()
    registry = load_registry(tokens_path)
    if alias not in registry:
        raise KeyError(
            f"Channel '{alias}' is not registered. "
            f"Run 'tube-scout auth --channel {alias}' first."
        )

    reg = registry[alias]
    token_file = Path(reg.token_path)
    if not token_file.exists():
        raise FileNotFoundError(f"Token file not found for '{alias}': {reg.token_path}")

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if creds.valid:
        _verify_scopes(creds, alias=alias)
        update_last_used(tokens_path, alias)
        return creds

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _verify_scopes(creds, alias=alias)
        _secure_write(token_file, creds.to_json())
        update_last_used(tokens_path, alias)
        return creds

    raise ValueError(
        f"Token for '{alias}' cannot be refreshed. "
        "Please re-authenticate with 'tube-scout auth --channel "
        f"{alias}'."
    )


def register_channel(alias: str) -> ChannelRegistration:
    """Register a new channel via OAuth flow.

    Opens a browser for OAuth login, auto-detects the channel ID via
    channels.list(mine=True), saves the token, and updates the registry.

    Args:
        alias: Human-readable department alias (e.g., "간호학과").

    Returns:
        ChannelRegistration for the newly registered channel.

    Raises:
        FileNotFoundError: If client secret file is not found.
        ValueError: If no channel is found on the authenticated account.
    """
    _validate_alias(alias)
    tokens_path = _tokens_dir()
    tokens_path.mkdir(parents=True, exist_ok=True)

    # idea6 NFR-IDEA6-003 §"Headless guard" (B7): refuse the
    # interactive OAuth flow when stdin is not a TTY (systemd / CI).
    _require_tty(alias=alias)

    # Run OAuth flow
    client_secret = _default_client_secret_path()
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=8080)
    _verify_scopes(creds, alias=alias)

    # Auto-detect channel ID
    yt_service = build("youtube", "v3", credentials=creds)
    response = yt_service.channels().list(mine=True, part="snippet").execute()
    items = response.get("items", [])

    if not items:
        raise ValueError(
            "No channel found on the authenticated account. "
            "Ensure the account owns a YouTube channel."
        )

    # Take first channel (multi-channel selection is for interactive use)
    channel = items[0]
    channel_id = channel["id"]
    channel_name = channel["snippet"]["title"]

    # Save token file
    token_file = tokens_path / f"{alias}.json"
    _secure_write(token_file, creds.to_json())

    # Update registry
    now = datetime.now(UTC).isoformat()
    reg = ChannelRegistration(
        alias=alias,
        channel_id=channel_id,
        channel_name=channel_name,
        registered_at=now,
        last_used_at=now,
        token_path=str(token_file),
    )

    registry = load_registry(tokens_path)
    registry[alias] = reg
    save_registry(tokens_path, registry)

    return reg


def revoke_channel(alias: str) -> None:
    """Revoke (delete) a channel's token and registry entry.

    Args:
        alias: Channel alias to revoke.

    Raises:
        KeyError: If alias is not registered.
    """
    _validate_alias(alias)
    tokens_path = _tokens_dir()
    registry = load_registry(tokens_path)
    if alias not in registry:
        raise KeyError(f"Channel '{alias}' is not registered. Nothing to revoke.")

    # Delete token file if it exists
    token_file = Path(registry[alias].token_path)
    if token_file.exists():
        token_file.unlink()

    # Remove from registry
    del registry[alias]
    save_registry(tokens_path, registry)


# ─── Channel alias resolution (spec 009 FR-006) ───


def resolve_channel_alias(
    explicit: str | None,
    registry: dict[str, "ChannelRegistration"],
) -> str:
    """Resolve a channel alias from an explicit flag or the registry.

    Implements FR-006 auto-select / multi-alias guard:
    - explicit provided and valid → return it
    - explicit provided but not in registry → raise UserFacingError
    - explicit=None, registry empty → raise NoAliasRegistered
    - explicit=None, registry has 1 alias → auto-select, emit dim notice
    - explicit=None, registry has 2+ aliases → raise MultipleAliasesNoSelection

    Args:
        explicit: The alias passed via --channel, or None if omitted.
        registry: Mapping of alias → ChannelRegistration (from load_registry).

    Returns:
        Resolved alias string.

    Raises:
        NoAliasRegistered: No aliases in registry and none given explicitly.
        MultipleAliasesNoSelection: Multiple aliases registered, none specified.
        UserFacingError: Explicit alias not found in registry.
    """
    from tube_scout.cli.errors import (
        MultipleAliasesNoSelection,
        NoAliasRegistered,
        UserFacingError,
    )

    if explicit is not None:
        if explicit not in registry:
            raise UserFacingError(
                message=(
                    f"Channel alias '{explicit}' is not registered."
                    f" Registered: {', '.join(registry) or '(none)'}."
                ),
                next_command=f"tube-scout auth --channel {explicit}",
            )
        return explicit

    aliases = list(registry)
    if len(aliases) == 0:
        raise NoAliasRegistered()
    if len(aliases) == 1:
        from rich.console import Console

        Console(stderr=True).print(
            f"[dim]Auto-selected channel alias '{aliases[0]}'.[/dim]"
        )
        return aliases[0]

    raise MultipleAliasesNoSelection(aliases=aliases)
