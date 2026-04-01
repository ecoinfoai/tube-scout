"""Collect subcommands for tube-scout."""

from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress

from tube_scout.models.config import AppConfig, CollectionState
from tube_scout.services.youtube_analytics import YouTubeAnalyticsService
from tube_scout.services.youtube_data import YouTubeDataService
from tube_scout.storage.checkpoint import load_checkpoint, save_checkpoint
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import write_parquet

console = Console()


def _load_config(data_dir: Path) -> AppConfig:
    """Load and validate config from data directory.

    Args:
        data_dir: Root data directory.

    Returns:
        Validated AppConfig.

    Raises:
        typer.Exit: If config is not found.
    """
    config_data = read_json(data_dir / "config.json")
    if config_data is None:
        console.print("[red]No configuration found. Run 'tube-scout init' first.[/red]")
        raise typer.Exit(code=1)
    return AppConfig(**config_data)


def collect_videos_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Ignore checkpoint, re-collect all.",
    ),
) -> None:
    """Collect video metadata from YouTube Data API.

    Args:
        data_dir: Data storage directory path.
        force_refresh: Whether to ignore existing checkpoints.
    """
    data_path = Path(data_dir)
    config = _load_config(data_path)

    try:
        service = YouTubeDataService()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    for channel_config in config.channels:
        channel_id = channel_config.channel_id
        professor_name = channel_config.professor_name

        # Check checkpoint
        if not force_refresh:
            checkpoint = load_checkpoint(data_path, channel_id, "videos")
            if checkpoint and checkpoint.status == "completed":
                console.print(
                    f"[yellow]Videos already collected for {channel_id}. "
                    f"Use --force-refresh to re-collect.[/yellow]"
                )
                continue

        console.print(f"[bold]Collecting videos for channel {channel_id}...[/bold]")

        # Save in-progress checkpoint
        state = CollectionState(
            channel_id=channel_id,
            phase="videos",
            started_at=datetime.now(UTC),
            status="in_progress",
        )
        save_checkpoint(data_path, state)

        try:
            # Get channel info
            channel_info = service.get_channel_info(channel_id)
            console.print(
                f"  Channel: {channel_info['channel_name']} "
                f"({channel_info['total_video_count']} videos total)"
            )

            # List all videos
            with Progress(console=console) as progress:
                task = progress.add_task("Listing videos...", total=None)
                all_videos = service.list_all_videos(
                    channel_info["uploads_playlist_id"]
                )
                progress.update(task, completed=len(all_videos))

            # Filter by professor name
            filtered = service.filter_by_professor(all_videos, professor_name)
            console.print(
                f"  Found {len(filtered)} videos matching '{professor_name}' "
                f"(out of {len(all_videos)} total)"
            )

            if not filtered:
                console.print(
                    "[yellow]No videos found matching the professor name. "
                    "Check spelling or try a different name.[/yellow]"
                )

            # Get detailed stats for filtered videos
            if filtered:
                video_ids = [v["video_id"] for v in filtered]
                details = service.get_video_details(video_ids)

                # Merge details into video records
                now = datetime.now(UTC).isoformat()
                for video in filtered:
                    vid_id = video["video_id"]
                    if vid_id in details:
                        video.update(details[vid_id])
                    video["channel_id"] = channel_id
                    video["collected_at"] = now

            # Save to data/raw/channels/{channel_id}/
            channel_dir = data_path / "raw" / "channels" / channel_id
            channel_dir.mkdir(parents=True, exist_ok=True)

            write_json(channel_dir / "videos_meta.json", filtered)

            # Also save as Parquet for analytics (T024)
            if filtered:
                import polars as pl

                df = pl.DataFrame(filtered)
                write_parquet(channel_dir / "videos_meta.parquet", df)

            write_json(
                channel_dir / "channel_meta.json",
                {
                    **channel_info,
                    "professor_name": professor_name,
                    "filtered_video_count": len(filtered),
                    "last_collected_at": datetime.now(UTC).isoformat(),
                },
            )

            # Update checkpoint
            state.total_expected = len(all_videos)
            state.total_collected = len(filtered)
            state.status = "completed"
            state.updated_at = datetime.now(UTC)
            save_checkpoint(data_path, state)

            console.print(
                f"[green]Collected {len(filtered)} videos successfully.[/green]"
            )

        except Exception as e:
            error_msg = str(e)
            if "quota" in error_msg.lower():
                state.status = "interrupted"
                state.updated_at = datetime.now(UTC)
                save_checkpoint(data_path, state)
                console.print(
                    "[red]API quota exceeded. Progress saved. "
                    "Resume later with the same command.[/red]"
                )
                raise typer.Exit(code=2)
            else:
                state.status = "interrupted"
                state.updated_at = datetime.now(UTC)
                save_checkpoint(data_path, state)
                console.print(f"[red]Error: {e}[/red]")
                raise typer.Exit(code=1)


def collect_retention_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    video_id: str = typer.Option(
        None,
        "--video-id",
        help="Specific video ID to collect retention for.",
    ),
) -> None:
    """Collect audience retention data from YouTube Analytics API.

    Args:
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
    """
    import polars as pl

    data_path = Path(data_dir)
    config = _load_config(data_path)

    try:
        service = YouTubeAnalyticsService()
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    video_ids_to_collect: list[str] = []

    if video_id:
        video_ids_to_collect = [video_id]
    else:
        # Collect for all filtered videos
        for channel_config in config.channels:
            videos_path = (
                data_path
                / "raw"
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos_data = read_json(videos_path)
            if videos_data:
                videos = (
                    videos_data
                    if isinstance(videos_data, list)
                    else videos_data.get("videos", [])
                )
                video_ids_to_collect.extend(v["video_id"] for v in videos)

    if not video_ids_to_collect:
        console.print(
            "[yellow]No videos found. Run 'tube-scout collect videos' first.[/yellow]"
        )
        raise typer.Exit(code=1)

    console.print(
        f"[bold]Collecting retention data for "
        f"{len(video_ids_to_collect)} video(s)...[/bold]"
    )

    for vid_id in video_ids_to_collect:
        try:
            retention = service.get_retention_data(vid_id)
            if retention:
                df = pl.DataFrame(retention)
                output_path = data_path / "raw" / "retention" / f"{vid_id}.parquet"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                write_parquet(output_path, df)
                console.print(
                    f"  [green]{vid_id}: {len(retention)} data points saved[/green]"
                )
            else:
                console.print(
                    f"  [yellow]{vid_id}: no retention data available[/yellow]"
                )
        except PermissionError as e:
            console.print(f"  [yellow]{vid_id}: {e}[/yellow]")
        except Exception as e:
            console.print(f"  [red]{vid_id}: {e}[/red]")


def collect_comments_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    video_id: str = typer.Option(
        None,
        "--video-id",
        help="Specific video ID to collect comments for.",
    ),
) -> None:
    """Collect comments for videos from YouTube Data API.

    Args:
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
    """
    data_path = Path(data_dir)
    config = _load_config(data_path)

    try:
        service = YouTubeDataService()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    video_ids_to_collect: list[str] = []

    if video_id:
        video_ids_to_collect = [video_id]
    else:
        for channel_config in config.channels:
            videos_path = (
                data_path
                / "raw"
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos_data = read_json(videos_path)
            if videos_data:
                videos = (
                    videos_data
                    if isinstance(videos_data, list)
                    else videos_data.get("videos", [])
                )
                video_ids_to_collect.extend(v["video_id"] for v in videos)

    if not video_ids_to_collect:
        console.print(
            "[yellow]No videos found. Run 'tube-scout collect videos' first.[/yellow]"
        )
        raise typer.Exit(code=1)

    console.print(
        f"[bold]Collecting comments for {len(video_ids_to_collect)} video(s)...[/bold]"
    )

    for vid_id in video_ids_to_collect:
        try:
            comments = service.get_comments(vid_id)
            if comments:
                output_path = data_path / "raw" / "comments" / f"{vid_id}.json"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                write_json(output_path, comments)
                console.print(
                    f"  [green]{vid_id}: {len(comments)} comments saved[/green]"
                )
            else:
                console.print(f"  [yellow]{vid_id}: no comments found[/yellow]")
        except Exception as e:
            console.print(f"  [red]{vid_id}: {e}[/red]")


def collect_transcripts_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    video_id: str = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Collect transcripts for videos using youtube-transcript-api.

    Args:
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.transcript import TranscriptService

    data_path = Path(data_dir)
    config = _load_config(data_path)
    service = TranscriptService()

    video_ids_to_collect: list[str] = []

    if video_id:
        video_ids_to_collect = [video_id]
    else:
        for channel_config in config.channels:
            videos_path = (
                data_path
                / "raw"
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos_data = read_json(videos_path)
            if videos_data:
                videos = (
                    videos_data
                    if isinstance(videos_data, list)
                    else videos_data.get("videos", [])
                )
                video_ids_to_collect.extend(v["video_id"] for v in videos)

    if not video_ids_to_collect:
        console.print(
            "[yellow]No videos found. Run 'tube-scout collect videos' first.[/yellow]"
        )
        raise typer.Exit(code=1)

    console.print(
        f"[bold]Collecting transcripts for "
        f"{len(video_ids_to_collect)} video(s)...[/bold]"
    )

    for vid_id in video_ids_to_collect:
        try:
            result = service.fetch_transcript(vid_id)
            if result:
                output_path = data_path / "raw" / "transcripts" / f"{vid_id}.json"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                write_json(output_path, result)
                console.print(
                    f"  [green]{vid_id}: {len(result['segments'])} segments "
                    f"({result['transcript_type']})[/green]"
                )
            else:
                console.print(f"  [yellow]{vid_id}: no transcript available[/yellow]")
        except Exception as e:
            console.print(f"  [red]{vid_id}: {e}[/red]")


def collect_all_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Ignore checkpoints.",
    ),
) -> None:
    """Run all collection steps in sequence.

    Args:
        data_dir: Data storage directory path.
        force_refresh: Whether to ignore existing checkpoints.
    """
    console.print("[bold]Running full collection pipeline...[/bold]\n")

    console.print("[bold cyan]Step 1/4: Collecting videos...[/bold cyan]")
    try:
        collect_videos_command(data_dir=data_dir, force_refresh=force_refresh)
    except SystemExit:
        pass

    console.print("\n[bold cyan]Step 2/4: Collecting comments...[/bold cyan]")
    try:
        collect_comments_command(data_dir=data_dir)
    except SystemExit:
        pass

    console.print("\n[bold cyan]Step 3/4: Collecting transcripts...[/bold cyan]")
    try:
        collect_transcripts_command(data_dir=data_dir)
    except SystemExit:
        pass

    console.print("\n[bold cyan]Step 4/4: Collecting retention data...[/bold cyan]")
    try:
        collect_retention_command(data_dir=data_dir)
    except SystemExit:
        pass

    console.print("\n[bold green]Collection pipeline complete.[/bold green]")
