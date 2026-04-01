"""Status and list commands for tube-scout."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from tube_scout.models.config import AppConfig
from tube_scout.storage.checkpoint import load_checkpoint
from tube_scout.storage.json_store import read_json

console = Console()

COLLECTION_PHASES = ["videos", "comments", "transcripts", "retention"]


def show_status(data_dir: Path) -> None:
    """Display current collection and analysis status.

    Args:
        data_dir: Root data directory.
    """
    config_path = data_dir / "config.json"
    config_data = read_json(config_path)
    if config_data is None:
        console.print("[red]No configuration found. Run 'tube-scout init' first.[/red]")
        return

    config = AppConfig(**config_data)

    for channel in config.channels:
        table = Table(title=f"Channel: {channel.channel_id}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Channel ID", channel.channel_id)
        table.add_row("Professor", channel.professor_name)
        table.add_row("Data Directory", config.settings.data_dir)

        for phase in COLLECTION_PHASES:
            state = load_checkpoint(data_dir, channel.channel_id, phase)
            if state:
                status_str = (
                    f"{state.status} ({state.total_collected}/{state.total_expected})"
                )
            else:
                status_str = "not started"
            table.add_row(f"Collection: {phase}", status_str)

        console.print(table)


def show_list(data_dir: Path, sort: str = "published_at", limit: int = 20) -> None:
    """Display collected videos as a rich table.

    Args:
        data_dir: Root data directory.
        sort: Field to sort by.
        limit: Maximum number of videos to display.
    """
    config_path = data_dir / "config.json"
    config_data = read_json(config_path)
    if config_data is None:
        console.print("[red]No configuration found. Run 'tube-scout init' first.[/red]")
        return

    config = AppConfig(**config_data)

    for channel in config.channels:
        videos_path = (
            data_dir / "raw" / "channels" / channel.channel_id / "videos_meta.json"
        )
        videos_data = read_json(videos_path)
        if videos_data is None:
            console.print(
                f"[yellow]No videos collected for {channel.channel_id}. "
                f"Run 'tube-scout collect videos' first.[/yellow]"
            )
            continue

        videos = (
            videos_data
            if isinstance(videos_data, list)
            else videos_data.get("videos", [])
        )

        # Sort
        reverse = sort == "view_count" or sort == "like_count"
        videos.sort(key=lambda v: v.get(sort, ""), reverse=reverse)
        videos = videos[:limit]

        table = Table(title=f"Videos: {channel.channel_id} ({channel.professor_name})")
        table.add_column("ID", style="cyan", max_width=12)
        table.add_column("Title", style="white", max_width=40)
        table.add_column("Date", style="green")
        table.add_column("Views", style="yellow", justify="right")
        table.add_column("Likes", style="magenta", justify="right")
        table.add_column("Duration", style="blue", justify="right")

        for video in videos:
            duration_sec = video.get("duration_seconds", 0)
            minutes = duration_sec // 60
            seconds = duration_sec % 60
            table.add_row(
                video.get("video_id", "?"),
                video.get("title", "?"),
                (
                    video.get("published_at", "?")[:10]
                    if video.get("published_at")
                    else "?"
                ),
                str(video.get("view_count", 0)),
                str(video.get("like_count", 0)),
                f"{minutes}:{seconds:02d}",
            )

        console.print(table)
