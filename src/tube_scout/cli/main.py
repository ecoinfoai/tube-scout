"""Tube Scout CLI entry point."""

from pathlib import Path

import typer
from rich.console import Console

from tube_scout.cli.analyze import (
    analyze_all_command,
    analyze_eqs_command,
    analyze_forecast_command,
    analyze_retention_command,
    analyze_sentiment_command,
    analyze_transcript_command,
)
from tube_scout.cli.collect import (
    collect_all_command,
    collect_comments_command,
    collect_retention_command,
    collect_transcripts_command,
    collect_videos_command,
)
from tube_scout.cli.report import (
    report_channel_command,
    report_video_command,
)
from tube_scout.models.config import AppConfig, ChannelConfig, Settings
from tube_scout.storage.json_store import write_json

app = typer.Typer(
    name="tube-scout",
    help="YouTube lecture video analytics CLI tool.",
    no_args_is_help=True,
)
console = Console()

# Register sub-command groups
collect_app = typer.Typer(help="Collect data from YouTube APIs.")
analyze_app = typer.Typer(help="Analyze collected data.")
report_app = typer.Typer(help="Generate analysis reports.")

app.add_typer(collect_app, name="collect")
app.add_typer(analyze_app, name="analyze")
app.add_typer(report_app, name="report")

# Register collect subcommands
collect_app.command(name="videos")(collect_videos_command)
collect_app.command(name="retention")(collect_retention_command)
collect_app.command(name="comments")(collect_comments_command)
collect_app.command(name="transcripts")(collect_transcripts_command)
collect_app.command(name="all")(collect_all_command)

# Register analyze subcommands
analyze_app.command(name="retention")(analyze_retention_command)
analyze_app.command(name="sentiment")(analyze_sentiment_command)
analyze_app.command(name="transcript")(analyze_transcript_command)
analyze_app.command(name="eqs")(analyze_eqs_command)
analyze_app.command(name="forecast")(analyze_forecast_command)
analyze_app.command(name="all")(analyze_all_command)

# Register report subcommands
report_app.command(name="video")(report_video_command)
report_app.command(name="channel")(report_channel_command)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print("tube-scout version 0.1.0")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """YouTube lecture video analytics CLI tool."""


@app.command()
def init(
    channel_id: str = typer.Option(
        ...,
        "--channel-id",
        help="YouTube channel ID (starts with UC).",
    ),
    professor: str = typer.Option(
        ...,
        "--professor",
        help="Professor name for filtering.",
    ),
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
) -> None:
    """Initialize project configuration.

    Args:
        channel_id: YouTube channel ID.
        professor: Professor name for video title filtering.
        data_dir: Directory for storing collected data.
    """
    try:
        channel_config = ChannelConfig(
            channel_id=channel_id,
            professor_name=professor,
        )
    except ValueError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(code=1)

    config = AppConfig(
        channels=[channel_config],
        settings=Settings(data_dir=data_dir),
    )

    config_path = Path(data_dir) / "config.json"
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    write_json(config_path, config.model_dump(mode="json"))
    console.print(f"[green]Configuration saved to {config_path}[/green]")


@app.command()
def status(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
) -> None:
    """Show current collection and analysis status.

    Args:
        data_dir: Directory where data is stored.
    """
    from tube_scout.cli.status import show_status

    show_status(Path(data_dir))


@app.command(name="list")
def list_videos(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    sort: str = typer.Option("published_at", "--sort", help="Sort field."),
    limit: int = typer.Option(20, "--limit", help="Number of videos to display."),
) -> None:
    """List collected videos.

    Args:
        data_dir: Directory where data is stored.
        sort: Field to sort by.
        limit: Maximum number of videos to show.
    """
    from tube_scout.cli.status import show_list

    show_list(Path(data_dir), sort=sort, limit=limit)
