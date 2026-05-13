"""transcript subcommands: export and export-bulk (spec 013 FR-040~FR-042)."""

import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tube_scout.services.audit_writer import AuditWriter
from tube_scout.services.kb_export import ExportFormat, export_bulk, export_transcript

console = Console()


def export_command(
    video_id: str,
    transcripts_dir: Path,
    output: Path,
    format_: ExportFormat = "txt",
    keep_timestamps: bool = False,
    clean_fillers: bool = False,
    with_meta: bool = False,
    audit_dir: Optional[Path] = None,
) -> None:
    """Export a single transcript to KB-ingestible plain text.

    Args:
        video_id: YouTube video ID.
        transcripts_dir: Directory containing <video_id>.json transcript files.
        output: Destination file path.
        format_: Output format — 'txt', 'md', or 'jsonl'.
        keep_timestamps: Include [HH:MM:SS] timestamps.
        clean_fillers: Remove Korean ASR filler expressions.
        with_meta: Include video metadata header (md/jsonl only).
        audit_dir: Project root for audit CSV; defaults to transcripts_dir parent.

    Raises:
        FileNotFoundError: Transcript JSON not found.
    """
    transcript_path = transcripts_dir / f"{video_id}.json"
    timestamp = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    _audit_dir = audit_dir if audit_dir is not None else transcripts_dir.parent

    result = export_transcript(
        transcript_path,
        output,
        format_=format_,
        keep_timestamps=keep_timestamps,
        clean_fillers=clean_fillers,
        with_meta=with_meta,
    )

    AuditWriter(_audit_dir).append_row("kb_export", {
        "video_id": video_id,
        "result": "success",
        "reason": "exported",
        "format": format_,
        "output_path": str(output),
        "byte_count": result.byte_count,
        "timestamp": timestamp,
    })


def export_bulk_command(
    transcripts_dir: Path,
    output_dir: Path,
    video_ids_file: Optional[Path],
    export_all: bool,
    format_: ExportFormat = "txt",
    keep_timestamps: bool = False,
    clean_fillers: bool = False,
    with_meta: bool = False,
    audit_dir: Optional[Path] = None,
) -> None:
    """Export multiple transcripts to output_dir.

    Args:
        transcripts_dir: Directory containing <video_id>.json transcript files.
        output_dir: Destination directory (must exist).
        video_ids_file: Path to text file with one video_id per line; None = use export_all.
        export_all: Export all transcripts found in transcripts_dir.
        format_: Output format — 'txt', 'md', or 'jsonl'.
        keep_timestamps: Include timestamps.
        clean_fillers: Remove Korean ASR filler expressions.
        with_meta: Include metadata header.
        audit_dir: Project root for audit CSV; defaults to transcripts_dir parent.

    Raises:
        ValueError: Neither video_ids_file nor export_all specified.
    """
    if not export_all and video_ids_file is None:
        raise ValueError("Specify --video-ids-file or --all to select transcripts.")

    _audit_dir = audit_dir if audit_dir is not None else transcripts_dir.parent
    timestamp = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    writer = AuditWriter(_audit_dir)

    video_ids: list[str] | None = None
    if video_ids_file is not None:
        video_ids = [
            line.strip()
            for line in video_ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    from tube_scout.services.progress_reporter import make_progress_reporter

    total = len(video_ids) if video_ids is not None else len(list(transcripts_dir.glob("*.json")))
    with make_progress_reporter("kb_export", total) as progress:
        bulk_result = export_bulk(
            transcripts_dir,
            output_dir,
            video_ids=video_ids,
            format_=format_,
            keep_timestamps=keep_timestamps,
            clean_fillers=clean_fillers,
            with_meta=with_meta,
            progress=progress,
        )

    # Write one audit row per exported video
    if video_ids is not None:
        ids_to_audit = video_ids
    else:
        ids_to_audit = [f.stem for f in transcripts_dir.glob("*.json")]

    for vid in ids_to_audit:
        out_file = output_dir / f"{vid}.{format_}"
        if out_file.exists():
            writer.append_row("kb_export", {
                "video_id": vid,
                "result": "success",
                "reason": "exported",
                "format": format_,
                "output_path": str(out_file),
                "byte_count": out_file.stat().st_size,
                "timestamp": timestamp,
            })
        else:
            writer.append_row("kb_export", {
                "video_id": vid,
                "result": "skip",
                "reason": "transcript_not_found",
                "format": format_,
                "output_path": "",
                "byte_count": 0,
                "timestamp": timestamp,
            })

    console.print(
        f"[green]Exported {bulk_result.exported_count}/{bulk_result.total_videos} transcripts "
        f"to {output_dir}[/green]"
    )


def transcript_export_typer(
    video_id: str = typer.Option(..., "--video-id", help="YouTube video ID."),
    transcripts_dir: str = typer.Option(
        "./01_collect/transcripts", "--transcripts-dir", help="Transcripts directory."
    ),
    output: Optional[str] = typer.Option(None, "--output", help="Output file path."),
    format_: str = typer.Option("txt", "--format", help="Output format: txt, md, jsonl."),
    keep_timestamps: bool = typer.Option(False, "--keep-timestamps", help="Include timestamps."),
    clean_fillers: bool = typer.Option(False, "--clean-fillers", help="Remove Korean ASR fillers."),
    with_meta: bool = typer.Option(False, "--with-meta", help="Include metadata header."),
    data_dir: str = typer.Option("./data", "--data-dir", help="Data directory."),
) -> None:
    """Export a single transcript to KB-ingestible plain text."""
    transcripts_path = Path(transcripts_dir)
    output_path = (
        Path(output)
        if output is not None
        else Path("./kb_export") / f"{video_id}.{format_}"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        export_command(
            video_id=video_id,
            transcripts_dir=transcripts_path,
            output=output_path,
            format_=format_,  # type: ignore[arg-type]
            keep_timestamps=keep_timestamps,
            clean_fillers=clean_fillers,
            with_meta=with_meta,
            audit_dir=Path(data_dir).parent,
        )
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Exported {video_id} → {output_path}[/green]")


def transcript_export_bulk_typer(
    channel: Optional[str] = typer.Option(None, "--channel", help="Channel alias."),
    video_ids_file: Optional[str] = typer.Option(
        None, "--video-ids-file", help="Text file with one video_id per line."
    ),
    export_all: bool = typer.Option(False, "--all", help="Export all transcripts."),
    format_: str = typer.Option("txt", "--format", help="Output format: txt, md, jsonl."),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", help="Output directory."),
    keep_timestamps: bool = typer.Option(False, "--keep-timestamps"),
    clean_fillers: bool = typer.Option(False, "--clean-fillers"),
    with_meta: bool = typer.Option(False, "--with-meta"),
    data_dir: str = typer.Option("./data", "--data-dir"),
    transcripts_dir: Optional[str] = typer.Option(
        None, "--transcripts-dir", help="Transcripts directory (overrides --channel default)."
    ),
) -> None:
    """Bulk-export transcripts to a directory."""
    if transcripts_dir is not None:
        t_dir = Path(transcripts_dir)
    elif channel is not None:
        t_dir = Path(data_dir) / "01_collect" / "transcripts"
    else:
        console.print("[red]Specify --channel or --transcripts-dir.[/red]")
        raise typer.Exit(code=1)

    alias = channel or "default"
    o_dir = Path(output_dir) if output_dir else Path("./kb_export") / alias
    o_dir.mkdir(parents=True, exist_ok=True)

    ids_file_path = Path(video_ids_file) if video_ids_file else None

    try:
        export_bulk_command(
            transcripts_dir=t_dir,
            output_dir=o_dir,
            video_ids_file=ids_file_path,
            export_all=export_all,
            format_=format_,  # type: ignore[arg-type]
            keep_timestamps=keep_timestamps,
            clean_fillers=clean_fillers,
            with_meta=with_meta,
            audit_dir=Path(data_dir).parent,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
