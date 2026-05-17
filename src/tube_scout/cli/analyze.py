"""Analyze subcommands for tube-scout."""

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tube_scout.cli.progress import create_progress
from tube_scout.cli.project import is_producer, resolve_project
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import read_parquet, write_parquet

_logger = logging.getLogger(__name__)

console = Console()


def analyze_retention_command(
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
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Analyze retention data to detect hotspots and skip zones.

    Args:
        data_dir: User data directory path (config, credentials).
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.youtube_analytics import (
        detect_rewatch_hotspots,
        detect_skip_zones,
    )

    Path(data_dir)
    mgr = resolve_project(project_dir, project, producer=is_producer("analyze"))
    retention_dir = mgr.collect_dir / "retention"

    if not retention_dir.exists():
        console.print(
            "[red]No retention data found. "
            "Run 'tube-scout collect retention' first.[/red]"
        )
        raise typer.Exit(code=1)

    files = (
        [retention_dir / f"{video_id}.parquet"]
        if video_id
        else list(retention_dir.glob("*.parquet"))
    )

    if not files:
        console.print("[yellow]No retention data files found.[/yellow]")
        raise typer.Exit(code=1)

    with create_progress() as progress:
        task = progress.add_task("Analyzing retention", total=len(files))
        for filepath in files:
            if not filepath.exists():
                progress.console.print(
                    f"[yellow]No retention data for {filepath.stem}[/yellow]"
                )
                progress.advance(task)
                continue

            df = read_parquet(filepath)
            if df is None:
                # idea6 FR-IDEA6-010 SILENT-13 fix (treatment b):
                _logger.warning(
                    "skip retention parquet (read_parquet returned None): %s",
                    filepath,
                )
                # intentional-skip: corrupt parquet — logged + counted as skipped
                progress.advance(task)
                continue

            vid = filepath.stem
            retention = df.to_dicts()

            hotspots = detect_rewatch_hotspots(retention)
            skips = detect_skip_zones(retention)

            # Save analysis results
            results = {
                "video_id": vid,
                "hotspots": hotspots,
                "skip_zones": skips,
                "total_data_points": len(retention),
            }
            results_dir = mgr.analyze_dir / "retention"
            results_dir.mkdir(parents=True, exist_ok=True)
            write_json(results_dir / f"{vid}.json", results)

            # Display results
            table = Table(title=f"Retention Analysis: {vid}")
            table.add_column("Type", style="cyan")
            table.add_column("Position", style="yellow")
            table.add_column("Watch Ratio", style="green")

            for h in hotspots:
                table.add_row(
                    "Hotspot",
                    f"{h['elapsed_ratio']:.1%}",
                    f"{h['audience_watch_ratio']:.2f}",
                )
            for s in skips:
                table.add_row(
                    "Skip Zone",
                    f"{s['elapsed_ratio']:.1%}",
                    f"{s['audience_watch_ratio']:.2f}",
                )

            if not hotspots and not skips:
                progress.console.print(
                    f"  [green]{vid}: No significant hotspots "
                    "or skip zones detected.[/green]"
                )
            else:
                progress.console.print(table)
            progress.advance(task)


def analyze_sentiment_command(
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
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
    sentiment_backend: str = typer.Option(
        "llm",
        "--sentiment-backend",
        help="Backend: llm (cloud LLM) or local (on-device NLP).",
    ),
) -> None:
    """Analyze comment sentiment, topics, and questions.

    Args:
        data_dir: User data directory path (config, credentials).
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
        sentiment_backend: Analysis backend to use.
    """
    import polars as pl

    from tube_scout.services.sentiment import SentimentService

    Path(data_dir)
    mgr = resolve_project(project_dir, project, producer=is_producer("analyze"))
    comments_dir = mgr.collect_dir / "comments"

    if not comments_dir.exists():
        console.print(
            "[red]No comment data found. Run 'tube-scout collect comments' first.[/red]"
        )
        raise typer.Exit(code=1)

    files = (
        [comments_dir / f"{video_id}.json"]
        if video_id
        else list(comments_dir.glob("*.json"))
    )

    if not files:
        console.print("[yellow]No comment data files found.[/yellow]")
        raise typer.Exit(code=1)

    service = SentimentService(backend=sentiment_backend)

    with create_progress() as progress:
        task = progress.add_task("Analyzing sentiment", total=len(files))
        for filepath in files:
            if not filepath.exists():
                progress.console.print(
                    f"[yellow]No comments for {filepath.stem}[/yellow]"
                )
                progress.advance(task)
                continue

            comments_data = read_json(filepath)
            if not comments_data:
                progress.advance(task)
                continue

            vid = filepath.stem
            comments = comments_data if isinstance(comments_data, list) else []

            try:
                results = service.analyze_batch(comments)
            except NotImplementedError as e:
                progress.console.print(f"[yellow]{vid}: {e}[/yellow]")
                progress.advance(task)
                continue

            # Save results
            output_dir = mgr.analyze_dir / "sentiment"
            output_dir.mkdir(parents=True, exist_ok=True)

            if results:
                df = pl.DataFrame(results)
                write_parquet(output_dir / f"{vid}.parquet", df)

            # Display summary
            questions = [r for r in results if r.get("is_question")]
            progress.console.print(
                f"  [green]{vid}: {len(results)} comments analyzed, "
                f"{len(questions)} questions found[/green]"
            )
            progress.advance(task)


def analyze_topic_command(
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
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Extract topics and questions from comments, cross-reference with hotspots.

    Args:
        data_dir: User data directory path (config, credentials).
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.topic_extractor import TopicExtractorService

    Path(data_dir)
    mgr = resolve_project(project_dir, project, producer=is_producer("analyze"))
    comments_dir = mgr.collect_dir / "comments"

    if not comments_dir.exists():
        console.print(
            "[red]No comment data found. Run 'tube-scout collect comments' first.[/red]"
        )
        raise typer.Exit(code=1)

    files = (
        [comments_dir / f"{video_id}.json"]
        if video_id
        else list(comments_dir.glob("*.json"))
    )

    if not files:
        console.print("[yellow]No comment data files found.[/yellow]")
        raise typer.Exit(code=1)

    service = TopicExtractorService()

    with create_progress() as progress:
        task = progress.add_task("Extracting topics", total=len(files))
        for filepath in files:
            if not filepath.exists():
                progress.console.print(
                    f"[yellow]No comments for {filepath.stem}[/yellow]"
                )
                progress.advance(task)
                continue

            comments_data = read_json(filepath)
            if not comments_data:
                progress.advance(task)
                continue

            vid = filepath.stem
            comments = comments_data if isinstance(comments_data, list) else []

            try:
                clusters = service.extract_topics(vid, comments)
                questions = service.extract_questions(vid, comments)
            except ValueError as e:
                progress.console.print(f"[yellow]{vid}: {e}[/yellow]")
                progress.advance(task)
                continue

            # Load hotspots for cross-reference if available
            retention_path = mgr.analyze_dir / "retention" / f"{vid}.json"
            retention_data = read_json(retention_path) or {}
            hotspots = retention_data.get("hotspots", [])

            matches: list[dict] = []
            if hotspots and questions:
                try:
                    matches = service.cross_reference_with_hotspots(
                        vid, comments, hotspots
                    )
                except ValueError:
                    pass

            # Save results
            topics_dir = mgr.analyze_dir / "topics"
            topics_dir.mkdir(parents=True, exist_ok=True)
            write_json(topics_dir / f"{vid}.json", clusters)

            questions_dir = mgr.analyze_dir / "questions"
            questions_dir.mkdir(parents=True, exist_ok=True)
            write_json(
                questions_dir / f"{vid}.json",
                {
                    "questions": questions,
                    "hotspot_matches": matches,
                },
            )

            # Display topic summary
            table = Table(title=f"Topic Clusters: {vid}")
            table.add_column("Topic", style="cyan")
            table.add_column("Comments", style="yellow")
            table.add_column("Sentiment", style="green")

            for cluster in clusters:
                dist = cluster.get("sentiment_distribution", {})
                sentiment_str = ", ".join(
                    f"{k}: {v:.0%}" for k, v in dist.items() if v > 0
                )
                table.add_row(
                    cluster["topic_label"],
                    str(len(cluster["comment_ids"])),
                    sentiment_str,
                )

            if clusters:
                progress.console.print(table)

            progress.console.print(
                f"  [green]{vid}: {len(clusters)} topics, "
                f"{len(questions)} questions, "
                f"{len(matches)} hotspot matches[/green]"
            )
            progress.advance(task)


def analyze_transcript_command(
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
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Analyze transcripts: chapter splitting, summary, difficulty scoring.

    Args:
        data_dir: User data directory path (config, credentials).
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.segmenter import SegmenterService

    Path(data_dir)
    mgr = resolve_project(project_dir, project, producer=is_producer("analyze"))
    transcripts_dir = mgr.collect_dir / "transcripts"

    if not transcripts_dir.exists():
        console.print(
            "[red]No transcript data found. "
            "Run 'tube-scout collect transcripts' first.[/red]"
        )
        raise typer.Exit(code=1)

    files = (
        [transcripts_dir / f"{video_id}.json"]
        if video_id
        else list(transcripts_dir.glob("*.json"))
    )

    if not files:
        console.print("[yellow]No transcript files found.[/yellow]")
        raise typer.Exit(code=1)

    service = SegmenterService()

    with create_progress() as progress:
        task = progress.add_task("Analyzing transcripts", total=len(files))
        for filepath in files:
            if not filepath.exists():
                progress.console.print(
                    f"[yellow]No transcript for {filepath.stem}[/yellow]"
                )
                progress.advance(task)
                continue

            transcript_data = read_json(filepath)
            if not transcript_data:
                progress.advance(task)
                continue

            vid = filepath.stem
            segments = transcript_data.get("segments", [])
            full_text = " ".join(s.get("text", "") for s in segments)

            try:
                result = service.segment_transcript(
                    video_id=vid,
                    transcript_text=full_text,
                )
            except NotImplementedError as e:
                progress.console.print(f"[yellow]{vid}: {e}[/yellow]")
                progress.advance(task)
                continue

            # Save results
            output_dir = mgr.analyze_dir / "segments"
            output_dir.mkdir(parents=True, exist_ok=True)
            write_json(output_dir / f"{vid}.json", result)

            # Display as table
            table = Table(title=f"Transcript Segments: {vid}")
            table.add_column("#", style="cyan")
            table.add_column("Title", style="white")
            table.add_column("Time", style="green")
            table.add_column("Difficulty", style="yellow")

            for seg in result:
                start = seg.get("start_seconds", 0)
                end = seg.get("end_seconds", 0)
                s_min, s_sec = int(start // 60), int(start % 60)
                e_min, e_sec = int(end // 60), int(end % 60)
                table.add_row(
                    str(seg.get("segment_index", 0)),
                    seg.get("title", "?"),
                    f"{s_min}:{s_sec:02d}-{e_min}:{e_sec:02d}",
                    f"{seg.get('difficulty_score', 0):.1f}",
                )

            progress.console.print(table)
            progress.advance(task)


def analyze_eqs_command(
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
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Evaluate Education Quality Score (RACED 5-axis) for videos.

    Args:
        data_dir: User data directory path (config, credentials).
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.eqs import EQSService

    Path(data_dir)
    mgr = resolve_project(project_dir, project, producer=is_producer("analyze"))
    transcripts_dir = mgr.collect_dir / "transcripts"

    if not transcripts_dir.exists():
        console.print(
            "[red]No transcript data found. "
            "Run 'tube-scout collect transcripts' first.[/red]"
        )
        raise typer.Exit(code=1)

    files = (
        [transcripts_dir / f"{video_id}.json"]
        if video_id
        else list(transcripts_dir.glob("*.json"))
    )

    service = EQSService()

    with create_progress() as progress:
        task = progress.add_task("Evaluating EQS", total=len(files))
        for filepath in files:
            if not filepath.exists():
                progress.advance(task)
                continue

            transcript_data = read_json(filepath)
            if not transcript_data:
                progress.advance(task)
                continue

            vid = filepath.stem
            segments = transcript_data.get("segments", [])
            full_text = " ".join(s.get("text", "") for s in segments)

            retention_path = mgr.analyze_dir / "retention" / f"{vid}.json"
            retention_data = read_json(retention_path) or {}

            try:
                result = service.evaluate(
                    video_id=vid,
                    transcript_text=full_text,
                    retention_data=retention_data.get("hotspots", []),
                    comment_data=[],
                )
            except NotImplementedError as e:
                progress.console.print(f"[yellow]{vid}: {e}[/yellow]")
                progress.advance(task)
                continue

            # Save results
            eqs_dir = mgr.analyze_dir / "eqs"
            eqs_dir.mkdir(parents=True, exist_ok=True)
            write_json(eqs_dir / f"{vid}.json", result)

            # Display
            table = Table(title=f"EQS: {vid}")
            table.add_column("Axis", style="cyan")
            table.add_column("Score", style="green")

            for axis in ["relevance", "accuracy", "clarity", "engagement", "depth"]:
                table.add_row(axis.capitalize(), f"{result.get(axis, 0):.2f}")
            table.add_row("Overall", f"{result.get('overall', 0):.2f}", style="bold")
            progress.console.print(table)
            progress.advance(task)


def analyze_forecast_command(
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
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Forecast for a specific video.",
    ),
    model: str = typer.Option(
        "auto",
        "--model",
        help="Model: auto (default) | linear | arima | prophet.",
    ),
    calendar: str | None = typer.Option(
        None,
        "--calendar",
        help="Path to academic calendar JSON file.",
    ),
    horizon_days: int = typer.Option(
        30,
        "--horizon-days",
        help="Forecast horizon in days.",
    ),
) -> None:
    """Run time series forecasting and anomaly detection.

    Args:
        data_dir: User data directory path (config, credentials).
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
        model: Forecasting model to use.
        calendar: Optional path to academic calendar JSON.
        horizon_days: Number of days to forecast.
    """
    from tube_scout.services.forecaster import ForecasterService

    data_path = Path(data_dir)
    mgr = resolve_project(project_dir, project, producer=is_producer("analyze"))
    config_data = read_json(data_path / "config.json")
    if config_data is None:
        console.print("[red]No configuration found.[/red]")
        raise typer.Exit(code=1)

    from tube_scout.models.config import AppConfig

    config = AppConfig(**config_data)
    service = ForecasterService()

    # Load calendar events
    calendar_events = None
    if calendar:
        cal_data = read_json(Path(calendar))
        if cal_data:
            calendar_events = cal_data.get("events", [])
    else:
        # Try loading from default location
        cal_data = read_json(data_path / "calendar.json")
        if cal_data:
            calendar_events = cal_data.get("events", [])

    for channel_config in config.channels:
        channel_id = channel_config.channel_id

        # Prefer daily_metrics from analytics (US1) over video-level data
        historical = _load_daily_metrics(mgr.collect_dir, channel_id)

        if not historical:
            # Fallback to video publish dates and view counts
            historical = _load_video_time_series(mgr.collect_dir, channel_id)

        if not historical:
            console.print(
                f"[yellow]No time-series data for {channel_id}. "
                "Run 'tube-scout collect analytics' or "
                "'tube-scout collect videos' first.[/yellow]"
            )
            continue

        historical.sort(key=lambda x: x["date"])

        try:
            forecasts = service.predict(
                channel_id=channel_id,
                metric_name="view_count",
                historical_data=historical,
                horizon_days=horizon_days,
                model=model,
                calendar_events=calendar_events,
            )
        except ValueError as e:
            console.print(f"[yellow]{channel_id}: {e}[/yellow]")
            continue

        # Save
        forecast_dir = mgr.analyze_dir / "forecast"
        forecast_dir.mkdir(parents=True, exist_ok=True)
        write_json(forecast_dir / f"{channel_id}_view_count.json", forecasts)

        # Anomaly detection
        anomalies = service.detect_anomalies(historical)
        anomaly_count = sum(1 for a in anomalies if a["is_anomaly"])

        model_used = forecasts[0].get("model_used", model) if forecasts else model
        console.print(
            f"[green]{channel_id}: {len(forecasts)} days forecasted "
            f"(model={model_used}), "
            f"{anomaly_count} anomalies detected[/green]"
        )


def _load_daily_metrics(collect_dir: Path, channel_id: str) -> list[dict[str, object]]:
    """Load daily metrics from analytics Parquet data (T071).

    Args:
        collect_dir: Project collect directory.
        channel_id: YouTube channel ID.

    Returns:
        List of dicts with 'date' (ordinal) and 'value'.
    """
    from tube_scout.storage.parquet_store import read_parquet

    parquet_path = collect_dir / "analytics" / channel_id / "daily_metrics.parquet"
    df = read_parquet(parquet_path)
    if df is None:
        return []

    from datetime import date as dt_date

    result = []
    for row in df.to_dicts():
        try:
            d = dt_date.fromisoformat(str(row["date"]))
            result.append({
                "date": d.toordinal(),
                "value": row.get("views", 0),
            })
        except (ValueError, TypeError, KeyError):
            continue
    return result


def _load_video_time_series(
    collect_dir: Path, channel_id: str
) -> list[dict[str, object]]:
    """Load time series from video metadata (legacy fallback).

    Args:
        collect_dir: Project collect directory.
        channel_id: YouTube channel ID.

    Returns:
        List of dicts with 'date' (ordinal) and 'value'.
    """
    from datetime import date as dt_date

    videos_path = collect_dir / "channels" / channel_id / "videos_meta.json"
    videos_data = read_json(videos_path)
    if not videos_data:
        return []

    videos = (
        videos_data if isinstance(videos_data, list) else videos_data.get("videos", [])
    )

    result = []
    for v in videos:
        if v.get("published_at") and v.get("view_count"):
            pub = v["published_at"][:10]
            try:
                d = dt_date.fromisoformat(pub)
                result.append({
                    "date": d.toordinal(),
                    "value": v["view_count"],
                })
            except (ValueError, TypeError):
                continue
    return result


def analyze_all_command(
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
    sentiment_backend: str = typer.Option(
        "llm",
        "--sentiment-backend",
        help="Backend: llm (cloud LLM) or local (on-device NLP).",
    ),
) -> None:
    """Run all analysis steps in sequence.

    Args:
        data_dir: User data directory path (config, credentials).
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        sentiment_backend: Sentiment analysis backend.
    """
    mgr = resolve_project(project_dir, project, producer=is_producer("analyze"))
    project_path = str(mgr.project_dir)

    console.print("[bold]Running full analysis pipeline...[/bold]\n")

    steps = [
        (
            "Sentiment analysis",
            lambda: analyze_sentiment_command(
                data_dir=data_dir,
                project_dir=project_dir,
                project=project_path,
                sentiment_backend=sentiment_backend,
            ),
        ),
        (
            "Topic extraction",
            lambda: analyze_topic_command(
                data_dir=data_dir,
                project_dir=project_dir,
                project=project_path,
            ),
        ),
        (
            "Transcript analysis",
            lambda: analyze_transcript_command(
                data_dir=data_dir,
                project_dir=project_dir,
                project=project_path,
            ),
        ),
        (
            "Retention analysis",
            lambda: analyze_retention_command(
                data_dir=data_dir,
                project_dir=project_dir,
                project=project_path,
            ),
        ),
        (
            "EQS scoring",
            lambda: analyze_eqs_command(
                data_dir=data_dir,
                project_dir=project_dir,
                project=project_path,
            ),
        ),
        (
            "Forecasting",
            lambda: analyze_forecast_command(
                data_dir=data_dir,
                project_dir=project_dir,
                project=project_path,
            ),
        ),
    ]

    from tube_scout.cli.errors import UserFacingError, render_error

    for i, (name, fn) in enumerate(steps, 1):
        console.print(f"\n[bold cyan]Step {i}/{len(steps)}: {name}...[/bold cyan]")
        try:
            fn()
        except SystemExit as exc:
            # idea6 ADR-IDEA6-008 / FR-IDEA6-010 / SILENT-4 fix:
            # SystemExit code != 0 means a downstream stage signalled
            # failure. Surface it through ActionableError + non-zero exit
            # rather than absorbing and reporting "Analysis pipeline complete".
            code = getattr(exc, "code", 0)
            if code:
                err = UserFacingError(
                    message=(
                        f"Analysis stage {i}/{len(steps)} '{name}' failed "
                        f"(exit_code={code}). Pipeline aborted; subsequent "
                        "stages were not run."
                    ),
                    next_command=(
                        "Inspect the error above and re-run the failing stage "
                        "individually, e.g. `tube-scout analyze "
                        f"{name.lower().split()[0]}`"
                    ),
                )
                render_error(err)
                raise err

    console.print("\n[bold green]Analysis pipeline complete.[/bold green]")


def analyze_content_reuse_command(
    channel: str = typer.Option(..., "--channel", help="Channel alias to analyze."),
    professor: str = typer.Option(
        ..., "--professor", help="Professor pool identifier."
    ),
    mode: str = typer.Option(
        "M-default",
        "--mode",
        help="Matching mode: M-default or M-nC2.",
    ),
    layer_a_seconds: float = typer.Option(
        30.0,
        "--layer-a-seconds",
        help="Layer A minimum video duration (seconds).",
    ),
    layer_b_threshold: float = typer.Option(
        0.30,
        "--layer-b-threshold",
        help="Layer B baseline n-gram frequency threshold.",
    ),
    resume: bool = typer.Option(
        False, "--resume/--no-resume", help="Skip already-analyzed pairs."
    ),
    force: bool = typer.Option(False, "--force", help="Re-analyze even if done."),
    db_path: str = typer.Option(
        "./data/content_reuse.db",
        "--db-path",
        help="Path to content_reuse.db SQLite file.",
    ),
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help=(
            "Collect data root (parent of channel work dirs). When provided, "
            "Layer B match_spans persistence resolves transcripts at "
            "<data-dir>/<channel_alias>/02_analyze/transcripts/<video_id>.json "
            "per spec 018 atomic-write layout. Without --data-dir the analysis "
            "still runs but match_spans persistence is skipped."
        ),
    ),
) -> None:
    """Run nC2 reuse analysis for a professor's video pool.

    Args:
        channel: Channel alias.
        professor: Professor pool identifier.
        mode: Matching mode (M-default or M-nC2).
        layer_a_seconds: Minimum video duration for pairing.
        layer_b_threshold: Layer B n-gram threshold.
        resume: Skip already-analyzed pairs.
        force: Re-analyze even if done.
        db_path: Path to SQLite database.
        data_dir: Collect data root used to resolve per-video transcript
            paths for Layer B match_spans persistence (spec 013 T068).
    """

    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import (
        ContentDB,
    )

    if mode not in ("M-default", "M-nC2"):
        console.print(f"[red]Invalid mode '{mode}'. Must be M-default or M-nC2.[/red]")
        raise typer.Exit(code=1)

    resolved_db = Path(db_path)
    resolved_db.parent.mkdir(parents=True, exist_ok=True)
    resolved_data_dir = Path(data_dir) if data_dir else None

    db = ContentDB(resolved_db)
    try:
        result = run_nc2_analysis(
            professor=professor,
            channel_alias=channel,
            db=db,
            matching_mode=mode,  # type: ignore[arg-type]
            layer_a_min_seconds=layer_a_seconds,
            layer_b_threshold=layer_b_threshold,
            resume=resume,
            force=force,
            data_dir=resolved_data_dir,
        )
    finally:
        db.close()

    console.print(f"[green]Analysis complete:[/green] professor={result.professor}")
    console.print(f"  total_pairs_generated : {result.total_pairs_generated}")
    console.print(f"  pairs_culled_layer_a  : {result.pairs_culled_layer_a}")
    console.print(f"  pairs_analyzed        : {result.pairs_analyzed}")
    console.print(f"  pairs_failed          : {result.pairs_failed}")
    console.print(f"  elapsed_seconds       : {result.elapsed_seconds:.2f}")
