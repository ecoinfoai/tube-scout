"""Auth CLI subcommands for multi-channel token management."""

import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from tube_scout.cli.errors import UserFacingError

console = Console()


def select_auth_flow(
    *,
    browser_redirect: bool,
    is_tty: bool,
    has_stdout: bool = True,
) -> str:
    """Determine which OAuth flow to use based on environment flags.

    Args:
        browser_redirect: Whether --browser-redirect flag was passed.
        is_tty: Whether stdin is a TTY.
        has_stdout: Whether stdout is available (False in fully headless context).

    Returns:
        "browser" if browser_redirect AND is_tty; "device" otherwise.

    Raises:
        InteractiveAuthRequired: If not is_tty and not has_stdout.
    """
    from tube_scout.services.auth import InteractiveAuthRequired  # noqa: PLC0415

    if not is_tty and not has_stdout:
        raise InteractiveAuthRequired()

    if browser_redirect and is_tty:
        return "browser"

    return "device"


class BrowserRedirectTimeout(UserFacingError):
    """Browser-redirect OAuth listener timed out (FR-013-bis).

    Args:
        alias: Channel alias for which auth was attempted.
    """

    def __init__(self, *, alias: str) -> None:
        super().__init__(
            message=(
                f"Browser-redirect OAuth for '{alias}' timed out."
                " No partial token has been written."
            ),
            next_command=f"tube-scout auth --channel {alias}",
        )


def run_browser_redirect_with_timeout(
    *,
    alias: str,
    timeout_seconds: float = 300.0,
    token_path: Path | None = None,
) -> Any:
    """Attempt browser-redirect OAuth flow with a hard timeout.

    Args:
        alias: Channel alias being authenticated.
        timeout_seconds: Maximum seconds to wait for browser redirect completion.
        token_path: Optional partial token path to unlink on timeout.

    Returns:
        Credentials object if the flow completes in time.

    Raises:
        BrowserRedirectTimeout: If the flow exceeds timeout_seconds or fails.
    """
    start = time.monotonic()

    creds = None
    try:
        from tube_scout.services.auth import _default_client_secret_path, SCOPES  # noqa: PLC0415
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415

        client_secret = _default_client_secret_path()
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        creds = flow.run_local_server(port=8080)
    except Exception:
        creds = None

    end = time.monotonic()

    if (end - start) > timeout_seconds or creds is None:
        if token_path is not None and token_path.exists():
            token_path.unlink()
        raise BrowserRedirectTimeout(alias=alias)

    return creds


def auth_command(
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Register a new department channel via OAuth.",
    ),
    list_channels: bool = typer.Option(
        False,
        "--list",
        help="List all registered channels.",
    ),
    revoke: str | None = typer.Option(
        None,
        "--revoke",
        help="Revoke (delete) a channel's token by alias.",
    ),
    browser_redirect: bool = typer.Option(
        False,
        "--browser-redirect",
        help="Use browser-redirect OAuth flow instead of device-code (default).",
    ),
) -> None:
    """Manage multi-channel OAuth authentication.

    Args:
        channel: Department alias to register via OAuth.
        list_channels: If True, list all registered channels.
        revoke: Channel alias to revoke.
        browser_redirect: If True, use browser-redirect flow (default: device-code).
    """
    if list_channels:
        _list_channels()
        return

    if revoke:
        _revoke_channel(revoke)
        return

    if channel:
        _register_channel(channel, browser_redirect=browser_redirect)
        return

    console.print(
        "[yellow]Specify --channel <alias>, --list, or --revoke <alias>.[/yellow]"
    )
    raise typer.Exit(code=1)


def _list_channels() -> None:
    """Display all registered channels as a Rich table."""
    from tube_scout.services.auth import list_channels

    channels = list_channels()
    if not channels:
        console.print("[yellow]No channels registered.[/yellow]")
        return

    table = Table(title="Registered Channels")
    table.add_column("Alias", style="cyan")
    table.add_column("Channel Name", style="green")
    table.add_column("Channel ID", style="dim")
    table.add_column("Registered", style="yellow")
    table.add_column("Last Used", style="yellow")

    for ch in channels:
        table.add_row(
            ch.alias,
            ch.channel_name,
            ch.channel_id,
            ch.registered_at,
            ch.last_used_at,
        )

    console.print(table)


def _register_channel(alias: str, *, browser_redirect: bool = False) -> None:
    """Register a new channel via OAuth flow.

    Args:
        alias: Department alias for the channel.
        browser_redirect: If True, use browser-redirect flow; otherwise device-code.
    """
    import sys  # noqa: PLC0415

    flow = select_auth_flow(
        browser_redirect=browser_redirect,
        is_tty=sys.stdin.isatty(),
    )

    if flow == "browser":
        from tube_scout.services.auth import register_channel  # noqa: PLC0415

        try:
            reg = register_channel(alias)
            console.print(
                f"[green]Channel '{reg.alias}' registered successfully "
                f"(ID: {reg.channel_id}, Name: {reg.channel_name})[/green]"
            )
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=2)
    else:
        _register_channel_device_flow(alias)


def _revoke_channel(alias: str) -> None:
    """Revoke a channel's token.

    Args:
        alias: Channel alias to revoke.
    """
    from tube_scout.services.auth import revoke_channel  # noqa: PLC0415

    try:
        revoke_channel(alias)
        console.print(f"[green]Channel '{alias}' revoked successfully.[/green]")
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)


def _register_channel_device_flow(alias: str, *, _browser_fallback: bool = False) -> None:
    """Register a channel using RFC 8628 device-code flow.

    When the OAuth client type does not support device authorization
    (HTTP 401 invalid_client), falls back to browser-redirect flow once.
    The ``_browser_fallback`` guard prevents recursive re-entry.

    Args:
        alias: Department alias for the channel.
        _browser_fallback: Internal guard — True when already in fallback path.
    """
    import json  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from tube_scout.services.auth import (  # noqa: PLC0415
        SCOPES,
        _authorized_http,
        _secure_write,
        _tokens_dir,
        _default_client_secret_path,
        _validate_alias,
        load_registry,
        save_registry,
    )
    from tube_scout.services.auth_device_flow import DeviceFlow  # noqa: PLC0415
    from tube_scout.models.config import ChannelRegistration  # noqa: PLC0415
    from googleapiclient.discovery import build as build_api  # noqa: PLC0415

    _validate_alias(alias)

    try:
        secret_path = _default_client_secret_path()
        secret_data = json.loads(secret_path.read_text(encoding="utf-8"))
        installed = secret_data.get("installed") or secret_data.get("web") or {}
        client_id = installed["client_id"]
        client_secret = installed["client_secret"]
    except Exception as e:
        console.print(f"[red]Could not load client secret: {e}[/red]")
        raise typer.Exit(code=1)

    tokens_path = _tokens_dir()
    tokens_path.mkdir(parents=True, exist_ok=True)
    token_file = tokens_path / f"{alias}.json"

    flow = DeviceFlow(client_id=client_id, client_secret=client_secret, alias=alias)

    def on_code(user_code: str, verification_url: str, expires_in: int) -> None:
        console.print(
            f"\n[bold yellow]Device Authorization Required[/bold yellow]\n"
            f"  Go to: [cyan]{verification_url}[/cyan]\n"
            f"  Enter code: [bold green]{user_code}[/bold green]\n"
            f"  (expires in {expires_in}s)\n"
        )

    try:
        token_dict = flow.run(
            scopes=SCOPES,
            on_code=on_code,
            token_path=token_file,
        )
    except UserFacingError as e:
        from tube_scout.cli.errors import ClientTypeNotSupportedForDeviceFlow  # noqa: PLC0415

        if isinstance(e, ClientTypeNotSupportedForDeviceFlow) and not _browser_fallback:
            console.print(f"[yellow]Warning: {e.message}[/yellow]")
            console.print("[dim]Falling back to browser-redirect flow...[/dim]")
            run_browser_redirect_with_timeout(alias=alias)
            return
        console.print(f"[red]Error: {e.message}[/red]")
        console.print(f"  Try: {e.next_command}")
        raise typer.Exit(code=1)

    from google.oauth2.credentials import Credentials  # noqa: PLC0415

    granted_scopes = token_dict.get("scope", "").split() or SCOPES
    creds = Credentials(
        token=token_dict["access_token"],
        refresh_token=token_dict.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=granted_scopes,
    )
    _secure_write(token_file, creds.to_json())

    yt_service = build_api("youtube", "v3", http=_authorized_http(creds))
    response = yt_service.channels().list(mine=True, part="snippet").execute()
    items = response.get("items", [])

    if not items:
        token_file.unlink(missing_ok=True)
        console.print("[red]No channel found on the authenticated account.[/red]")
        raise typer.Exit(code=1)

    channel = items[0]
    channel_id = channel["id"]
    channel_name = channel["snippet"]["title"]

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

    console.print(
        f"[green]Channel '{alias}' registered via device-code flow "
        f"(ID: {channel_id}, Name: {channel_name})[/green]"
    )
