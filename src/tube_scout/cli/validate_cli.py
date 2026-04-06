"""Validate CLI subcommand for title validation."""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.validation import ValidationFinding
from tube_scout.output.manager import OutputManager
from tube_scout.services.validator import run_all_validations, save_validation_results

console = Console()


def validate_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias to validate.",
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
    output: str = typer.Option(
        "table",
        "--output",
        help="Output format: table, json, or report.",
    ),
    rules: str | None = typer.Option(
        None,
        "--rules",
        help="Comma-separated rule IDs to run (e.g., V-001,V-003).",
    ),
    data_dir: str = typer.Option(
        "./output",
        "--data-dir",
        help="Directory containing parsed data.",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        help="Override output directory.",
    ),
) -> None:
    """Run title validation rules on parsed video data.

    Args:
        channel: Channel alias to validate.
        year: Academic year filter.
        semester: Semester filter (1 or 2).
        output: Output format (table, json, report).
        rules: Comma-separated rule IDs to run.
        data_dir: Directory containing parsed data.
        output_dir: Override output directory.
    """
    # Find latest parsed titles
    base = Path(output_dir) if output_dir else Path(data_dir)
    manager = OutputManager(base_dir=base)
    latest = manager.get_latest()
    if latest is None:
        console.print("[red]No output runs found. Run parsing first.[/red]")
        raise typer.Exit(code=1)

    parsed_path = latest / "parsed" / channel / "parsed_titles.json"
    if not parsed_path.exists():
        console.print(
            f"[red]Parsed titles not found for channel '{channel}' "
            f"at {parsed_path}[/red]"
        )
        raise typer.Exit(code=1)

    with open(parsed_path) as f:
        raw_data = json.load(f)

    plist = (
        raw_data if isinstance(raw_data, list) else raw_data.get("parsed_titles", [])
    )
    parsed_titles = [ParsedTitle(**item) for item in plist]

    # Apply year/semester filters
    if year is not None:
        parsed_titles = [pt for pt in parsed_titles if pt.year == year]
    if semester is not None:
        parsed_titles = [pt for pt in parsed_titles if pt.semester == semester]

    # Load video metadata if available
    videos_path = latest / "raw" / "channels" / channel / "videos_meta.json"
    videos: list[dict] = []
    if videos_path.exists():
        with open(videos_path) as f:
            videos = json.load(f)

    # Run validation
    findings = run_all_validations(parsed_titles, videos)

    # Filter by rules if specified
    if rules:
        rule_set = {r.strip() for r in rules.split(",")}
        findings = [f for f in findings if f.rule_id in rule_set]

    # Output results
    if output == "json":
        data = [f.model_dump() for f in findings]
        console.print_json(json.dumps(data, ensure_ascii=False))
    elif output == "report":
        run_dir = manager.create_run()
        validation_dir = run_dir / "validation" / channel
        out_path = save_validation_results(findings, validation_dir)
        manager.update_latest_link(run_dir)
        console.print(f"[green]Validation results saved to {out_path}[/green]")
    else:
        _print_table(findings)

    console.print(
        f"\n[bold]Total findings: {len(findings)}[/bold] "
        f"(ERROR: {sum(1 for f in findings if f.severity == 'ERROR')}, "
        f"WARNING: {sum(1 for f in findings if f.severity == 'WARNING')}, "
        f"INFO: {sum(1 for f in findings if f.severity == 'INFO')})"
    )


def _print_table(findings: list[ValidationFinding]) -> None:
    """Print validation findings as a rich table.

    Args:
        findings: List of validation findings to display.
    """
    table = Table(title="Validation Findings")
    table.add_column("Rule", style="cyan", width=6)
    table.add_column("Severity", width=8)
    table.add_column("Professor", style="magenta", width=10)
    table.add_column("Description", style="white")
    table.add_column("Videos", style="dim", width=15)

    for finding in findings:
        severity_style = {
            "ERROR": "bold red",
            "WARNING": "yellow",
            "INFO": "blue",
        }.get(finding.severity, "white")

        table.add_row(
            finding.rule_id,
            f"[{severity_style}]{finding.severity}[/{severity_style}]",
            finding.professor or "-",
            finding.description[:60],
            ", ".join(finding.video_ids[:3]),
        )

    console.print(table)
