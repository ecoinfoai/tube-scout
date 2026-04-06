"""Auth CLI subcommands for multi-channel token management."""

import typer
from rich.console import Console
from rich.table import Table

console = Console()


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
) -> None:
    """Manage multi-channel OAuth authentication.

    Args:
        channel: Department alias to register via OAuth.
        list_channels: If True, list all registered channels.
        revoke: Channel alias to revoke.
    """
    if list_channels:
        _list_channels()
        return

    if revoke:
        _revoke_channel(revoke)
        return

    if channel:
        _register_channel(channel)
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


def _register_channel(alias: str) -> None:
    """Register a new channel via OAuth flow.

    Args:
        alias: Department alias for the channel.
    """
    from tube_scout.services.auth import register_channel

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


def _revoke_channel(alias: str) -> None:
    """Revoke a channel's token.

    Args:
        alias: Channel alias to revoke.
    """
    from tube_scout.services.auth import revoke_channel

    try:
        revoke_channel(alias)
        console.print(f"[green]Channel '{alias}' revoked successfully.[/green]")
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
