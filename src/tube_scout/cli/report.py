"""Report generation CLI commands."""

from pathlib import Path

import typer
from rich.console import Console

from tube_scout.models.config import AppConfig
from tube_scout.reporting.channel_report import ChannelReportGenerator
from tube_scout.reporting.video_report import VideoReportGenerator
from tube_scout.storage.json_store import read_json

console = Console()


def _load_config(data_dir: Path) -> AppConfig:
    """Load config from data directory."""
    config_data = read_json(data_dir / "config.json")
    if config_data is None:
        console.print("[red]No configuration found. Run 'tube-scout init' first.[/red]")
        raise typer.Exit(code=1)
    return AppConfig(**config_data)


def report_video_command(
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
    format: str = typer.Option(
        "html",
        "--format",
        help="Output format: html/notebook.",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        help="Output directory.",
    ),
) -> None:
    """Generate a video analysis report.

    Args:
        data_dir: Data storage directory.
        video_id: Specific video ID, or generate for all.
        format: Output format.
        output_dir: Custom output directory.
    """
    data_path = Path(data_dir)
    config = _load_config(data_path)
    out_dir = Path(output_dir) if output_dir else data_path / "reports" / "video"

    for channel_config in config.channels:
        vid_ids = []
        if video_id:
            vid_ids = [video_id]
        else:
            videos_path = (
                data_path
                / "raw"
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos = read_json(videos_path)
            if not videos:
                console.print(
                    f"[yellow]No videos for {channel_config.channel_id}[/yellow]"
                )
                continue
            vlist = videos if isinstance(videos, list) else videos.get("videos", [])
            vid_ids = [v["video_id"] for v in vlist]

        for vid in vid_ids:
            path = _generate_video_report(
                data_path=data_path,
                video_id=vid,
                channel_id=channel_config.channel_id,
                output_dir=out_dir,
                fmt=format,
            )
            console.print(f"[green]Report generated: {path}[/green]")


def _generate_video_report(
    data_path: Path,
    video_id: str,
    channel_id: str,
    output_dir: Path,
    fmt: str,
) -> Path:
    """Generate a single video report in the specified format.

    Args:
        data_path: Root data directory.
        video_id: YouTube video ID.
        channel_id: YouTube channel ID.
        output_dir: Output directory.
        fmt: Output format ('html' or 'notebook').

    Returns:
        Path to the generated file.
    """
    if fmt == "notebook":
        from tube_scout.reporting.notebook_export import (
            VideoNotebookExporter,
        )

        gen = VideoReportGenerator(data_dir=data_path)
        video = gen._load_video_meta(video_id, channel_id)
        retention = gen._load_retention(video_id)
        segments = gen._load_segments(video_id)

        exporter = VideoNotebookExporter()
        return exporter.export(
            video=video,
            retention=retention,
            segments=segments,
            output_dir=output_dir,
        )

    generator = VideoReportGenerator(data_dir=data_path)
    return generator.generate(
        video_id=video_id,
        channel_id=channel_id,
        output_dir=output_dir,
    )


def report_channel_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    format: str = typer.Option(
        "html",
        "--format",
        help="Output format: html/notebook.",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        help="Output directory.",
    ),
) -> None:
    """Generate a channel analysis report.

    Args:
        data_dir: Data storage directory.
        format: Output format.
        output_dir: Custom output directory.
    """
    data_path = Path(data_dir)
    config = _load_config(data_path)
    out_dir = Path(output_dir) if output_dir else data_path / "reports" / "channel"

    generator = ChannelReportGenerator(data_dir=data_path)

    for channel_config in config.channels:
        path = generator.generate(
            channel_id=channel_config.channel_id,
            output_dir=out_dir,
        )
        console.print(f"[green]Channel report generated: {path}[/green]")
