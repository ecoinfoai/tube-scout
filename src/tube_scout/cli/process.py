"""Process subcommands for tube-scout (spec 013 FR-024~FR-026)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import typer
from rich.console import Console

console = Console()


def process_normalize_transcripts_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias.",
    ),
    video_ids_str: str = typer.Option(
        "",
        "--video-ids",
        help="Comma-separated video IDs to normalize.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing normalized transcripts.",
    ),
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Work root for channel data directories.",
    ),
    db_path_str: str = typer.Option(
        "",
        "--db-path",
        help="Path to content_reuse.db (defaults to <data-dir>/content_reuse.db).",
    ),
) -> None:
    """Normalize raw transcripts to transcripts_normalized/ (FR-024~FR-026).

    Args:
        channel: Channel alias.
        video_ids_str: Comma-separated list of video IDs; empty = all with raw transcript.
        force: If True, overwrite existing normalized output.
        data_dir: Work root directory.
        db_path_str: Override DB path.
    """
    import datetime

    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.services.text_normalizer import detect_source_conflict, normalize_transcript_json

    work_root = Path(data_dir)
    db = Path(db_path_str) if db_path_str else work_root / "content_reuse.db"
    transcript_dir = work_root / channel / "01_collect" / "transcripts"
    normalized_dir = work_root / channel / "01_collect" / "transcripts_normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    # Resolve video_ids list
    if video_ids_str:
        video_ids = [v.strip() for v in video_ids_str.split(",") if v.strip()]
    elif db.exists():
        try:
            with sqlite3.connect(db) as conn:
                rows = conn.execute(
                    "SELECT ps.video_id FROM processing_status ps"
                    " JOIN video_metadata vm ON vm.video_id = ps.video_id"
                    " JOIN channel_metadata cm ON cm.channel_id = vm.channel_id"
                    " WHERE cm.channel_alias = ?",
                    (channel,),
                ).fetchall()
            video_ids = [r[0] for r in rows]
        except Exception as exc:
            console.print(f"[red]DB query error: {exc}[/red]")
            raise typer.Exit(code=2) from exc
    else:
        # Fall back to filesystem scan
        video_ids = [p.stem for p in transcript_dir.glob("*.json") if p.is_file()]

    if not video_ids:
        console.print("[yellow]No videos to normalize.[/yellow]")
        raise typer.Exit(code=0)

    audit = AuditWriter(work_root / channel)

    for video_id in video_ids:
        ts = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        raw_path = transcript_dir / f"{video_id}.json"
        norm_path = normalized_dir / f"{video_id}.json"

        if not raw_path.exists():
            audit.append_row("normalize", {
                "video_id": video_id,
                "result": "skip",
                "reason": "raw_not_found",
                "timestamp": ts,
            })
            continue

        # FR-024 single-source rule: conflict check
        conflict = detect_source_conflict(transcript_dir, video_id)
        if conflict is not None:
            console.print(
                f"Conflict: video_id={video_id} has both ASR ('whisper') and API caption sources. "
                "Single-source rule requires operator decision. "
                f"Remove one of: {conflict}"
            )
            raise typer.Exit(code=6)

        try:
            written = normalize_transcript_json(raw_path, norm_path, force=force)
        except Exception as exc:
            console.print(f"[yellow]fail[/yellow] {video_id}: {exc}")
            audit.append_row("normalize", {
                "video_id": video_id,
                "result": "fail",
                "reason": str(exc),
                "timestamp": ts,
            })
            continue

        reason = "normalized" if written else "skip_existing"
        result_tag = "success" if written else "skip"
        audit.append_row("normalize", {
            "video_id": video_id,
            "result": result_tag,
            "reason": reason,
            "timestamp": ts,
        })
        indicator = "[green]ok[/green]" if written else "[dim]skip[/dim]"
        console.print(f"{indicator} {video_id}")
