"""Search CLI subcommand for structured video search."""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def search_command(
    config: str | None = typer.Option(
        None,
        "--config",
        help="YAML search configuration file.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias.",
    ),
    professor: str | None = typer.Option(
        None,
        "--professor",
        help="Filter by professor name (partial match).",
    ),
    course: str | None = typer.Option(
        None,
        "--course",
        help="Filter by course name (partial match).",
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
    week_from: int | None = typer.Option(
        None,
        "--week-from",
        help="Filter week range start.",
    ),
    week_to: int | None = typer.Option(
        None,
        "--week-to",
        help="Filter week range end.",
    ),
    export: str | None = typer.Option(
        None,
        "--export",
        help="Export results to JSON file.",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        help="Override output directory.",
    ),
) -> None:
    """Search videos using YAML config or CLI flags.

    Args:
        config: Path to YAML search configuration.
        channel: Channel alias for data source.
        professor: Professor name filter.
        course: Course name filter.
        year: Academic year filter.
        semester: Semester filter.
        week_from: Week range start.
        week_to: Week range end.
        export: Path to export results as JSON.
        output_dir: Override output directory.
    """
    from tube_scout.services.search_service import SearchService

    # Build query from config or CLI flags
    if config:
        try:
            query = SearchService.load_config(Path(config))
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=2)
        except ValueError as e:
            console.print(f"[red]Failed to parse search configuration: {e}[/red]")
            raise typer.Exit(code=2)
    else:
        query = SearchService.from_cli_flags(
            professor=professor,
            course=course,
            year=year,
            semester=semester,
            week_from=week_from,
            week_to=week_to,
        )

    # Load parsed titles
    parsed_titles = _load_parsed_titles(channel, output_dir=output_dir)
    if not parsed_titles:
        alias = channel or "default"
        console.print(
            f"[yellow]No videos found for channel '{alias}' "
            "matching the given criteria.[/yellow]"
        )
        raise typer.Exit(code=1)

    # Execute search
    results = SearchService.search(parsed_titles, query)

    if not results:
        console.print("[yellow]No results found matching the search criteria.[/yellow]")
        raise typer.Exit(code=1)

    # Display results
    table = Table(title=f"Search Results ({len(results)} videos)")
    table.add_column("Video ID", style="dim")
    table.add_column("Professor", style="cyan")
    table.add_column("Course", style="green")
    table.add_column("Year", style="yellow")
    table.add_column("Week", style="yellow")
    table.add_column("Session", style="yellow")

    for pt in results:
        table.add_row(
            pt.video_id,
            ", ".join(pt.professor) if pt.professor else "-",
            pt.course or "-",
            str(pt.year) if pt.year else "-",
            str(pt.week) if pt.week else "-",
            str(pt.session) if pt.session else "-",
        )

    console.print(table)

    # Export if requested
    if export:
        export_path = Path(export)
        export_data = [pt.model_dump(mode="json") for pt in results]
        export_path.write_text(
            json.dumps(export_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        console.print(f"[green]Results exported to {export_path}[/green]")


def _load_parsed_titles(
    channel: str | None,
    output_dir: str | None = None,
) -> list:
    """Load parsed titles from the latest output directory.

    Args:
        channel: Optional channel alias.
        output_dir: Optional output directory override.

    Returns:
        List of ParsedTitle objects.
    """
    from tube_scout.models.parsed_title import ParsedTitle
    from tube_scout.output.manager import OutputManager

    base = Path(output_dir) if output_dir else None
    mgr = OutputManager(base_dir=base)
    latest = mgr.get_latest()
    if latest is None:
        return []

    # Look for parsed titles in the latest output
    parsed_dir = latest / "parsed"
    if not parsed_dir.exists():
        return []

    results = []
    for json_file in parsed_dir.rglob("parsed_titles.json"):
        from tube_scout.storage.json_store import read_json

        data = read_json(json_file)
        if data and isinstance(data, list):
            results.extend(ParsedTitle(**item) for item in data)

    return results
