"""OAuth2 authentication for YouTube Analytics API."""

import os
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
TOKEN_FILE = "token.json"


def _default_client_secret_path() -> Path:
    """Return path to client secret JSON from env or default location."""
    env_path = os.environ.get("TUBE_SCOUT_CLIENT_SECRET")
    if env_path:
        return Path(env_path)

    config_dir = Path.home() / ".config" / "tube-scout"
    for f in sorted(config_dir.glob("client_secret_*.json")):
        return f

    raise FileNotFoundError(
        "OAuth client secret not found. Set TUBE_SCOUT_CLIENT_SECRET env var "
        "or place client_secret_*.json in ~/.config/tube-scout/"
    )


def _token_path() -> Path:
    """Return path to cached OAuth token."""
    config_dir = Path.home() / ".config" / "tube-scout"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / TOKEN_FILE


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
        from google.auth.transport.requests import Request

        creds.refresh(Request())
    else:
        client_secret = _default_client_secret_path()
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        creds = flow.run_local_server(port=8080)

    token_path.write_text(creds.to_json())
    return creds


def build_data_client() -> Any:
    """Build and return an authenticated YouTube Data API client.

    Returns:
        YouTube Data API v3 client resource (with OAuth, can access unlisted videos).
    """
    creds = authenticate()
    return build("youtube", "v3", credentials=creds)


def build_analytics_client() -> Any:
    """Build and return an authenticated YouTube Analytics API client.

    Returns:
        YouTube Analytics API client resource.
    """
    creds = authenticate()
    return build("youtubeAnalytics", "v2", credentials=creds)
