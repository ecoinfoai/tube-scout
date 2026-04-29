"""OAuth2 authentication for YouTube Analytics API.

Supports both single-channel (legacy) and multi-channel token management.
"""

import json
import os
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
TOKEN_FILE = "token.json"


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
    """Return path to client secret JSON from TUBE_SCOUT_CLIENT_SECRET env var.

    Returns:
        Path to the client secret JSON file.

    Raises:
        ValueError: If TUBE_SCOUT_CLIENT_SECRET env var is not set.
        FileNotFoundError: If the file at the env var path does not exist.
    """
    env_path = os.environ.get("TUBE_SCOUT_CLIENT_SECRET")
    if not env_path:
        raise ValueError(
            "TUBE_SCOUT_CLIENT_SECRET environment variable is required. "
            "Set it to the path of your OAuth client secret JSON file."
        )

    path = Path(env_path)
    if not path.exists():
        raise FileNotFoundError(
            f"OAuth client secret not found at {env_path}. "
            "Verify TUBE_SCOUT_CLIENT_SECRET points to an existing file."
        )
    return path


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
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        client_secret = _default_client_secret_path()
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        creds = flow.run_local_server(port=8080)

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
        update_last_used(tokens_path, alias)
        return creds

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
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
    tokens_path = _tokens_dir()
    tokens_path.mkdir(parents=True, exist_ok=True)

    # Run OAuth flow
    client_secret = _default_client_secret_path()
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=8080)

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
