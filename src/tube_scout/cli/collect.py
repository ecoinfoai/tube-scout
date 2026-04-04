"""Collect subcommands for tube-scout."""

from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console

from tube_scout.cli.progress import create_progress
from tube_scout.cli.project import resolve_project
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
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Ignore checkpoint, re-collect all.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (uses multi-channel token).",
    ),
) -> None:
    """Collect video metadata from YouTube Data API.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        force_refresh: Whether to ignore existing checkpoints.
        channel: Optional channel alias for multi-channel auth.
    """
    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project)

    try:
        if channel:
            from tube_scout.services.auth import authenticate_channel

            creds = authenticate_channel(channel)
            from googleapiclient.discovery import build as build_api

            client = build_api("youtube", "v3", credentials=creds)
            service = YouTubeDataService(client=client)
            console.print(
                f"[dim]Using multi-channel auth for '{channel}'[/dim]"
            )
        else:
            from tube_scout.services.auth import build_data_client

            client = build_data_client()
            service = YouTubeDataService(client=client)
            console.print(
                "[dim]Using OAuth authentication (unlisted videos accessible)[/dim]"
            )
    except (FileNotFoundError, Exception):
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
            checkpoint = load_checkpoint(mgr.checkpoint_dir, channel_id, "videos")
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
        save_checkpoint(mgr.checkpoint_dir, state)

        try:
            # Get channel info
            channel_info = service.get_channel_info(channel_id)
            console.print(
                f"  Channel: {channel_info['channel_name']} "
                f"({channel_info['total_video_count']} videos total)"
            )

            # List all videos
            with create_progress() as progress:
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

            # Save to collect/channels/{channel_id}/
            channel_dir = mgr.collect_dir / "channels" / channel_id
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
            save_checkpoint(mgr.checkpoint_dir, state)

            console.print(
                f"[green]Collected {len(filtered)} videos successfully.[/green]"
            )

        except Exception as e:
            error_msg = str(e)
            if "quota" in error_msg.lower():
                state.status = "interrupted"
                state.updated_at = datetime.now(UTC)
                save_checkpoint(mgr.checkpoint_dir, state)
                console.print(
                    "[red]API quota exceeded. Progress saved. "
                    "Resume later with the same command.[/red]"
                )
                raise typer.Exit(code=2)
            else:
                state.status = "interrupted"
                state.updated_at = datetime.now(UTC)
                save_checkpoint(mgr.checkpoint_dir, state)
                console.print(f"[red]Error: {e}[/red]")
                raise typer.Exit(code=1)


def collect_retention_command(
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
    video_id: str = typer.Option(
        None,
        "--video-id",
        help="Specific video ID to collect retention for.",
    ),
) -> None:
    """Collect audience retention data from YouTube Analytics API.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
    """
    import polars as pl

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project)

    try:
        from tube_scout.services.auth import build_analytics_client

        client = build_analytics_client()
        service = YouTubeAnalyticsService(client=client)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]OAuth authentication failed: {e}[/red]")
        raise typer.Exit(code=1)

    video_ids_to_collect: list[str] = []

    if video_id:
        video_ids_to_collect = [video_id]
    else:
        # Collect for all filtered videos
        for channel_config in config.channels:
            videos_path = (
                mgr.collect_dir
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

    with create_progress() as progress:
        task = progress.add_task(
            "Collecting retention", total=len(video_ids_to_collect)
        )
        for vid_id in video_ids_to_collect:
            try:
                retention = service.get_retention_data(vid_id)
                if retention:
                    df = pl.DataFrame(retention)
                    output_path = (
                        mgr.collect_dir / "retention" / f"{vid_id}.parquet"
                    )
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    write_parquet(output_path, df)
                    progress.console.print(
                        f"  [green]{vid_id}: {len(retention)} data points saved[/green]"
                    )
                else:
                    progress.console.print(
                        f"  [yellow]{vid_id}: no retention data available[/yellow]"
                    )
            except PermissionError as e:
                progress.console.print(f"  [yellow]{vid_id}: {e}[/yellow]")
            except Exception as e:
                progress.console.print(f"  [red]{vid_id}: {e}[/red]")
            progress.advance(task)


def collect_comments_command(
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
    video_id: str = typer.Option(
        None,
        "--video-id",
        help="Specific video ID to collect comments for.",
    ),
    include_replies: bool = typer.Option(
        False,
        "--include-replies",
        help="Also collect replies for each comment thread.",
    ),
) -> None:
    """Collect comments for videos from YouTube Data API.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
        include_replies: Whether to collect reply threads.
    """
    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project)

    try:
        from tube_scout.services.auth import build_data_client

        client = build_data_client()
        service = YouTubeDataService(client=client)
    except (FileNotFoundError, Exception):
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
                mgr.collect_dir
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

    with create_progress() as progress:
        task = progress.add_task(
            "Collecting comments", total=len(video_ids_to_collect)
        )
        for vid_id in video_ids_to_collect:
            try:
                comments = service.get_comments(
                    vid_id, include_replies=include_replies
                )
                if comments:
                    output_path = mgr.collect_dir / "comments" / f"{vid_id}.json"
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    write_json(output_path, comments)
                    progress.console.print(
                        f"  [green]{vid_id}: {len(comments)} comments saved[/green]"
                    )
                else:
                    progress.console.print(
                        f"  [yellow]{vid_id}: no comments found[/yellow]"
                    )
            except Exception as e:
                progress.console.print(f"  [red]{vid_id}: {e}[/red]")
            progress.advance(task)


def collect_transcripts_command(
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
    video_id: str = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Collect transcripts for videos using youtube-transcript-api.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.transcript import TranscriptService

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project)
    service = TranscriptService()

    video_ids_to_collect: list[str] = []

    if video_id:
        video_ids_to_collect = [video_id]
    else:
        for channel_config in config.channels:
            videos_path = (
                mgr.collect_dir
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

    with create_progress() as progress:
        task = progress.add_task(
            "Collecting transcripts", total=len(video_ids_to_collect)
        )
        for vid_id in video_ids_to_collect:
            try:
                result = service.fetch_transcript(vid_id)
                if result:
                    output_path = (
                        mgr.collect_dir / "transcripts" / f"{vid_id}.json"
                    )
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    write_json(output_path, result)
                    progress.console.print(
                        f"  [green]{vid_id}: {len(result['segments'])} segments "
                        f"({result['transcript_type']})[/green]"
                    )
                else:
                    progress.console.print(
                        f"  [yellow]{vid_id}: no transcript available[/yellow]"
                    )
            except Exception as e:
                progress.console.print(f"  [red]{vid_id}: {e}[/red]")
            progress.advance(task)


def collect_analytics_command(
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
    start_date: str | None = typer.Option(
        None,
        "--start-date",
        help="Override default 2-year lookback (ISO date: YYYY-MM-DD).",
    ),
    report_type: str | None = typer.Option(
        None,
        "--report-type",
        help="Collect only a specific report type.",
    ),
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Collect for a specific video only.",
    ),
    incremental: bool = typer.Option(
        True,
        "--incremental/--full",
        help="Incremental (default) or full re-collection.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (uses multi-channel token).",
    ),
) -> None:
    """Collect YouTube Analytics report data.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        start_date: Override start date (ISO format).
        report_type: Specific report type to collect.
        video_id: Optional specific video ID.
        incremental: Whether to use incremental sync.
        channel: Optional channel alias for multi-channel auth.
    """
    import polars as pl

    from tube_scout.storage.parquet_store import write_parquet

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project)

    try:
        if channel:
            from tube_scout.services.auth import authenticate_channel

            creds = authenticate_channel(channel)
            from googleapiclient.discovery import build as build_api

            client = build_api("youtubeAnalytics", "v2", credentials=creds)
            service = YouTubeAnalyticsService(client=client)
        else:
            from tube_scout.services.auth import build_analytics_client

            client = build_analytics_client()
            service = YouTubeAnalyticsService(client=client)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]OAuth authentication failed: {e}[/red]")
        raise typer.Exit(code=1)

    # Determine date range
    from datetime import date as date_type
    from datetime import timedelta

    end = date_type.today() - timedelta(days=3)  # 2-3 day data delay

    if start_date:
        start = date_type.fromisoformat(start_date)
    elif config.settings.analytics_start_date:
        start = date_type.fromisoformat(config.settings.analytics_start_date)
    else:
        start = end - timedelta(days=730)  # Default 2-year lookback

    report_types = [report_type] if report_type else None

    for channel_config in config.channels:
        channel_id = channel_config.channel_id

        # Incremental: adjust start date per report type
        actual_start = start
        if incremental:
            checkpoint = load_checkpoint(mgr.checkpoint_dir, channel_id, "analytics")
            if checkpoint and checkpoint.analytics_last_dates:
                last_dates = checkpoint.analytics_last_dates
                if report_type and report_type in last_dates:
                    last = date_type.fromisoformat(last_dates[report_type])
                    actual_start = last + timedelta(days=1)
                elif not report_type and last_dates:
                    dates = [
                        date_type.fromisoformat(d) for d in last_dates.values()
                    ]
                    actual_start = min(dates) + timedelta(days=1)

        if actual_start > end:
            console.print(
                f"[yellow]Analytics for {channel_id} already up to date.[/yellow]"
            )
            continue

        console.print(
            f"[bold]Collecting analytics for {channel_id} "
            f"({actual_start} to {end})...[/bold]"
        )

        # Save in-progress checkpoint
        state = load_checkpoint(
            mgr.checkpoint_dir, channel_id, "analytics"
        ) or CollectionState(
            channel_id=channel_id,
            phase="analytics",
            started_at=datetime.now(UTC),
            status="in_progress",
        )
        state.status = "in_progress"
        save_checkpoint(mgr.checkpoint_dir, state)

        try:
            result = service.collect_all_reports(
                channel_id=channel_id,
                start_date=actual_start,
                end_date=end,
                report_types=report_types,
                video_id=video_id,
            )

            # Store results
            analytics_dir = mgr.collect_dir / "analytics" / channel_id
            analytics_dir.mkdir(parents=True, exist_ok=True)

            collected_types: list[str] = []
            for rtype, data in result.items():
                if rtype == "errors" or not data:
                    continue
                collected_types.append(rtype)

                # Time-series data -> Parquet, dimensional -> JSON
                if rtype in ("daily_metrics", "subscriber_changes"):
                    df = pl.DataFrame(data)
                    write_parquet(analytics_dir / f"{rtype}.parquet", df)
                else:
                    write_json(analytics_dir / f"{rtype}.json", data)

            # Update checkpoint with last dates
            for rtype in collected_types:
                state.analytics_last_dates[rtype] = end.isoformat()
            state.status = "completed"
            state.updated_at = datetime.now(UTC)
            save_checkpoint(mgr.checkpoint_dir, state)

            # Report errors
            errors = result.get("errors", [])
            if errors:
                for err in errors:
                    console.print(
                        f"  [yellow]Warning: {err['report_type']}: "
                        f"{err['error']}[/yellow]"
                    )

            console.print(
                f"[green]Collected {len(collected_types)} analytics report type(s) "
                f"for {channel_id}.[/green]"
            )

        except PermissionError as e:
            state.status = "interrupted"
            state.updated_at = datetime.now(UTC)
            save_checkpoint(mgr.checkpoint_dir, state)
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)
        except Exception as e:
            error_msg = str(e)
            state.status = "interrupted"
            state.updated_at = datetime.now(UTC)
            save_checkpoint(mgr.checkpoint_dir, state)
            if "quota" in error_msg.lower():
                console.print(
                    "[red]YouTube API quota exhausted. "
                    "Retry after midnight Pacific Time.[/red]"
                )
                raise typer.Exit(code=2)
            console.print(f"[red]API error: {e}[/red]")
            raise typer.Exit(code=3)


def collect_all_command(
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
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Ignore checkpoints.",
    ),
) -> None:
    """Run all collection steps in sequence.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        force_refresh: Whether to ignore existing checkpoints.
    """
    mgr = resolve_project(project_dir, project)
    proj_path = str(mgr.project_dir)

    console.print("[bold]Running full collection pipeline...[/bold]\n")

    console.print("[bold cyan]Step 1/5: Collecting videos...[/bold cyan]")
    try:
        collect_videos_command(
            data_dir=data_dir,
            project_dir=project_dir,
            project=proj_path,
            force_refresh=force_refresh,
        )
    except SystemExit:
        pass

    console.print("\n[bold cyan]Step 2/5: Collecting comments...[/bold cyan]")
    try:
        collect_comments_command(
            data_dir=data_dir,
            project_dir=project_dir,
            project=proj_path,
        )
    except SystemExit:
        pass

    console.print("\n[bold cyan]Step 3/5: Collecting transcripts...[/bold cyan]")
    try:
        collect_transcripts_command(
            data_dir=data_dir,
            project_dir=project_dir,
            project=proj_path,
        )
    except SystemExit:
        pass

    console.print("\n[bold cyan]Step 4/5: Collecting retention data...[/bold cyan]")
    try:
        collect_retention_command(
            data_dir=data_dir,
            project_dir=project_dir,
            project=proj_path,
        )
    except SystemExit:
        pass

    console.print("\n[bold cyan]Step 5/5: Collecting analytics...[/bold cyan]")
    try:
        collect_analytics_command(
            data_dir=data_dir,
            project_dir=project_dir,
            project=proj_path,
        )
    except SystemExit:
        pass

    console.print("\n[bold green]Collection pipeline complete.[/bold green]")


def collect_bulk_command(
    report_type: str = typer.Option(
        ...,
        "--report-type",
        help="Reporting API report type ID (e.g., channel_basic_a2).",
    ),
    status: bool = typer.Option(
        False,
        "--status",
        help="Show status of existing jobs instead of creating new.",
    ),
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
    """Create or check bulk reporting jobs via YouTube Reporting API.

    Args:
        report_type: Reporting API report type ID.
        status: If True, show existing job status instead of creating.
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
    """
    mgr = resolve_project(project_dir, project)

    try:
        from tube_scout.services.auth import build_reporting_client

        client = build_reporting_client()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]OAuth authentication failed: {e}[/red]")
        raise typer.Exit(code=1)

    from tube_scout.services.youtube_reporting import YouTubeReportingService

    service = YouTubeReportingService(client=client)

    if status:
        console.print(f"[bold]Checking status for report type: {report_type}[/bold]")
        try:
            types = service.list_report_types()
            console.print(f"  Available report types: {len(types)}")
            for rt in types:
                console.print(
                    f"    - {rt.get('id', 'unknown')}: {rt.get('name', '')}"
                )
        except Exception as e:
            console.print(f"[red]Error listing report types: {e}[/red]")
            raise typer.Exit(code=1)
        return

    console.print(f"[bold]Creating bulk reporting job: {report_type}[/bold]")
    try:
        job = service.create_job(report_type)
        console.print(
            f"  [green]Job created: {job.job_id} (status: {job.status})[/green]"
        )
        console.print(
            "  Use 'tube-scout collect bulk --report-type "
            f"{report_type} --status' to check progress."
        )

        from tube_scout.storage.json_store import write_json

        jobs_dir = mgr.collect_dir / "reporting"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            jobs_dir / f"job_{job.job_id}.json",
            job.model_dump(mode="json"),
        )
    except (PermissionError, RuntimeError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
