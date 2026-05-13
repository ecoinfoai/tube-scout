"""Report generation CLI commands."""

import re
from datetime import UTC, date, datetime
from pathlib import Path

import typer
from rich.console import Console

from tube_scout.cli.progress import create_progress
from tube_scout.cli.project import is_producer, resolve_project
from tube_scout.models.config import AppConfig
from tube_scout.models.video_filter import VideoFilter
from tube_scout.reporting.channel_report import ChannelReportGenerator
from tube_scout.reporting.video_report import VideoReportGenerator
from tube_scout.services.video_filter_service import VideoFilterService
from tube_scout.storage.json_store import read_json

console = Console()


def _load_config(data_dir: Path) -> AppConfig:
    """Load config from data directory."""
    config_data = read_json(data_dir / "config.json")
    if config_data is None:
        console.print("[red]No configuration found. Run 'tube-scout init' first.[/red]")
        raise typer.Exit(code=1)
    return AppConfig(**config_data)


def _has_filter_options(
    keyword: str | None,
    published_after: str | None,
    published_before: str | None,
    video_ids_csv: str | None,
) -> bool:
    """Check if any filter option is specified.

    Args:
        keyword: Keyword filter value.
        published_after: Start date string.
        published_before: End date string.
        video_ids_csv: Comma-separated video IDs.

    Returns:
        True if at least one filter option is set.
    """
    return any([keyword, published_after, published_before, video_ids_csv])


def _sanitize_filename_part(value: str) -> str:
    """Sanitize a string for safe use in filenames.

    Removes path separators, parent directory references, and control characters.
    Preserves alphanumeric, Korean, and common punctuation.

    Args:
        value: Raw string to sanitize.

    Returns:
        Sanitized string safe for filename use.
    """
    # Remove path separators and parent dir references
    sanitized = value.replace("/", "_").replace("\\", "_")
    sanitized = sanitized.replace("..", "_")
    # Keep only word characters (letters, digits, underscore) and hyphens
    sanitized = re.sub(r"[^\w\-]", "_", sanitized)
    # Collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "unnamed"


def _print_dry_run_table(filtered_videos: list[dict]) -> None:
    """Print a Rich table of filtered videos for dry-run preview.

    Args:
        filtered_videos: List of video metadata dicts.
    """
    from rich.table import Table

    total_duration = sum(v.get("duration_seconds", 0) for v in filtered_videos)
    duration_h = total_duration // 3600
    duration_m = (total_duration % 3600) // 60

    table = Table(title=f"Found {len(filtered_videos)} videos matching filters")
    table.add_column("Video ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Published", style="green")
    table.add_column("Views", style="yellow", justify="right")

    for v in filtered_videos:
        view_count = v.get("view_count", 0)
        table.add_row(
            v.get("video_id", ""),
            v.get("title", ""),
            v.get("published_at", "")[:10],
            f"{view_count:,}",
        )

    if len(filtered_videos) > 200:
        console.print(
            f"[yellow]Warning: {len(filtered_videos)} videos selected "
            "(> 200). PDF generation may be slow and produce a large file.[/yellow]"
        )

    console.print(table)
    console.print(
        f"{len(filtered_videos)} videos matched. "
        f"Total duration: {duration_h}h {duration_m}m."
    )


def report_video_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
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
    keyword: str | None = typer.Option(
        None,
        "--keyword",
        help="Filter by title keyword (substring match).",
    ),
    published_after: str | None = typer.Option(
        None,
        "--published-after",
        help="Filter by publish date start (YYYY-MM-DD, inclusive).",
    ),
    published_before: str | None = typer.Option(
        None,
        "--published-before",
        help="Filter by publish date end (YYYY-MM-DD, inclusive).",
    ),
    video_ids_csv: str | None = typer.Option(
        None,
        "--video-ids",
        help="Comma-separated video IDs to filter.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview filtered video list without generating reports.",
    ),
) -> None:
    """Generate a video analysis report.

    Args:
        data_dir: Data storage directory.
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        video_id: Specific video ID, or generate for all.
        format: Output format.
        output_dir: Custom output directory.
        keyword: Title keyword filter.
        published_after: Publish date start filter (YYYY-MM-DD).
        published_before: Publish date end filter (YYYY-MM-DD).
        video_ids_csv: Comma-separated video IDs.
        dry_run: If True, show filtered list without generating reports.
    """
    # Mutual exclusion: --video-id and --video-ids
    if video_id and video_ids_csv:
        console.print("[red]Cannot use --video-id and --video-ids together.[/red]")
        raise typer.Exit(code=1)

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project, producer=is_producer("report"))
    out_dir = Path(output_dir) if output_dir else mgr.report_dir / "video"
    use_filter = _has_filter_options(
        keyword, published_after, published_before, video_ids_csv
    )

    for channel_config in config.channels:
        vid_ids = []
        if video_id:
            vid_ids = [video_id]
        else:
            videos_path = (
                mgr.collect_dir
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

            if use_filter:
                pa = date.fromisoformat(published_after) if published_after else None
                pb = date.fromisoformat(published_before) if published_before else None
                video_filter = VideoFilter(
                    keyword=keyword,
                    published_after=pa,
                    published_before=pb,
                    video_ids=video_ids_csv.split(",") if video_ids_csv else None,
                )
                filtered = VideoFilterService.filter_videos(vlist, video_filter)
                if not filtered:
                    console.print(
                        "[yellow]No videos matching the specified filters.[/yellow]"
                    )
                    raise typer.Exit(code=1)

                if dry_run:
                    _print_dry_run_table(filtered)
                    return

                vid_ids = [v["video_id"] for v in filtered]
            else:
                vid_ids = [v["video_id"] for v in vlist]

        with create_progress() as progress:
            task = progress.add_task("Generating video reports", total=len(vid_ids))
            for vid in vid_ids:
                path = _generate_video_report(
                    collect_dir=mgr.collect_dir,
                    analyze_dir=mgr.analyze_dir,
                    video_id=vid,
                    channel_id=channel_config.channel_id,
                    output_dir=out_dir,
                    fmt=format,
                )
                progress.console.print(f"[green]Report generated: {path}[/green]")
                progress.advance(task)


def _generate_video_report(
    collect_dir: Path,
    analyze_dir: Path,
    video_id: str,
    channel_id: str,
    output_dir: Path,
    fmt: str,
) -> Path:
    """Generate a single video report in the specified format.

    Args:
        collect_dir: Directory for collected data.
        analyze_dir: Directory for analysis results.
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

        gen = VideoReportGenerator(
            collect_dir=collect_dir,
            analyze_dir=analyze_dir,
        )
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

    generator = VideoReportGenerator(
        collect_dir=collect_dir,
        analyze_dir=analyze_dir,
    )
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
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        video_id: Video ID (required).
        output_dir: Custom output directory.
    """
    from tube_scout.reporting.comment_report import CommentReportGenerator

    data_path = Path(data_dir)
    mgr = resolve_project(project_dir, project, producer=is_producer("report"))
    out_dir = Path(output_dir) if output_dir else mgr.report_dir / "comment_insight"

    # Load topic clusters
    topics_path = mgr.analyze_dir / "topics" / f"{video_id}.json"
    topics = read_json(topics_path)
    if topics is None:
        console.print(
            f"[red]No topic data for {video_id}. "
            "Run 'tube-scout analyze topic' first.[/red]"
        )
        raise typer.Exit(code=1)
    topics_list = topics if isinstance(topics, list) else []

    # Load questions
    questions_path = mgr.analyze_dir / "questions" / f"{video_id}.json"
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
                mgr.collect_dir
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos = read_json(videos_path)
            if videos:
                vlist = videos if isinstance(videos, list) else videos.get("videos", [])
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
    """Generate a department report with overview, professor detail, and compliance.

    Args:
        channel: Channel alias or ID.
        format: Output format (html, xlsx, pdf).
        year: Optional academic year filter.
        semester: Optional semester filter.
        output_dir: Custom output directory.
        data_dir: Data storage directory.
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
    """
    from tube_scout.models.parsed_title import ParsedTitle
    from tube_scout.models.video import Video
    from tube_scout.reporting.department_report import DepartmentReportGenerator
    from tube_scout.reporting.excel_export import ExcelExporter

    mgr = resolve_project(project_dir, project, producer=is_producer("report"))

    # Load parsed titles
    parsed_path = mgr.analyze_dir / "parsed" / channel / "parsed_titles.json"
    parsed_data = read_json(parsed_path)
    if parsed_data is None:
        console.print(
            f"[red]No parsed titles for '{channel}'. Run title parsing first.[/red]"
        )
        raise typer.Exit(code=1)
    plist = (
        parsed_data
        if isinstance(parsed_data, list)
        else parsed_data.get("parsed_titles", [])
    )
    parsed_titles = [ParsedTitle(**p) for p in plist]

    # Load videos
    videos_path = mgr.collect_dir / "channels" / channel / "videos_meta.json"
    videos_data = read_json(videos_path)
    if videos_data is None:
        console.print(
            f"[red]No video data for '{channel}'. Run data collection first.[/red]"
        )
        raise typer.Exit(code=1)
    vlist = (
        videos_data if isinstance(videos_data, list) else videos_data.get("videos", [])
    )
    videos = [Video(**v) for v in vlist]

    # Set up output directory
    if output_dir:
        reports_dir = Path(output_dir)
    else:
        reports_dir = mgr.report_dir / "department"

    generator = DepartmentReportGenerator()
    overview = generator.compute_overview(
        parsed_titles,
        videos,
        channel,
        year=year,
        semester=semester,
    )
    professor_details = generator.compute_professor_details(
        parsed_titles,
        videos,
        year=year,
        semester=semester,
    )
    compliance = generator.compute_compliance(
        parsed_titles,
        videos,
        year=year,
        semester=semester,
    )

    suffix = f"_{channel}"
    if year:
        suffix += f"_{year}"
    if semester:
        suffix += f"_s{semester}"

    if format == "html":
        report_path = reports_dir / f"department{suffix}.html"
        generator.generate_html(
            overview,
            professor_details,
            compliance,
            report_path,
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
        console.print(f"[green]Department Excel report: {report_path}[/green]")

    elif format == "pdf":
        html_path = reports_dir / f"department{suffix}.html"
        generator.generate_html(
            overview,
            professor_details,
            compliance,
            html_path,
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


def report_bundle_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
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
    keyword: str | None = typer.Option(
        None,
        "--keyword",
        help="Filter by title keyword (substring match).",
    ),
    published_after: str | None = typer.Option(
        None,
        "--published-after",
        help="Filter by publish date start (YYYY-MM-DD, inclusive).",
    ),
    published_before: str | None = typer.Option(
        None,
        "--published-before",
        help="Filter by publish date end (YYYY-MM-DD, inclusive).",
    ),
    video_ids_csv: str | None = typer.Option(
        None,
        "--video-ids",
        help="Comma-separated video IDs to filter.",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="PDF output file path.",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Report cover title.",
    ),
    format: str = typer.Option(
        "pdf",
        "--format",
        help="Output format: pdf/html.",
    ),
    sort: str = typer.Option(
        "date_asc",
        "--sort",
        help="Sort order: date/date_asc/course/views.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview filtered video list without generating bundle.",
    ),
    no_confirm: bool = typer.Option(
        False,
        "--no-confirm",
        help="Skip interactive confirmation before generating.",
    ),
    from_html: str | None = typer.Option(
        None,
        "--from-html",
        help="Existing HTML report directory (harvest mode).",
    ),
) -> None:
    """Generate a combined PDF bundle report from filtered videos.

    Args:
        data_dir: Data storage directory.
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        keyword: Title keyword filter.
        published_after: Publish date start filter (YYYY-MM-DD).
        published_before: Publish date end filter (YYYY-MM-DD).
        video_ids_csv: Comma-separated video IDs.
        output: PDF output file path.
        title: Custom report cover title.
        format: Output format ('pdf' or 'html').
        sort: Sort order for videos.
        dry_run: If True, show filtered list without generating bundle.
        no_confirm: If True, skip interactive confirmation.
        from_html: Path to existing HTML reports directory.
    """
    from tube_scout.reporting.bundle_report import BundleReportGenerator

    if not _has_filter_options(
        keyword, published_after, published_before, video_ids_csv
    ):
        console.print(
            "[red]At least one filter option is required "
            "(--keyword, --published-after, --published-before, or --video-ids).[/red]"
        )
        raise typer.Exit(code=1)

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project, producer=is_producer("report"))

    video_filter = VideoFilter(
        keyword=keyword,
        published_after=(
            date.fromisoformat(published_after) if published_after else None
        ),
        published_before=(
            date.fromisoformat(published_before) if published_before else None
        ),
        video_ids=video_ids_csv.split(",") if video_ids_csv else None,
    )

    for channel_config in config.channels:
        channel_id = channel_config.channel_id

        gen = BundleReportGenerator(
            collect_dir=mgr.collect_dir,
            analyze_dir=mgr.analyze_dir,
        )

        # Pre-filter for preview and 0-result check
        videos_meta = gen._load_videos_meta(channel_id)
        filtered = VideoFilterService.filter_videos(videos_meta, video_filter)
        filtered = VideoFilterService.sort_videos(filtered, sort)

        if not filtered:
            console.print("[yellow]No videos matching the specified filters.[/yellow]")
            raise typer.Exit(code=0)

        if dry_run:
            _print_dry_run_table(filtered)
            return

        # Show preview and ask for confirmation
        _print_dry_run_table(filtered)
        if not no_confirm:
            if not typer.confirm("Generate report?"):
                console.print("[yellow]Cancelled.[/yellow]")
                raise typer.Exit(code=0)

        if output:
            output_path = Path(output)
        else:
            suffix = _sanitize_filename_part(keyword) if keyword else "all"
            date_str = datetime.now(UTC).strftime("%Y%m%d")
            output_path = mgr.report_dir / "bundle" / f"bundle_{suffix}_{date_str}.html"

        try:
            if from_html:
                html_path = gen.generate_from_html(
                    html_dir=Path(from_html),
                    video_filter=video_filter,
                    channel_id=channel_id,
                    output_path=output_path,
                    sort_by=sort,
                    title=title,
                )
            else:
                html_path = gen.generate(
                    video_filter=video_filter,
                    channel_id=channel_id,
                    output_path=output_path,
                    sort_by=sort,
                    title=title,
                )
        except ValueError:
            console.print("[yellow]No videos matching the specified filters.[/yellow]")
            raise typer.Exit(code=0)

        console.print(f"[green]Bundle HTML report generated: {html_path}[/green]")

        if format == "html":
            return

        pdf_path = gen.render_pdf(html_path)
        if pdf_path:
            console.print(f"[green]Bundle PDF report generated: {pdf_path}[/green]")
        else:
            console.print(
                "[yellow]PDF generation skipped (weasyprint not available). "
                "Install weasyprint for PDF output. "
                f"HTML report saved: {html_path}[/yellow]"
            )


def report_channel_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Data storage directory.",
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
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        format: Output format.
        output_dir: Custom output directory.
    """
    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project, producer=is_producer("report"))
    out_dir = Path(output_dir) if output_dir else mgr.report_dir / "channel"

    generator = ChannelReportGenerator(
        collect_dir=mgr.collect_dir,
        analyze_dir=mgr.analyze_dir,
    )

    with create_progress() as progress:
        task = progress.add_task(
            "Generating channel reports", total=len(config.channels)
        )
        for channel_config in config.channels:
            path = generator.generate(
                channel_id=channel_config.channel_id,
                output_dir=out_dir,
            )
            progress.console.print(f"[green]Channel report generated: {path}[/green]")
            progress.advance(task)


def report_content_command(
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (required for spec 007 legacy report; omit for spec 011 v2).",
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
    format: str = typer.Option(
        "html",
        "--format",
        help="Output format: html, xlsx, json, or all.",
    ),
    professor: str | None = typer.Option(
        None,
        "--professor",
        help="Professor ID for spec 011 nC2 v2 report (omit for legacy report).",
    ),
    year: int | None = typer.Option(
        None,
        "--year",
        help="Filter by academic year (legacy report only).",
    ),
    semester: int | None = typer.Option(
        None,
        "--semester",
        help="Filter by semester 1 or 2 (legacy report only).",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        help="Output directory (legacy report only).",
    ),
) -> None:
    """Generate content quality report.

    With --professor: generates spec 011 nC2 v2 report (4-pattern HTML/Excel/JSON).
    Without --professor: generates spec 007 legacy report (requires --channel).

    Args:
        channel: Channel alias for legacy report.
        project_dir: Projects root directory.
        project: Existing project path or 'latest'.
        format: Output format.
        professor: Professor ID for v2 nC2 report.
        year: Academic year filter (legacy).
        semester: Semester filter (legacy).
        output_dir: Custom output directory (legacy).
    """
    # spec 011 v2 report path: --professor provided
    if professor is not None:
        from tube_scout.reporting.content_report import generate_v2_report

        if project is None:
            console.print("[red]--project is required for spec 011 v2 report.[/red]")
            raise typer.Exit(code=2)

        project_path = Path(project)
        if not project_path.exists():
            console.print(f"[red]Project directory not found: {project_path}[/red]")
            raise typer.Exit(code=2)

        try:
            paths = generate_v2_report(project_path, professor_id=professor, fmt=format)
            for ext, path in paths.items():
                console.print(f"[green]v2 report ({ext}): {path}[/green]")
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2)
        return

    # Legacy spec 007 report path: --channel required
    if channel is None:
        console.print(
            "[red]--professor (spec 011 v2) or --channel (spec 007 legacy) is required.[/red]"
        )
        raise typer.Exit(code=2)

    from tube_scout.reporting.content_report import ContentReportGenerator
    from tube_scout.services.auth import load_registry
    from tube_scout.storage.content_db import ContentDB

    registry = load_registry()
    if channel not in registry:
        console.print(f"[red]Channel '{channel}' not registered.[/red]")
        raise typer.Exit(code=1)

    channel_id = registry[channel].channel_id
    mgr = resolve_project(project_dir, project, producer=is_producer("report"))
    db_path = mgr.project_dir / "tube_scout.db"

    if not db_path.exists():
        console.print(
            "[yellow]No analysis data found. "
            "Run 'tube-scout content scan' first.[/yellow]"
        )
        raise typer.Exit(code=2)

    db = ContentDB(db_path)
    comparisons = db.list_comparisons(order_by_suspicion=True)
    quality_results = []
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM quality_results")
    quality_results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if not comparisons and not quality_results:
        console.print("[yellow]No data to report.[/yellow]")
        raise typer.Exit(code=2)

    if output_dir:
        reports_dir = Path(output_dir)
    else:
        reports_dir = mgr.report_dir / "content_quality"

    suffix = f"_{channel_id}"
    if year:
        suffix += f"_{year}"
    if semester:
        suffix += f"_s{semester}"

    generator = ContentReportGenerator()

    if format == "html":
        report_path = reports_dir / f"content{suffix}.html"
        generator.generate_html(comparisons, quality_results, report_path)
        console.print(f"[green]Content HTML report generated: {report_path}[/green]")
    elif format == "xlsx":
        report_path = reports_dir / f"content{suffix}.xlsx"
        generator.generate_xlsx(comparisons, quality_results, report_path)
        console.print(f"[green]Content Excel report generated: {report_path}[/green]")
    elif format == "json":
        report_path = reports_dir / f"content{suffix}.json"
        generator.generate_json(comparisons, quality_results, report_path)
        console.print(f"[green]Content JSON report generated: {report_path}[/green]")
    else:
        console.print(f"[red]Unknown format: {format}. Use html, xlsx, or json.[/red]")
        raise typer.Exit(code=1)


def report_content_reuse_command(
    channel: str = typer.Option(..., "--channel", help="Channel alias"),
    professor: str = typer.Option(..., "--professor", help="Professor identifier"),
    mode: str = typer.Option("M-nC2", "--mode", help="Matching mode: M-nC2 or M-default"),
    top_k: int = typer.Option(50, "--top-k", help="Top-K suspect pairs in report"),
    sort_by: str = typer.Option(
        "i2-cosine",
        "--sort-by",
        help="Sort metric: i2-cosine, i6-longest-contiguous, i7-distribution-dispersion, i8-position-diversity, audio-fp-hamming",
    ),
    appendix_threshold_i2_cosine: float | None = typer.Option(
        None, "--appendix-threshold-i2-cosine", help="Appendix threshold for I-2 cosine similarity"
    ),
    appendix_threshold_i6_longest_contiguous: float | None = typer.Option(
        None, "--appendix-threshold-i6-longest-contiguous", help="Appendix threshold for I-6 longest contiguous (seconds)"
    ),
    appendix_threshold_i7_distribution_dispersion: float | None = typer.Option(
        None, "--appendix-threshold-i7-distribution-dispersion", help="Appendix threshold for I-7 distribution dispersion"
    ),
    appendix_threshold_i8_position_diversity: float | None = typer.Option(
        None, "--appendix-threshold-i8-position-diversity", help="Appendix threshold for I-8 position diversity"
    ),
    appendix_threshold_audio_fp_hamming: int | None = typer.Option(
        None, "--appendix-threshold-audio-fp-hamming", help="Appendix threshold for audio fingerprint Hamming distance"
    ),
    format: str = typer.Option("both", "--format", help="Output format: pdf, html, or both"),
    output: str | None = typer.Option(None, "--output", help="Output directory (default: current directory)"),
    db_path: str | None = typer.Option(None, "--db-path", help="Path to content_reuse.db"),
) -> None:
    """Render per-professor nC2 content reuse report (HTML + PDF)."""
    from tube_scout.reporting.professor_nc2 import (
        AppendixThresholds,
        render_professor_nc2_report,
    )
    from tube_scout.storage.content_db import ContentDB

    valid_formats = {"pdf", "html", "both"}
    if format not in valid_formats:
        console.print(f"[red]Invalid format: {format!r}. Use one of: {sorted(valid_formats)}[/red]")
        raise typer.Exit(code=1)

    valid_sort = {
        "i2-cosine", "i6-longest-contiguous", "i7-distribution-dispersion",
        "i8-position-diversity", "audio-fp-hamming",
    }
    if sort_by not in valid_sort:
        console.print(f"[red]Invalid --sort-by: {sort_by!r}. Valid: {sorted(valid_sort)}[/red]")
        raise typer.Exit(code=1)

    resolved_db = Path(db_path) if db_path else Path.cwd() / "content_reuse.db"
    if not resolved_db.exists():
        console.print(f"[red]Database not found: {resolved_db}[/red]")
        raise typer.Exit(code=1)

    output_dir = Path(output) if output else Path.cwd() / "reports" / "content_reuse"

    thresholds = AppendixThresholds(
        i2_cosine=appendix_threshold_i2_cosine,
        i6_longest_contiguous=appendix_threshold_i6_longest_contiguous,
        i7_distribution_dispersion=appendix_threshold_i7_distribution_dispersion,
        i8_position_diversity=appendix_threshold_i8_position_diversity,
        audio_fp_hamming=appendix_threshold_audio_fp_hamming,
    )

    db = ContentDB(resolved_db)
    try:
        result = render_professor_nc2_report(
            professor=professor,
            channel_alias=channel,
            db=db,
            output_dir=output_dir,
            matching_mode=mode,  # type: ignore[arg-type]
            top_k=top_k,
            sort_by=sort_by,  # type: ignore[arg-type]
            appendix_thresholds=thresholds,
            output_format=format,  # type: ignore[arg-type]
        )
    finally:
        db.close()

    if result.html_path:
        console.print(f"[green]HTML report: {result.html_path}[/green]")
    if result.pdf_path:
        console.print(f"[green]PDF report: {result.pdf_path}[/green]")
    console.print(
        f"[blue]Professor: {result.professor} | Pairs: {result.pair_count} | "
        f"Appendix: {result.appendix_count}[/blue]"
    )
