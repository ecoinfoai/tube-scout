"""Analyze subcommands for tube-scout."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import read_parquet, write_parquet

console = Console()


def analyze_retention_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Analyze retention data to detect hotspots and skip zones.

    Args:
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.youtube_analytics import (
        detect_rewatch_hotspots,
        detect_skip_zones,
    )

    data_path = Path(data_dir)
    retention_dir = data_path / "raw" / "retention"

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

    for filepath in files:
        if not filepath.exists():
            console.print(f"[yellow]No retention data for {filepath.stem}[/yellow]")
            continue

        df = read_parquet(filepath)
        if df is None:
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
        results_dir = data_path / "processed" / "retention"
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
            console.print(
                f"  [green]{vid}: No significant hotspots "
                "or skip zones detected.[/green]"
            )
        else:
            console.print(table)


def analyze_sentiment_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
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
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
        sentiment_backend: Analysis backend to use.
    """
    import polars as pl

    from tube_scout.services.sentiment import SentimentService

    data_path = Path(data_dir)
    comments_dir = data_path / "raw" / "comments"

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

    for filepath in files:
        if not filepath.exists():
            console.print(f"[yellow]No comments for {filepath.stem}[/yellow]")
            continue

        comments_data = read_json(filepath)
        if not comments_data:
            continue

        vid = filepath.stem
        comments = comments_data if isinstance(comments_data, list) else []

        try:
            results = service.analyze_batch(comments)
        except NotImplementedError as e:
            console.print(f"[yellow]{vid}: {e}[/yellow]")
            continue

        # Save results
        output_dir = data_path / "processed" / "sentiment"
        output_dir.mkdir(parents=True, exist_ok=True)

        if results:
            df = pl.DataFrame(results)
            write_parquet(output_dir / f"{vid}.parquet", df)

        # Display summary
        questions = [r for r in results if r.get("is_question")]
        console.print(
            f"  [green]{vid}: {len(results)} comments analyzed, "
            f"{len(questions)} questions found[/green]"
        )


def analyze_topic_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Extract topics and questions from comments, cross-reference with hotspots.

    Args:
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.topic_extractor import TopicExtractorService

    data_path = Path(data_dir)
    comments_dir = data_path / "raw" / "comments"

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

    for filepath in files:
        if not filepath.exists():
            console.print(f"[yellow]No comments for {filepath.stem}[/yellow]")
            continue

        comments_data = read_json(filepath)
        if not comments_data:
            continue

        vid = filepath.stem
        comments = comments_data if isinstance(comments_data, list) else []

        try:
            clusters = service.extract_topics(vid, comments)
            questions = service.extract_questions(vid, comments)
        except ValueError as e:
            console.print(f"[yellow]{vid}: {e}[/yellow]")
            continue

        # Load hotspots for cross-reference if available
        retention_path = data_path / "processed" / "retention" / f"{vid}.json"
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
        topics_dir = data_path / "processed" / "topics"
        topics_dir.mkdir(parents=True, exist_ok=True)
        write_json(topics_dir / f"{vid}.json", clusters)

        questions_dir = data_path / "processed" / "questions"
        questions_dir.mkdir(parents=True, exist_ok=True)
        write_json(questions_dir / f"{vid}.json", {
            "questions": questions,
            "hotspot_matches": matches,
        })

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
            console.print(table)

        console.print(
            f"  [green]{vid}: {len(clusters)} topics, "
            f"{len(questions)} questions, "
            f"{len(matches)} hotspot matches[/green]"
        )


def analyze_transcript_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Analyze transcripts: chapter splitting, summary, difficulty scoring.

    Args:
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.segmenter import SegmenterService

    data_path = Path(data_dir)
    transcripts_dir = data_path / "raw" / "transcripts"

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

    for filepath in files:
        if not filepath.exists():
            console.print(f"[yellow]No transcript for {filepath.stem}[/yellow]")
            continue

        transcript_data = read_json(filepath)
        if not transcript_data:
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
            console.print(f"[yellow]{vid}: {e}[/yellow]")
            continue

        # Save results
        output_dir = data_path / "processed" / "segments"
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

        console.print(table)


def analyze_eqs_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Specific video ID.",
    ),
) -> None:
    """Evaluate Education Quality Score (RACED 5-axis) for videos.

    Args:
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
    """
    from tube_scout.services.eqs import EQSService

    data_path = Path(data_dir)
    transcripts_dir = data_path / "raw" / "transcripts"

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

    for filepath in files:
        if not filepath.exists():
            continue

        transcript_data = read_json(filepath)
        if not transcript_data:
            continue

        vid = filepath.stem
        segments = transcript_data.get("segments", [])
        full_text = " ".join(s.get("text", "") for s in segments)

        retention_path = data_path / "processed" / "retention" / f"{vid}.json"
        retention_data = read_json(retention_path) or {}

        try:
            result = service.evaluate(
                video_id=vid,
                transcript_text=full_text,
                retention_data=retention_data.get("hotspots", []),
                comment_data=[],
            )
        except NotImplementedError as e:
            console.print(f"[yellow]{vid}: {e}[/yellow]")
            continue

        # Save results
        eqs_dir = data_path / "processed" / "eqs"
        eqs_dir.mkdir(parents=True, exist_ok=True)
        write_json(eqs_dir / f"{vid}.json", result)

        # Display
        table = Table(title=f"EQS: {vid}")
        table.add_column("Axis", style="cyan")
        table.add_column("Score", style="green")

        for axis in ["relevance", "accuracy", "clarity", "engagement", "depth"]:
            table.add_row(axis.capitalize(), f"{result.get(axis, 0):.2f}")
        table.add_row("Overall", f"{result.get('overall', 0):.2f}", style="bold")
        console.print(table)


def analyze_forecast_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
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
        data_dir: Data storage directory path.
        video_id: Optional specific video ID.
        model: Forecasting model to use.
        calendar: Optional path to academic calendar JSON.
        horizon_days: Number of days to forecast.
    """
    from tube_scout.services.forecaster import ForecasterService

    data_path = Path(data_dir)
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
        historical = _load_daily_metrics(data_path, channel_id)

        if not historical:
            # Fallback to video publish dates and view counts
            historical = _load_video_time_series(data_path, channel_id)

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
        forecast_dir = data_path / "processed" / "forecast"
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


def _load_daily_metrics(
    data_path: Path, channel_id: str
) -> list[dict[str, object]]:
    """Load daily metrics from analytics Parquet data (T071).

    Args:
        data_path: Root data directory.
        channel_id: YouTube channel ID.

    Returns:
        List of dicts with 'date' (ordinal) and 'value'.
    """
    from tube_scout.storage.parquet_store import read_parquet

    parquet_path = (
        data_path / "raw" / "analytics" / channel_id / "daily_metrics.parquet"
    )
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
    data_path: Path, channel_id: str
) -> list[dict[str, object]]:
    """Load time series from video metadata (legacy fallback).

    Args:
        data_path: Root data directory.
        channel_id: YouTube channel ID.

    Returns:
        List of dicts with 'date' (ordinal) and 'value'.
    """
    from datetime import date as dt_date

    videos_path = data_path / "raw" / "channels" / channel_id / "videos_meta.json"
    videos_data = read_json(videos_path)
    if not videos_data:
        return []

    videos = (
        videos_data
        if isinstance(videos_data, list)
        else videos_data.get("videos", [])
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
        help="Data storage directory.",
    ),
    sentiment_backend: str = typer.Option(
        "llm",
        "--sentiment-backend",
        help="Backend: llm (cloud LLM) or local (on-device NLP).",
    ),
) -> None:
    """Run all analysis steps in sequence.

    Args:
        data_dir: Data storage directory path.
        sentiment_backend: Sentiment analysis backend.
    """
    console.print("[bold]Running full analysis pipeline...[/bold]\n")

    steps = [
        (
            "Sentiment analysis",
            lambda: analyze_sentiment_command(
                data_dir=data_dir,
                sentiment_backend=sentiment_backend,
            ),
        ),
        ("Topic extraction", lambda: analyze_topic_command(data_dir=data_dir)),
        ("Transcript analysis", lambda: analyze_transcript_command(data_dir=data_dir)),
        ("Retention analysis", lambda: analyze_retention_command(data_dir=data_dir)),
        ("EQS scoring", lambda: analyze_eqs_command(data_dir=data_dir)),
        ("Forecasting", lambda: analyze_forecast_command(data_dir=data_dir)),
    ]

    for i, (name, fn) in enumerate(steps, 1):
        console.print(f"\n[bold cyan]Step {i}/{len(steps)}: {name}...[/bold cyan]")
        try:
            fn()
        except SystemExit:
            pass

    console.print("\n[bold green]Analysis pipeline complete.[/bold green]")
