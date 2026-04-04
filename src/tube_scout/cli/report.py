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


def report_comment_insight_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
    video_id: str = typer.Option(
        ...,
        "--video-id",
        help="Video ID to generate comment insight report for.",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        help="Output directory.",
    ),
) -> None:
    """Generate a comment insight report with topic summaries and FAQ.

    Args:
        data_dir: Data storage directory.
        video_id: Video ID (required).
        output_dir: Custom output directory.
    """
    from tube_scout.reporting.comment_report import CommentReportGenerator

    data_path = Path(data_dir)
    out_dir = (
        Path(output_dir)
        if output_dir
        else data_path / "reports" / "comment_insight"
    )

    # Load topic clusters
    topics_path = data_path / "processed" / "topics" / f"{video_id}.json"
    topics = read_json(topics_path)
    if topics is None:
        console.print(
            f"[red]No topic data for {video_id}. "
            "Run 'tube-scout analyze topic' first.[/red]"
        )
        raise typer.Exit(code=1)
    topics_list = topics if isinstance(topics, list) else []

    # Load questions
    questions_path = data_path / "processed" / "questions" / f"{video_id}.json"
    questions_data = read_json(questions_path) or {
        "questions": [],
        "hotspot_matches": [],
    }

    # Load video metadata (best-effort)
    video_meta: dict = {"video_id": video_id, "title": video_id}
    config_data = read_json(data_path / "config.json")
    if config_data:
        config = AppConfig(**config_data)
        for channel_config in config.channels:
            videos_path = (
                data_path
                / "raw"
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos = read_json(videos_path)
            if videos:
                vlist = (
                    videos
                    if isinstance(videos, list)
                    else videos.get("videos", [])
                )
                for v in vlist:
                    if v.get("video_id") == video_id:
                        video_meta = v
                        break

    generator = CommentReportGenerator()
    path = generator.generate(
        video_id=video_id,
        video_meta=video_meta,
        topics=topics_list,
        questions_data=questions_data,
        output_dir=out_dir,
    )
    console.print(f"[green]Comment insight report generated: {path}[/green]")


def report_department_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias or ID.",
    ),
    format: str = typer.Option(
        "html",
        "--format",
        help="Output format: html/xlsx/pdf.",
    ),
    year: int | None = typer.Option(
        None,
        "--year",
        help="Filter by academic year.",
    ),
    semester: int | None = typer.Option(
        None,
        "--semester",
        help="Filter by semester (1 or 2).",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        help="Output directory override.",
    ),
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
    ),
) -> None:
    """Generate a department report with overview, professor detail, and compliance.

    Args:
        channel: Channel alias or ID.
        format: Output format (html, xlsx, pdf).
        year: Optional academic year filter.
        semester: Optional semester filter.
        output_dir: Custom output directory.
        data_dir: Data storage directory.
    """
    from tube_scout.models.parsed_title import ParsedTitle
    from tube_scout.models.video import Video
    from tube_scout.output.manager import OutputManager
    from tube_scout.reporting.department_report import DepartmentReportGenerator
    from tube_scout.reporting.excel_export import ExcelExporter

    data_path = Path(data_dir)

    # Load parsed titles
    parsed_path = data_path / "parsed" / channel / "parsed_titles.json"
    parsed_data = read_json(parsed_path)
    if parsed_data is None:
        console.print(
            f"[red]No parsed titles for '{channel}'. "
            "Run title parsing first.[/red]"
        )
        raise typer.Exit(code=1)
    parsed_titles = [ParsedTitle(**p) for p in parsed_data]

    # Load videos
    videos_path = data_path / "raw" / "channels" / channel / "videos_meta.json"
    videos_data = read_json(videos_path)
    if videos_data is None:
        console.print(
            f"[red]No video data for '{channel}'. "
            "Run data collection first.[/red]"
        )
        raise typer.Exit(code=1)
    vlist = (
        videos_data
        if isinstance(videos_data, list)
        else videos_data.get("videos", [])
    )
    videos = [Video(**v) for v in vlist]

    # Set up output directory
    if output_dir:
        out_dir = Path(output_dir)
    else:
        mgr = OutputManager()
        out_dir = mgr.create_run()
        mgr.update_latest_link(out_dir)
    reports_dir = out_dir / "reports" / "department"

    generator = DepartmentReportGenerator()
    overview = generator.compute_overview(
        parsed_titles, videos, channel, year=year, semester=semester,
    )
    professor_details = generator.compute_professor_details(
        parsed_titles, videos, year=year, semester=semester,
    )
    compliance = generator.compute_compliance(
        parsed_titles, videos, year=year, semester=semester,
    )

    suffix = f"_{channel}"
    if year:
        suffix += f"_{year}"
    if semester:
        suffix += f"_s{semester}"

    if format == "html":
        report_path = reports_dir / f"department{suffix}.html"
        generator.generate_html(
            overview, professor_details, compliance, report_path,
        )
        console.print(f"[green]Department report generated: {report_path}[/green]")

    elif format == "xlsx":
        report_path = reports_dir / f"department{suffix}.xlsx"
        exporter = ExcelExporter()
        exporter.export(
            overview=overview,
            professor_details=professor_details,
            compliance_entries=compliance,
            output_path=report_path,
        )
        console.print(
            f"[green]Department Excel report: {report_path}[/green]"
        )

    elif format == "pdf":
        html_path = reports_dir / f"department{suffix}.html"
        generator.generate_html(
            overview, professor_details, compliance, html_path,
        )
        pdf_path = generator.generate_pdf(html_path)
        if pdf_path:
            console.print(f"[green]Department PDF report generated: {pdf_path}[/green]")
        else:
            console.print(
                "[yellow]PDF generation skipped (weasyprint not installed). "
                f"HTML report saved: {html_path}[/yellow]"
            )
    else:
        console.print(f"[red]Unknown format: {format}. Use html, xlsx, or pdf.[/red]")
        raise typer.Exit(code=1)


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
