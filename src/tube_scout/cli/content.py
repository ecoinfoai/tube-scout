"""Content reuse detection CLI commands.

Provides fingerprint, compare, quality, review, and scan subcommands
under the 'tube-scout content' command group.
"""

import logging
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from tube_scout.cli.project import resolve_project
from tube_scout.services.auth import load_registry
from tube_scout.storage.content_db import ContentDB
from tube_scout.storage.json_store import read_json

logger = logging.getLogger(__name__)

content_app = typer.Typer(
    help="Content reuse detection and quality analysis.",
    no_args_is_help=True,
)
console = Console()


def _resolve_channel_id(channel: str) -> str:
    """Resolve channel alias to channel ID.

    Args:
        channel: Channel alias.

    Returns:
        YouTube channel ID.

    Raises:
        typer.Exit: If channel is not registered.
    """
    registry = load_registry()
    if channel not in registry:
        console.print(
            f"[red]Channel '{channel}' not registered. "
            f"Run 'tube-scout auth --channel {channel}' first.[/red]"
        )
        raise typer.Exit(code=1)
    return registry[channel].channel_id


def _get_db(project_dir: Path) -> ContentDB:
    """Get or create ContentDB for a project.

    Args:
        project_dir: Project directory path.

    Returns:
        ContentDB instance.
    """
    return ContentDB(project_dir / "tube_scout.db")


def _load_transcripts(
    collect_dir: Path, channel_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Load transcript segments keyed by video_id.

    Args:
        collect_dir: 01_collect directory path.
        channel_id: YouTube channel ID.

    Returns:
        Dict mapping video_id to list of segment dicts.
    """
    transcripts_dir = collect_dir / "channels" / channel_id / "transcripts"
    if not transcripts_dir.exists():
        # Try flat transcripts dir
        transcripts_dir = collect_dir / "transcripts"

    result: dict[str, list[dict[str, Any]]] = {}
    if not transcripts_dir.exists():
        return result

    for path in transcripts_dir.glob("*.json"):
        data = read_json(path)
        if data and "segments" in data:
            vid = data.get("video_id", path.stem)
            result[vid] = data["segments"]

    return result


def _load_parsed_titles(
    analyze_dir: Path, channel_id: str
) -> list[dict[str, Any]]:
    """Load parsed title data.

    Args:
        analyze_dir: 02_analyze directory path.
        channel_id: YouTube channel ID.

    Returns:
        List of parsed title dicts.
    """
    # Try multiple possible locations
    candidates = [
        analyze_dir / "channels" / channel_id / "parsed_titles.json",
        analyze_dir / "parsed_titles.json",
    ]
    for path in candidates:
        data = read_json(path)
        if data:
            return data if isinstance(data, list) else data.get("titles", [])
    return []


def _load_videos_meta(
    collect_dir: Path, channel_id: str
) -> list[dict[str, Any]]:
    """Load video metadata.

    Args:
        collect_dir: 01_collect directory path.
        channel_id: YouTube channel ID.

    Returns:
        List of video metadata dicts.
    """
    videos_path = collect_dir / "channels" / channel_id / "videos_meta.json"
    data = read_json(videos_path)
    if data:
        return data if isinstance(data, list) else data.get("videos", [])
    return []


@content_app.command(name="fingerprint")
def content_fingerprint_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias for caption lookup.",
    ),
    project: str = typer.Option(
        "latest",
        "--project",
        help="Project path or 'latest'.",
    ),
    project_dir: str = typer.Option(
        "./projects",
        "--project-dir",
        help="Projects root directory.",
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
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Re-generate fingerprints even if already done.",
    ),
) -> None:
    """Generate SHA-256 hash and semantic embedding for each video's caption text.

    Args:
        channel: Channel alias.
        project: Project path or 'latest'.
        project_dir: Projects root directory.
        year: Academic year filter.
        semester: Semester filter.
        force_refresh: Re-generate fingerprints.
    """
    from tube_scout.services.fingerprint import FingerprintService

    channel_id = _resolve_channel_id(channel)
    mgr = resolve_project(project_dir, project)
    db = _get_db(mgr.project_dir)
    fp_service = FingerprintService()

    transcripts = _load_transcripts(mgr.collect_dir, channel_id)
    if not transcripts:
        console.print(
            "[yellow]No transcripts found. "
            "Run 'tube-scout collect transcripts' first.[/yellow]"
        )
        raise typer.Exit(code=2)

    count = len(transcripts)
    console.print(
        f"[bold]Generating fingerprints for {count} videos...[/bold]"
    )

    processed = 0
    skipped = 0
    for video_id, segments in transcripts.items():
        if not force_refresh:
            existing = db.get_fingerprint(video_id)
            if existing:
                skipped += 1
                continue

        try:
            fp = fp_service.generate_hash(segments)
            db.upsert_fingerprint(video_id, fp.sha256_hash, fp.full_text_length)
            db.upsert_processing_status(video_id, channel_id, "fingerprinted")
            processed += 1
        except ValueError as e:
            logger.warning("Skipping %s: %s", video_id, e)
            db.upsert_processing_status(
                video_id, channel_id, "failed", error_message=str(e)
            )

    console.print(
        f"[green]Fingerprints generated: {processed} new, {skipped} skipped.[/green]"
    )


@content_app.command(name="compare")
def content_compare_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias.",
    ),
    year_from: int = typer.Option(
        ...,
        "--year-from",
        help="Source year for comparison.",
    ),
    year_to: int = typer.Option(
        ...,
        "--year-to",
        help="Target year for comparison.",
    ),
    project: str = typer.Option(
        "latest",
        "--project",
        help="Project path or 'latest'.",
    ),
    project_dir: str = typer.Option(
        "./projects",
        "--project-dir",
        help="Projects root directory.",
    ),
    course: str | None = typer.Option(
        None,
        "--course",
        help="Filter by course name.",
    ),
    professor: str | None = typer.Option(
        None,
        "--professor",
        help="Filter by professor name.",
    ),
) -> None:
    """Compare matched video pairs across years using 5 indicators.

    Args:
        channel: Channel alias.
        year_from: Source year.
        year_to: Target year.
        project: Project path or 'latest'.
        project_dir: Projects root directory.
        course: Course name filter.
        professor: Professor name filter.
    """
    from tube_scout.services.content_comparator import (
        ContentComparator,
        match_comparison_pairs,
    )
    from tube_scout.services.fingerprint import FingerprintService

    channel_id = _resolve_channel_id(channel)
    mgr = resolve_project(project_dir, project)
    db = _get_db(mgr.project_dir)

    # Load parsed titles for pair matching
    parsed_titles = _load_parsed_titles(mgr.analyze_dir, channel_id)
    if not parsed_titles:
        console.print(
            "[yellow]No parsed titles found. "
            "Run title parsing first.[/yellow]"
        )
        raise typer.Exit(code=2)

    # Optional filters
    if course:
        parsed_titles = [t for t in parsed_titles if t.get("course") == course]
    if professor:
        parsed_titles = [
            t for t in parsed_titles
            if professor in t.get("professor", [])
        ]

    pairs = match_comparison_pairs(parsed_titles, year_from=year_from, year_to=year_to)
    if not pairs:
        console.print(
            "[yellow]No comparison pairs found "
            "for the specified years.[/yellow]"
        )
        raise typer.Exit(code=2)

    console.print(
        f"[bold]Comparing {len(pairs)} pairs "
        f"({year_from} vs {year_to})...[/bold]"
    )

    # Load transcripts for text comparison
    transcripts = _load_transcripts(mgr.collect_dir, channel_id)
    fp_service = FingerprintService()

    # Build text map
    text_map: dict[str, str] = {}
    for vid, segs in transcripts.items():
        text_map[vid] = fp_service.extract_full_text(segs)

    # Build duration map from video metadata
    videos = _load_videos_meta(mgr.collect_dir, channel_id)
    dur_map = {v["video_id"]: v.get("duration_seconds", 0) for v in videos}

    comparator = ContentComparator(
        fingerprint_lookup=lambda vid: db.get_fingerprint(vid),
        text_lookup=lambda vid: text_map.get(vid),
        duration_lookup=lambda vid: dur_map.get(vid),
    )

    results_count = 0
    for pair in pairs:
        result = comparator.compare_pair(pair)
        try:
            db.insert_comparison(**{
                k: result[k] for k in [
                    "source_video_id", "target_video_id", "professor", "course",
                    "week", "session", "year_from", "year_to",
                    "i1_hash_match", "i2_cosine_similarity", "i3_change_rate",
                    "i4_new_term_count", "i5_duration_diff_seconds",
                    "suspicion_score", "grade",
                ]
            })
            results_count += 1
        except Exception as e:
            logger.warning("Failed to store comparison %s<>%s: %s",
                           pair["source_video_id"], pair["target_video_id"], e)

    # Show summary
    table = Table(title="Comparison Summary")
    table.add_column("Grade", style="bold")
    table.add_column("Count", justify="right")

    all_results = db.list_comparisons()
    grade_counts: dict[str, int] = {}
    for r in all_results:
        g = r.get("grade", "unknown")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    grade_styles = {
        "critical": "red",
        "high": "yellow",
        "moderate": "cyan",
        "normal": "green",
    }
    for grade_name in ("critical", "high", "moderate", "normal"):
        count = grade_counts.get(grade_name, 0)
        table.add_row(grade_name, str(count), style=grade_styles.get(grade_name))

    console.print(table)
    console.print(f"[green]Compared {results_count} pairs successfully.[/green]")


@content_app.command(name="quality")
def content_quality_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias.",
    ),
    project: str = typer.Option(
        "latest",
        "--project",
        help="Project path or 'latest'.",
    ),
    project_dir: str = typer.Option(
        "./projects",
        "--project-dir",
        help="Projects root directory.",
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
) -> None:
    """Run quality checklist (Q-001~Q-005) on all videos with captions.

    Args:
        channel: Channel alias.
        project: Project path or 'latest'.
        project_dir: Projects root directory.
        year: Academic year filter.
        semester: Semester filter.
    """
    from tube_scout.services.quality_checker import QualityChecker

    channel_id = _resolve_channel_id(channel)
    mgr = resolve_project(project_dir, project)
    db = _get_db(mgr.project_dir)

    transcripts = _load_transcripts(mgr.collect_dir, channel_id)
    videos = _load_videos_meta(mgr.collect_dir, channel_id)
    dur_map = {v["video_id"]: v.get("duration_seconds", 0) for v in videos}

    # Load parsed titles for course relevance
    parsed_titles = _load_parsed_titles(mgr.analyze_dir, channel_id)
    course_map = {t["video_id"]: t.get("course") for t in parsed_titles}

    if not transcripts and not videos:
        console.print("[yellow]No data found. Run collection first.[/yellow]")
        raise typer.Exit(code=1)

    checker = QualityChecker()
    processed = 0

    all_video_ids = set(list(transcripts.keys()) + [v["video_id"] for v in videos])
    count = len(all_video_ids)
    console.print(
        f"[bold]Running quality checks on {count} videos...[/bold]"
    )

    for video_id in all_video_ids:
        segments = transcripts.get(video_id)
        duration = dur_map.get(video_id, 0)
        course_name = course_map.get(video_id)

        result = checker.run_all_checks(
            segments=segments,
            duration_seconds=duration,
            course_name=course_name,
        )

        db.upsert_quality_result(
            video_id=video_id,
            q001_voice_present=result.q001_voice_present,
            q002_min_duration=result.q002_min_duration,
            q003_course_relevance=result.q003_course_relevance,
            q004_silence_ratio=result.q004_silence_ratio,
            q005_speech_density=result.q005_speech_density,
            pass_count=result.pass_count,
        )
        processed += 1

    console.print(f"[green]Quality checks completed for {processed} videos.[/green]")


@content_app.command(name="review")
def content_review_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias.",
    ),
    project: str = typer.Option(
        "latest",
        "--project",
        help="Project path or 'latest'.",
    ),
    project_dir: str = typer.Option(
        "./projects",
        "--project-dir",
        help="Projects root directory.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help=(
            "Filter by review status "
            "(UNREVIEWED, CONFIRMED_DUPLICATE, FALSE_POSITIVE)."
        ),
    ),
    grade: str | None = typer.Option(
        None,
        "--grade",
        help="Filter by grade (critical, high, moderate, normal).",
    ),
    mark: str | None = typer.Option(
        None,
        "--mark",
        help="Mark comparison: '<id> <CONFIRMED_DUPLICATE|FALSE_POSITIVE>'.",
    ),
) -> None:
    """View and update review status for comparison results.

    Args:
        channel: Channel alias.
        project: Project path or 'latest'.
        project_dir: Projects root directory.
        status: Review status filter.
        grade: Grade filter.
        mark: Mark comparison with new status.
    """
    mgr = resolve_project(project_dir, project)
    db = _get_db(mgr.project_dir)

    # Mark mode
    if mark:
        parts = mark.split(maxsplit=1)
        if len(parts) != 2:
            console.print(
                "[red]--mark format: '<comparison_id> "
                "<CONFIRMED_DUPLICATE|FALSE_POSITIVE>'[/red]"
            )
            raise typer.Exit(code=1)

        try:
            comp_id = int(parts[0])
        except ValueError:
            console.print(f"[red]Invalid comparison ID: {parts[0]}[/red]")
            raise typer.Exit(code=1)

        new_status = parts[1].upper()
        if new_status not in ("CONFIRMED_DUPLICATE", "FALSE_POSITIVE"):
            console.print(
                f"[red]Invalid status: {new_status}. "
                "Use CONFIRMED_DUPLICATE or FALSE_POSITIVE.[/red]"
            )
            raise typer.Exit(code=1)

        try:
            db.update_review_status(comp_id, new_status, reviewed_by="cli")
            console.print(
                f"[green]Comparison {comp_id} "
                f"marked as {new_status}.[/green]"
            )
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)
        return

    # List mode
    results = db.list_comparisons(
        review_status=status,
        grade=grade,
        order_by_suspicion=True,
    )

    if not results:
        console.print("[yellow]No comparison results found.[/yellow]")
        raise typer.Exit(code=2)

    table = Table(title="Content Review")
    table.add_column("ID", justify="right")
    table.add_column("Professor")
    table.add_column("Course")
    table.add_column("W/S")
    table.add_column("Years")
    table.add_column("Score", justify="right")
    table.add_column("Grade")
    table.add_column("Status")

    grade_styles = {
        "critical": "red",
        "high": "yellow",
        "moderate": "cyan",
        "normal": "green",
    }

    for r in results:
        g = r.get("grade", "")
        table.add_row(
            str(r["id"]),
            r.get("professor", ""),
            r.get("course", ""),
            f"W{r.get('week', '?')}/S{r.get('session', '?')}",
            f"{r.get('year_from', '?')}->{r.get('year_to', '?')}",
            f"{r.get('suspicion_score', 0):.1f}",
            g,
            r.get("review_status", ""),
            style=grade_styles.get(g, ""),
        )

    console.print(table)
    console.print(
        f"[dim]Total: {len(results)} results. "
        "Use --mark '<id> <status>' to update.[/dim]"
    )


@content_app.command(name="scan")
def content_scan_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias.",
    ),
    year_from: int = typer.Option(
        ...,
        "--year-from",
        help="Source year.",
    ),
    year_to: int = typer.Option(
        ...,
        "--year-to",
        help="Target year.",
    ),
    project: str = typer.Option(
        "latest",
        "--project",
        help="Project path or 'latest'.",
    ),
    project_dir: str = typer.Option(
        "./projects",
        "--project-dir",
        help="Projects root directory.",
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Force re-processing of all stages.",
    ),
) -> None:
    """Run full pipeline: fingerprint -> compare -> quality.

    Args:
        channel: Channel alias.
        year_from: Source year.
        year_to: Target year.
        project: Project path or 'latest'.
        project_dir: Projects root directory.
        force_refresh: Force re-processing.
    """
    console.print("[bold]Running content scan pipeline...[/bold]\n")

    # Stage 1: Fingerprint
    console.print("[bold cyan]Stage 1/3: Fingerprint[/bold cyan]")
    try:
        content_fingerprint_command(
            channel=channel,
            project=project,
            project_dir=project_dir,
            year=None,
            semester=None,
            force_refresh=force_refresh,
        )
    except SystemExit:
        pass  # Non-fatal: may exit with code 2 (no captions)

    # Stage 2: Compare
    console.print("\n[bold cyan]Stage 2/3: Compare[/bold cyan]")
    try:
        content_compare_command(
            channel=channel,
            year_from=year_from,
            year_to=year_to,
            project=project,
            project_dir=project_dir,
            course=None,
            professor=None,
        )
    except SystemExit:
        pass

    # Stage 3: Quality
    console.print("\n[bold cyan]Stage 3/3: Quality[/bold cyan]")
    try:
        content_quality_command(
            channel=channel,
            project=project,
            project_dir=project_dir,
            year=None,
            semester=None,
        )
    except SystemExit:
        pass

    console.print("\n[bold green]Content scan pipeline complete.[/bold green]")
