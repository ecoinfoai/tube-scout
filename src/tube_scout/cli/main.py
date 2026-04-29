"""Tube Scout CLI entry point."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import typer
from rich.console import Console

from tube_scout.cli.analyze import (
    analyze_all_command,
    analyze_eqs_command,
    analyze_forecast_command,
    analyze_retention_command,
    analyze_sentiment_command,
    analyze_topic_command,
    analyze_transcript_command,
)
from tube_scout.cli.auth_cli import auth_command
from tube_scout.cli.collect import (
    collect_all_command,
    collect_analytics_command,
    collect_bulk_command,
    collect_comments_command,
    collect_retention_command,
    collect_transcripts_command,
    collect_videos_command,
)
from tube_scout.cli.content import content_app
from tube_scout.cli.report import (
    report_bundle_command,
    report_channel_command,
    report_comment_insight_command,
    report_content_command,
    report_department_command,
    report_video_command,
)
from tube_scout.cli.search_cli import search_command
from tube_scout.cli.validate_cli import validate_command
from tube_scout.models.config import (
    AcademicCalendar,
    AppConfig,
    ChannelConfig,
    Settings,
)
from tube_scout.storage.json_store import read_json, write_json

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

calendar_app = typer.Typer(help="Manage academic calendar for forecasting.")

app.command(name="auth")(auth_command)
app.command(name="search")(search_command)
app.command(name="validate")(validate_command)
app.add_typer(collect_app, name="collect")
app.add_typer(analyze_app, name="analyze")
app.add_typer(report_app, name="report")
app.add_typer(calendar_app, name="calendar")
app.add_typer(content_app, name="content")

# T089: register admin subcommand group (US3 admin CLI).
from tube_scout.cli.admin import admin_app  # noqa: E402

app.add_typer(admin_app, name="admin")

# Register collect subcommands
collect_app.command(name="videos")(collect_videos_command)
collect_app.command(name="retention")(collect_retention_command)
collect_app.command(name="comments")(collect_comments_command)
collect_app.command(name="transcripts")(collect_transcripts_command)
collect_app.command(name="analytics")(collect_analytics_command)
collect_app.command(name="bulk")(collect_bulk_command)
collect_app.command(name="all")(collect_all_command)

# Register analyze subcommands
analyze_app.command(name="retention")(analyze_retention_command)
analyze_app.command(name="sentiment")(analyze_sentiment_command)
analyze_app.command(name="transcript")(analyze_transcript_command)
analyze_app.command(name="eqs")(analyze_eqs_command)
analyze_app.command(name="topic")(analyze_topic_command)
analyze_app.command(name="forecast")(analyze_forecast_command)
analyze_app.command(name="all")(analyze_all_command)

# Register report subcommands
report_app.command(name="video")(report_video_command)
report_app.command(name="channel")(report_channel_command)
report_app.command(name="comment-insight")(report_comment_insight_command)
report_app.command(name="department")(report_department_command)
report_app.command(name="bundle")(report_bundle_command)
report_app.command(name="content")(report_content_command)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        try:
            pkg_version = version("tube-scout")
        except PackageNotFoundError:
            pkg_version = "unknown"
        console.print(f"tube-scout version {pkg_version}")
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
        help="User data directory (config, credentials).",
    ),
    project_dir: str = typer.Option(
        "./projects",
        "--project-dir",
        help="Projects root directory.",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Existing project path or 'latest'.",
    ),
) -> None:
    """Show current collection and analysis status.

    Args:
        data_dir: User data directory.
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
    """
    from tube_scout.cli.status import show_status

    checkpoint_dir = None
    if project is not None:
        from tube_scout.cli.project import resolve_project

        mgr = resolve_project(project_dir, project)
        checkpoint_dir = mgr.checkpoint_dir

    show_status(Path(data_dir), checkpoint_dir=checkpoint_dir)


@app.command(name="list")
def list_videos(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="User data directory (config, credentials).",
    ),
    project_dir: str = typer.Option(
        "./projects",
        "--project-dir",
        help="Projects root directory.",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Existing project path or 'latest'.",
    ),
    sort: str = typer.Option("published_at", "--sort", help="Sort field."),
    limit: int = typer.Option(20, "--limit", help="Number of videos to display."),
) -> None:
    """List collected videos.

    Args:
        data_dir: User data directory.
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        sort: Field to sort by.
        limit: Maximum number of videos to show.
    """
    from tube_scout.cli.status import show_list

    collect_dir = None
    if project is not None:
        from tube_scout.cli.project import resolve_project

        mgr = resolve_project(project_dir, project)
        collect_dir = mgr.collect_dir

    show_list(Path(data_dir), collect_dir=collect_dir, sort=sort, limit=limit)


@calendar_app.command(name="set")
def calendar_set(
    file: str = typer.Option(
        ...,
        "--file",
        help="Path to academic calendar JSON file.",
    ),
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
) -> None:
    """Set academic calendar for forecasting.

    Args:
        file: Path to calendar JSON file.
        data_dir: Data storage directory path.
    """
    from pydantic import ValidationError

    calendar_path = Path(file)
    if not calendar_path.exists():
        console.print(f"[red]Calendar file not found: {file}[/red]")
        raise typer.Exit(code=1)

    calendar_data = read_json(calendar_path)
    if calendar_data is None:
        console.print("[red]Failed to read calendar file.[/red]")
        raise typer.Exit(code=1)

    try:
        calendar = AcademicCalendar(**calendar_data)
    except ValidationError as e:
        console.print(f"[red]Academic calendar file is invalid: {e}[/red]")
        raise typer.Exit(code=1)

    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    write_json(data_path / "calendar.json", calendar.model_dump(mode="json"))
    console.print(
        f"[green]Academic calendar saved with {len(calendar.events)} event(s).[/green]"
    )


@calendar_app.command(name="show")
def calendar_show(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
) -> None:
    """Display current academic calendar.

    Args:
        data_dir: Data storage directory path.
    """
    from rich.table import Table

    data_path = Path(data_dir)
    calendar_data = read_json(data_path / "calendar.json")
    if calendar_data is None:
        console.print(
            "[yellow]No academic calendar set. "
            "Use 'tube-scout calendar set --file PATH' to configure.[/yellow]"
        )
        raise typer.Exit(code=1)

    events = calendar_data.get("events", [])
    table = Table(title="Academic Calendar")
    table.add_column("Name", style="cyan")
    table.add_column("Start Date", style="green")
    table.add_column("End Date", style="green")
    table.add_column("Type", style="yellow")

    for event in events:
        table.add_row(
            event.get("name", ""),
            event.get("start_date", ""),
            event.get("end_date", ""),
            event.get("event_type", ""),
        )

    console.print(table)
