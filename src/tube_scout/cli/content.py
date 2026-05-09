"""Content reuse detection CLI commands.

Provides fingerprint, compare, quality, review, and scan subcommands
under the 'tube-scout content' command group (spec 007), plus professor,
baseline, whitelist, and policy subcommand groups (spec 011 placeholders).
"""

import logging
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from tube_scout.cli.project import is_producer, resolve_project
from tube_scout.services.auth import load_registry
from tube_scout.storage.content_db import ContentDB
from tube_scout.storage.json_store import read_json

logger = logging.getLogger(__name__)

content_app = typer.Typer(
    help="Content reuse detection and quality analysis.",
    no_args_is_help=True,
)
console = Console()

# --- spec 011 subcommand groups ---

professor_app = typer.Typer(
    name="professor",
    help="Manage professor mappings (spec 011).",
    no_args_is_help=True,
)
baseline_app = typer.Typer(
    name="baseline",
    help="Manage per-professor baseline corpus (spec 011).",
    no_args_is_help=True,
)
whitelist_app = typer.Typer(
    name="whitelist",
    help="Manage Layer D pair/phrase whitelist (spec 011).",
    no_args_is_help=True,
)
policy_app = typer.Typer(
    name="policy",
    help="Inspect policy.yaml (spec 011, read-only).",
    no_args_is_help=True,
)

content_app.add_typer(professor_app, name="professor")
content_app.add_typer(baseline_app, name="baseline")
content_app.add_typer(whitelist_app, name="whitelist")
content_app.add_typer(policy_app, name="policy")

# Module-level flag: lazy migration runs at most once per process invocation.
_SPEC011_MIGRATED: bool = False


def _ensure_v2_schema(project: Path) -> Path:
    """Lazy migration hook: run migrate_to_v2 once per process invocation.

    Args:
        project: Project root directory.

    Returns:
        Absolute path to the content_reuse.db file.
    """
    global _SPEC011_MIGRATED
    db_path = project / "02_analyze" / "content" / "content_reuse.db"
    if not _SPEC011_MIGRATED:
        from tube_scout.storage.content_db import migrate_to_v2
        migrate_to_v2(db_path)
        _SPEC011_MIGRATED = True
    return db_path


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


def _load_parsed_titles(analyze_dir: Path, channel_id: str) -> list[dict[str, Any]]:
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


def _load_videos_meta(collect_dir: Path, channel_id: str) -> list[dict[str, Any]]:
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
    mgr = resolve_project(project_dir, project, producer=is_producer("content"))
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
    console.print(f"[bold]Generating fingerprints for {count} videos...[/bold]")

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
    mode: str = typer.Option(
        "legacy",
        "--mode",
        help="Compare mode: 'legacy' (year-pair) or 'nc2' (delegates to scan --mode nc2).",
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
        mode: Compare mode ('legacy' or 'nc2').
    """
    if mode == "nc2":
        if not professor:
            console.print(
                "[red]Missing --professor for nC2 mode. "
                "Provide a professor ID registered with 'tube-scout content professor map'.[/red]"
            )
            raise typer.Exit(code=1)
        _run_nc2_scan(project=project, project_dir=project_dir, professor_id=professor, resume=False)
        return
    from tube_scout.services.content_comparator import (
        ContentComparator,
        match_comparison_pairs,
    )
    from tube_scout.services.fingerprint import FingerprintService

    channel_id = _resolve_channel_id(channel)
    mgr = resolve_project(project_dir, project, producer=is_producer("content"))
    db = _get_db(mgr.project_dir)

    # Load parsed titles for pair matching
    parsed_titles = _load_parsed_titles(mgr.analyze_dir, channel_id)
    if not parsed_titles:
        console.print(
            "[yellow]No parsed titles found. Run title parsing first.[/yellow]"
        )
        raise typer.Exit(code=2)

    # Optional filters
    if course:
        parsed_titles = [t for t in parsed_titles if t.get("course") == course]
    if professor:
        parsed_titles = [
            t for t in parsed_titles if professor in t.get("professor", [])
        ]

    pairs = match_comparison_pairs(parsed_titles, year_from=year_from, year_to=year_to)
    if not pairs:
        console.print(
            "[yellow]No comparison pairs found for the specified years.[/yellow]"
        )
        raise typer.Exit(code=2)

    console.print(
        f"[bold]Comparing {len(pairs)} pairs ({year_from} vs {year_to})...[/bold]"
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
            db.insert_comparison(
                **{
                    k: result[k]
                    for k in [
                        "source_video_id",
                        "target_video_id",
                        "professor",
                        "course",
                        "week",
                        "session",
                        "year_from",
                        "year_to",
                        "i1_hash_match",
                        "i2_cosine_similarity",
                        "i3_change_rate",
                        "i4_new_term_count",
                        "i5_duration_diff_seconds",
                        "suspicion_score",
                        "grade",
                    ]
                }
            )
            results_count += 1
        except Exception as e:
            logger.warning(
                "Failed to store comparison %s<>%s: %s",
                pair["source_video_id"],
                pair["target_video_id"],
                e,
            )

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
    mgr = resolve_project(project_dir, project, producer=is_producer("content"))
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
    console.print(f"[bold]Running quality checks on {count} videos...[/bold]")

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
            "Filter by review status (UNREVIEWED, CONFIRMED_DUPLICATE, FALSE_POSITIVE)."
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
    mgr = resolve_project(project_dir, project, producer=is_producer("content"))
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
                f"[green]Comparison {comp_id} marked as {new_status}.[/green]"
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
    mode: str = typer.Option(
        "legacy",
        "--mode",
        help="Scan mode: 'legacy' (spec 007 year-pair) or 'nc2' (spec 011 nC2 professor pool).",
    ),
    professor: str | None = typer.Option(
        None,
        "--professor",
        help="Professor ID (required for --mode nc2).",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Resume an interrupted nC2 run from the last checkpoint.",
    ),
) -> None:
    """Run full pipeline: fingerprint -> compare -> quality.

    In 'nc2' mode, runs the nC2 professor-pool matching pipeline instead
    of the legacy year-pair compare stage.

    Args:
        channel: Channel alias.
        year_from: Source year.
        year_to: Target year.
        project: Project path or 'latest'.
        project_dir: Projects root directory.
        force_refresh: Force re-processing.
        mode: Scan mode ('legacy' or 'nc2').
        professor: Professor ID (required for nc2 mode).
        resume: Resume from last checkpoint (nc2 mode only).
    """
    if mode == "nc2":
        if not professor:
            console.print(
                "[red]Missing --professor for nC2 mode. "
                "Provide a professor ID registered with 'tube-scout content professor map'.[/red]"
            )
            raise typer.Exit(code=1)
        _run_nc2_scan(project=project, project_dir=project_dir, professor_id=professor, resume=resume)
        return

    console.print("[bold]Running content scan pipeline...[/bold]\n")

    # Stage 1: Fingerprint
    console.print("[bold cyan]Stage 1/3: Fingerprint[/bold cyan]")
    from tube_scout.cli.errors import UserFacingError, render_error

    def _run_stage(stage_num: int, stage_name: str, fn) -> None:  # type: ignore[no-untyped-def]
        """Run a content-scan sub-stage; raise actionable error on failure.

        idea6 ADR-IDEA6-008 / FR-IDEA6-010 / SILENT-1..3 fix.
        Sub-stages with SystemExit code != 0 propagate via
        UserFacingError so the master content-scan pipeline aborts
        rather than printing "Content scan pipeline complete" with a
        broken intermediate artifact.
        """
        try:
            fn()
        except SystemExit as exc:
            code = getattr(exc, "code", 0)
            if code:
                err = UserFacingError(
                    message=(
                        f"Content-scan stage {stage_num}/3 '{stage_name}' "
                        f"failed (exit_code={code}). Subsequent stages "
                        "were not run."
                    ),
                    next_command=(
                        f"Run the failing sub-command in isolation: "
                        f"tube-scout content {stage_name.lower()} --channel {channel}"
                    ),
                )
                render_error(err)
                raise err

    _run_stage(
        1,
        "Fingerprint",
        lambda: content_fingerprint_command(
            channel=channel,
            project=project,
            project_dir=project_dir,
            year=None,
            semester=None,
            force_refresh=force_refresh,
        ),
    )

    # Stage 2: Compare
    console.print("\n[bold cyan]Stage 2/3: Compare[/bold cyan]")
    _run_stage(
        2,
        "Compare",
        lambda: content_compare_command(
            channel=channel,
            year_from=year_from,
            year_to=year_to,
            project=project,
            project_dir=project_dir,
            course=None,
            professor=None,
            mode="legacy",
        ),
    )

    # Stage 3: Quality
    console.print("\n[bold cyan]Stage 3/3: Quality[/bold cyan]")
    _run_stage(
        3,
        "Quality",
        lambda: content_quality_command(
            channel=channel,
            project=project,
            project_dir=project_dir,
            year=None,
            semester=None,
        ),
    )

    console.print("\n[bold green]Content scan pipeline complete.[/bold green]")


def _run_nc2_scan(project: str, project_dir: str, professor_id: str, resume: bool) -> None:
    """Execute the nC2 professor-pool matching pipeline.

    Args:
        project: Project path or 'latest'.
        project_dir: Projects root directory.
        professor_id: Professor identifier.
        resume: If True, resume from last in-progress checkpoint run.
    """
    import sqlite3
    from datetime import UTC, datetime

    from tube_scout.services.nc2_matcher import generate_nc2_pairs
    from tube_scout.services.pair_checkpoint import (
        finalize_run,
        iterate_unfinished_pairs,
        mark_pair_done,
        resume_run,
        start_run,
    )
    from tube_scout.services.policy_loader import load_policy

    mgr = resolve_project(project_dir, project, producer=is_producer("content"))
    db_path = _ensure_v2_schema(mgr.project_dir)
    policy = load_policy(mgr.project_dir)
    captions_dir = mgr.collect_dir

    run_id: str | None = None
    if resume:
        run_id = resume_run(professor_id, "M-nC2", db_path)
        if run_id:
            console.print(f"[bold]Resuming nC2 run {run_id} for professor '{professor_id}'...[/bold]")

    if not run_id:
        pairs = generate_nc2_pairs(
            professor_id=professor_id,
            db_path=db_path,
            captions_dir=captions_dir,
            cosine_cull_threshold=policy.matching_cosine_cull,
        )
        run_id = start_run(
            professor_id=professor_id,
            matching_mode="M-nC2",
            pair_count_total=len(pairs),
            db_path=db_path,
        )
        console.print(
            f"[bold]Starting nC2 run {run_id} — {len(pairs)} pairs for professor '{professor_id}'.[/bold]"
        )

    pool = None
    from tube_scout.services.professor_resolver import resolve_caption_pool
    pool = resolve_caption_pool(professor_id, db_path)

    now_fn = lambda: datetime.now(UTC).isoformat()
    conn = sqlite3.connect(str(db_path))
    processed = 0
    try:
        for pair_ref in iterate_unfinished_pairs(pool, "M-nC2", db_path):
            conn.execute(
                "INSERT OR IGNORE INTO comparison_results "
                "(source_video_id, target_video_id, matching_mode, professor_id, created_at) "
                "VALUES (?, ?, 'M-nC2', ?, ?)",
                (pair_ref.source_video_id, pair_ref.target_video_id, professor_id, now_fn()),
            )
            conn.commit()
            mark_pair_done(run_id, db_path)
            processed += 1
    finally:
        conn.close()

    finalize_run(run_id, db_path, "completed")
    console.print(f"[green]nC2 scan complete: {processed} pairs processed.[/green]")


# ---------------------------------------------------------------------------
# spec 011 placeholder commands — professor group
# ---------------------------------------------------------------------------


@professor_app.command("map")
def professor_map(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor_id: str = typer.Option(..., "--professor-id", help="Professor identifier."),
    display_name: str = typer.Option(..., "--display-name", help="Human-readable name."),
    channel: str = typer.Option(..., "--channel", help="Channel alias."),
    author: str = typer.Option(..., "--author", help="Author marker or __channel_owner__."),
    note: str | None = typer.Option(None, "--note", help="Optional notes."),
) -> None:
    """Register or extend a professor pool mapping.

    Args:
        project: Project directory.
        professor_id: Professor identifier.
        display_name: Human-readable name.
        channel: Channel alias.
        author: Author marker.
        note: Optional notes.
    """
    from tube_scout.services.professor_resolver import map_professor

    db_path = _ensure_v2_schema(project)
    try:
        mapping = map_professor(
            professor_id=professor_id,
            display_name=display_name,
            channel_alias=channel,
            author_marker=author,
            db_path=db_path,
            registered_by="cli",
            note=note,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    console.print(
        f"[green]Mapped professor '{mapping.professor_id}' "
        f"({mapping.display_name}) -> channel '{mapping.channel_alias}'.[/green]"
    )


@professor_app.command("list")
def professor_list(
    project: Path = typer.Option(..., "--project", help="Project directory."),
) -> None:
    """List all registered professor mappings.

    Args:
        project: Project directory.
    """
    from tube_scout.services.professor_resolver import list_professors

    db_path = _ensure_v2_schema(project)
    mappings = list_professors(db_path)
    if not mappings:
        console.print("[yellow]No professor mappings registered.[/yellow]")
        return

    for m in mappings:
        console.print(
            f"{m.professor_id}  {m.display_name}  {m.channel_alias}  "
            f"{m.author_marker}  {m.registered_by}"
        )


@professor_app.command("show")
def professor_show(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor_id: str = typer.Option(..., "--professor-id", help="Professor identifier."),
) -> None:
    """Show a single professor's mappings.

    Args:
        project: Project directory.
        professor_id: Professor identifier.

    Raises:
        NotImplementedError: Always — pending US1 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content professor show is not yet implemented. "
        "Pending US1 implementation (T034). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §5."
    )


@professor_app.command("unmap")
def professor_unmap(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor_id: str = typer.Option(..., "--professor-id", help="Professor identifier."),
    channel: str = typer.Option(..., "--channel", help="Channel alias to remove."),
    author: str = typer.Option(..., "--author", help="Author marker of the row."),
) -> None:
    """Remove a professor pool membership row.

    Args:
        project: Project directory.
        professor_id: Professor identifier.
        channel: Channel alias.
        author: Author marker.
    """
    from tube_scout.services.professor_resolver import unmap_professor

    db_path = _ensure_v2_schema(project)
    removed = unmap_professor(
        professor_id=professor_id,
        channel_alias=channel,
        author_marker=author,
        db_path=db_path,
    )
    if removed:
        console.print(
            f"[green]Unmapped professor '{professor_id}' from channel '{channel}' "
            f"(author: {author}).[/green]"
        )
    else:
        console.print(
            f"[yellow]No membership row found for professor '{professor_id}' "
            f"on channel '{channel}' (author: {author}).[/yellow]"
        )


# ---------------------------------------------------------------------------
# spec 011 placeholder commands — baseline group
# ---------------------------------------------------------------------------


@baseline_app.command("bootstrap")
def baseline_bootstrap(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor: str = typer.Option(..., "--professor", help="Professor identifier."),
    earliest_n: int = typer.Option(5, "--earliest-n", help="Number of earliest videos."),
    min_occurrences: int = typer.Option(3, "--min-occurrences", help="Minimum video occurrences."),
) -> None:
    """Seed baseline corpus from earliest N videos.

    Args:
        project: Project directory.
        professor: Professor identifier.
        earliest_n: Number of earliest videos to use.
        min_occurrences: Minimum occurrences threshold.

    Raises:
        NotImplementedError: Always — pending US2 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content baseline bootstrap is not yet implemented. "
        "Pending US2 implementation (T040). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §6."
    )


@baseline_app.command("add")
def baseline_add(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor: str = typer.Option(..., "--professor", help="Professor identifier."),
    phrase: str = typer.Option(..., "--phrase", help="Phrase text to add."),
    source_video: list[str] = typer.Option([], "--source-video", help="Source video IDs."),
    reason: str | None = typer.Option(None, "--reason", help="Reason for addition."),
) -> None:
    """Add a single phrase to a professor's baseline corpus.

    Args:
        project: Project directory.
        professor: Professor identifier.
        phrase: Phrase text.
        source_video: Source video IDs.
        reason: Reason for addition.

    Raises:
        NotImplementedError: Always — pending US2 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content baseline add is not yet implemented. "
        "Pending US2 implementation (T041). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §6."
    )


@baseline_app.command("list")
def baseline_list(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor: str | None = typer.Option(None, "--professor", help="Professor identifier filter."),
) -> None:
    """List baseline corpus phrases.

    Args:
        project: Project directory.
        professor: Optional professor filter.

    Raises:
        NotImplementedError: Always — pending US2 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content baseline list is not yet implemented. "
        "Pending US2 implementation (T042). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §6."
    )


@baseline_app.command("remove")
def baseline_remove(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor: str = typer.Option(..., "--professor", help="Professor identifier."),
    phrase: str = typer.Option(..., "--phrase", help="Phrase text to remove."),
) -> None:
    """Remove a phrase from a professor's baseline corpus.

    Args:
        project: Project directory.
        professor: Professor identifier.
        phrase: Phrase text to remove.

    Raises:
        NotImplementedError: Always — pending US2 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content baseline remove is not yet implemented. "
        "Pending US2 implementation (T043). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §6."
    )


# ---------------------------------------------------------------------------
# spec 011 placeholder commands — whitelist group
# ---------------------------------------------------------------------------


@whitelist_app.command("add-pair")
def whitelist_add_pair(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    pair_id: str | None = typer.Option(None, "--pair-id", help="Comparison result ID."),
    reason: str = typer.Option(..., "--reason", help="Reason for whitelisting."),
) -> None:
    """Whitelist a comparison pair (mark as FALSE_POSITIVE).

    Args:
        project: Project directory.
        pair_id: Comparison result ID.
        reason: Reason text.

    Raises:
        NotImplementedError: Always — pending US3 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content whitelist add-pair is not yet implemented. "
        "Pending US3 implementation (T050). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §7."
    )


@whitelist_app.command("add-phrase")
def whitelist_add_phrase(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor: str = typer.Option(..., "--professor", help="Professor identifier."),
    phrase: str = typer.Option(..., "--phrase", help="Phrase text."),
    reason: str = typer.Option(..., "--reason", help="Reason for whitelisting."),
) -> None:
    """Add a phrase to the per-professor whitelist.

    Args:
        project: Project directory.
        professor: Professor identifier.
        phrase: Phrase text.
        reason: Reason text.

    Raises:
        NotImplementedError: Always — pending US3 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content whitelist add-phrase is not yet implemented. "
        "Pending US3 implementation (T051). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §7."
    )


@whitelist_app.command("list")
def whitelist_list(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    professor: str | None = typer.Option(None, "--professor", help="Professor identifier filter."),
    type_filter: str | None = typer.Option(None, "--type", help="Filter by type: pair or phrase."),
) -> None:
    """List whitelist entries.

    Args:
        project: Project directory.
        professor: Optional professor filter.
        type_filter: Optional type filter (pair|phrase).

    Raises:
        NotImplementedError: Always — pending US3 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content whitelist list is not yet implemented. "
        "Pending US3 implementation (T052). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §7."
    )


@whitelist_app.command("export")
def whitelist_export(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    format: str = typer.Option(..., "--format", help="Export format: csv, xlsx, or markdown."),
    output: Path = typer.Option(..., "--output", help="Output file path."),
) -> None:
    """Export whitelist to CSV, XLSX, or Markdown.

    Args:
        project: Project directory.
        format: Export format (csv|xlsx|markdown).
        output: Output file path.

    Raises:
        NotImplementedError: Always — pending US3 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content whitelist export is not yet implemented. "
        "Pending US3 implementation (T053). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §7."
    )


@whitelist_app.command("remove")
def whitelist_remove(
    project: Path = typer.Option(..., "--project", help="Project directory."),
    type_filter: str = typer.Option(..., "--type", help="Entry type: pair or phrase."),
    id: int = typer.Option(..., "--id", help="Entry ID to remove."),
) -> None:
    """Remove a whitelist entry by ID.

    Args:
        project: Project directory.
        type_filter: Entry type (pair|phrase).
        id: Entry ID.

    Raises:
        NotImplementedError: Always — pending US3 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content whitelist remove is not yet implemented. "
        "Pending US3 implementation (T054). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §7."
    )


# ---------------------------------------------------------------------------
# spec 011 placeholder commands — policy group
# ---------------------------------------------------------------------------


@policy_app.command("show")
def policy_show(
    project: Path = typer.Option(..., "--project", help="Project directory."),
) -> None:
    """Display the current policy.yaml contents.

    Args:
        project: Project directory.

    Raises:
        NotImplementedError: Always — pending US4 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content policy show is not yet implemented. "
        "Pending US4 implementation (T058). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §8."
    )


@policy_app.command("validate")
def policy_validate(
    project: Path = typer.Option(..., "--project", help="Project directory."),
) -> None:
    """Validate policy.yaml against spec 011 schema rules.

    Args:
        project: Project directory.

    Raises:
        NotImplementedError: Always — pending US4 implementation.
    """
    _ensure_v2_schema(project)
    raise NotImplementedError(
        "tube-scout content policy validate is not yet implemented. "
        "Pending US4 implementation (T059). "
        "See specs/011-reuse-fullstack-subtitle/contracts/cli_content.md §8."
    )
