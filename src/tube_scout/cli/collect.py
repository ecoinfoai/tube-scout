"""Collect subcommands for tube-scout."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from tube_scout.cli.progress import create_progress
from tube_scout.cli.project import is_producer, resolve_project
from tube_scout.models.config import AppConfig, CollectionState
from tube_scout.services.youtube_analytics import YouTubeAnalyticsService
from tube_scout.services.youtube_data import YouTubeDataService
from tube_scout.storage.checkpoint import load_checkpoint, save_checkpoint
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import write_parquet

console = Console()

_ENV_TRANSCRIPT_SOURCE = "TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE"


def resolve_alias_to_channel_id(alias: str) -> str:
    """Resolve channel alias to channel ID via spec 003 registry.

    Args:
        alias: Channel alias string.

    Returns:
        YouTube channel ID string.

    Raises:
        KeyError: If alias is not registered.
        SystemExit: With code 5 if called via CLI gate (caller must handle).
    """
    from tube_scout.cli.errors import UserFacingError
    from tube_scout.services.auth import load_registry, resolve_channel_alias

    try:
        return resolve_channel_alias(alias, load_registry())
    except (UserFacingError, KeyError, ValueError) as exc:
        raise KeyError(f"Channel alias '{alias}' is not registered.") from exc


def dispatch_transcript_source(
    source: str,
    **kwargs: object,
) -> None:
    """Dispatch transcript collection to api or ytdlp backend.

    Args:
        source: 'api' or 'ytdlp'.
        **kwargs: Backend-specific arguments passed through.
    """
    if source == "ytdlp":
        _dispatch_ytdlp_transcripts(**kwargs)
    else:
        _dispatch_api_transcripts(**kwargs)


def _dispatch_ytdlp_transcripts(  # noqa: C901
    channel: str | None = None,
    all_channels: object = False,
    force: bool = False,
    cookies_browser: str | None = "brave",
    cookies_path: str | None = None,
    sleep_seconds: tuple[float, float] = (30.0, 60.0),
    audit_writer: object = None,
    **kwargs: object,
) -> None:
    """Fetch captions via yt-dlp for a channel or all channels.

    Pipeline per video:
      fetch_caption_via_ytdlp → srv3_to_transcript_json → atomic JSON write
      → audit_writer.append_transcript_row

    Args:
        channel: Channel alias to process.
        all_channels: If True, process all registered channels.
        force: If True, re-fetch even when transcript JSON exists.
        cookies_browser: Browser for yt-dlp --cookies-from-browser.
        cookies_path: Path to 0600 cookies.txt, overrides cookies_browser.
        sleep_seconds: (min, max) sleep between yt-dlp calls.
        audit_writer: AuditWriter for transcripts_audit.csv rows.
        **kwargs: Ignored extra args from dispatch_transcript_source.
    """
    import datetime
    import json
    import os
    import tempfile

    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.services.srv3_parser import Srv3ParseError, pick_priority_track, srv3_to_transcript_json
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp
    from tube_scout.services.ytdlp_errors import YtdlpError

    mgr = resolve_project("./projects", None, producer=False)
    project_dir = Path(mgr.project_dir)
    transcript_dir = project_dir / "01_collect" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)

    _audit: AuditWriter = audit_writer if isinstance(audit_writer, AuditWriter) else AuditWriter(project_dir)  # type: ignore[assignment]

    cookies_path_obj = Path(cookies_path) if cookies_path else None
    cookies_src = f"file:{cookies_path}" if cookies_path else f"browser:{cookies_browser or 'brave'}"

    def _process_channel(alias: str, channel_id: str) -> None:
        channel_dir = project_dir / "01_collect" / "channels" / channel_id
        meta_path = channel_dir / "videos_meta.json"
        if not meta_path.exists():
            console.print(
                f"[yellow]No videos_meta.json for channel '{alias}'. "
                "Run `tube-scout collect videos` first.[/yellow]"
            )
            return

        videos_data = read_json(meta_path) or []
        video_ids = [v["video_id"] for v in videos_data if "video_id" in v]

        ts_now = datetime.datetime.now(tz=datetime.UTC).isoformat()

        for video_id in video_ids:
            json_path = transcript_dir / f"{video_id}.json"
            if not force and json_path.exists():
                _audit.append_transcript_row({
                    "video_id": video_id,
                    "result": "skip",
                    "reason": "skip_existing",
                    "source": "",
                    "timestamp": ts_now,
                    "cookies_source": cookies_src,
                })
                continue

            try:
                manual_path, auto_path = fetch_caption_via_ytdlp(
                    video_url=f"https://youtu.be/{video_id}",
                    output_dir=transcript_dir,
                    cookies_browser=cookies_browser,
                    cookies_path=cookies_path_obj,
                    sleep_seconds=sleep_seconds,
                )
            except YtdlpError as exc:
                _audit.append_transcript_row({
                    "video_id": video_id,
                    "result": "fail",
                    "reason": type(exc).__name__,
                    "source": "",
                    "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
                    "cookies_source": cookies_src,
                })
                console.print(f"  [red]yt-dlp error {video_id}: {exc}[/red]")
                continue

            track = pick_priority_track(manual_path, auto_path)
            if track is None:
                _audit.append_transcript_row({
                    "video_id": video_id,
                    "result": "skip",
                    "reason": "no_captions_available",
                    "source": "",
                    "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
                    "cookies_source": cookies_src,
                })
                continue

            chosen_path, source_value = track
            try:
                transcript = srv3_to_transcript_json(
                    chosen_path.read_text(encoding="utf-8"),
                    video_id=video_id,
                    source=source_value,
                )
            except Srv3ParseError as exc:
                _audit.append_transcript_row({
                    "video_id": video_id,
                    "result": "fail",
                    "reason": "srv3_parse_error",
                    "source": source_value,
                    "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
                    "cookies_source": cookies_src,
                })
                console.print(f"  [yellow]srv3 parse error {video_id}: {exc}[/yellow]")
                continue

            # Atomic JSON write
            fd, tmp_name = tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(transcript, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, json_path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise

            _audit.append_transcript_row({
                "video_id": video_id,
                "result": "ok",
                "reason": "fetched",
                "source": source_value,
                "timestamp": transcript.get("fetched_at", datetime.datetime.now(tz=datetime.UTC).isoformat()),
                "cookies_source": cookies_src,
            })

    if all_channels:
        from tube_scout.services.auth import load_registry
        registry = load_registry()
        for alias, entry in registry.items():
            channel_id = getattr(entry, "channel_id", None) or resolve_alias_to_channel_id(alias)
            _process_channel(alias, channel_id)
    elif channel:
        channel_id = resolve_alias_to_channel_id(channel)
        _process_channel(channel, channel_id)
    else:
        console.print(
            "[yellow]_dispatch_ytdlp_transcripts: pass --channel or --all-channels.[/yellow]"
        )


def _dispatch_api_transcripts(**kwargs: object) -> None:
    """Data API transcript backend — delegates to existing spec 010 logic."""


def dispatch_audio_fingerprint(
    channel: str | None = None,
    all_channels: object = False,
    force: bool = False,
    audio_temp: Path | None = None,
    db_path: Path | None = None,
    video_ids: list[str] | None = None,
    cookies_browser: str = "brave",
    cookies_path: str | None = None,
    sleep_seconds: tuple[float, float] = (30.0, 60.0),
    audit_writer: object = None,
    current_video_id_ref: list[str] | None = None,
    **kwargs: object,
) -> None:
    """Dispatch audio extraction + fingerprint + DB persist pipeline.

    Args:
        channel: Channel alias to process.
        all_channels: If True, process all registered channels.
        force: If True, overwrite existing fingerprint rows.
        audio_temp: Directory for temporary audio files.
        db_path: Path to content_reuse.db SQLite database.
        video_ids: Explicit list of video IDs to process (overrides channel lookup).
        cookies_browser: Browser name for yt-dlp cookie extraction.
        cookies_path: Optional path to cookies.txt file.
        sleep_seconds: (min, max) sleep range between yt-dlp calls.
        audit_writer: AuditWriter instance for fingerprint_audit.csv rows.
        current_video_id_ref: Mutable single-element list updated to the
            in-progress video_id (for SIGINT handler interrupted row).
        **kwargs: Additional arguments (ignored).
    """
    import datetime

    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp
    from tube_scout.services.ytdlp_errors import FingerprintExtractError
    from tube_scout.storage.content_db import (
        audio_fingerprint_exists,
        insert_audio_fingerprint,
    )

    if video_ids is None:
        console.print(
            "[yellow]dispatch_audio_fingerprint: video_ids not provided; "
            "pass --channel or an explicit video_ids list.[/yellow]"
        )
        return

    cookies_src = "file" if cookies_path else "brave"

    for video_id in video_ids:
        # FIX-4: update current_video_id_ref so SIGINT handler writes correct video_id
        if current_video_id_ref is not None:
            current_video_id_ref[0] = video_id

        already_done = (
            db_path is not None and audio_fingerprint_exists(db_path, video_id)
        )
        if not force and already_done:
            if audit_writer is not None and hasattr(audit_writer, "append_fingerprint_row"):
                audit_writer.append_fingerprint_row({
                    "video_id": video_id,
                    "result": "skip",
                    "reason": "skip_existing",
                    "duration_sec": None,
                    "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
                    "cookies_source": cookies_src,
                })
            continue

        audio_path: Path | None = None
        try:
            temp_dir = audio_temp if audio_temp is not None else Path(".")
            audio_path = fetch_audio_via_ytdlp(
                video_url=f"https://youtu.be/{video_id}",
                output_dir=temp_dir,
                cookies_browser=cookies_browser,
                cookies_path=Path(cookies_path) if cookies_path else None,
                sleep_seconds=sleep_seconds,
            )
            try:
                fp_bytes, duration = extract_chromaprint_fingerprint(audio_path)
            except FingerprintExtractError as fp_err:
                console.print(
                    f"  [yellow]fingerprint skip {video_id}: {fp_err}[/yellow]"
                )
                if audit_writer is not None and hasattr(
                    audit_writer, "append_fingerprint_row"
                ):
                    audit_writer.append_fingerprint_row({
                        "video_id": video_id,
                        "result": "fail",
                        "reason": "fpcalc_failed",
                        "duration_sec": None,
                        "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
                        "cookies_source": cookies_src,
                    })
                continue
            if db_path is not None:
                extracted_at = datetime.datetime.now(tz=datetime.UTC).isoformat()
                insert_audio_fingerprint(
                    db_path, video_id, fp_bytes, duration, extracted_at
                )
            if audit_writer is not None and hasattr(audit_writer, "append_fingerprint_row"):
                audit_writer.append_fingerprint_row({
                    "video_id": video_id,
                    "result": "success",
                    "reason": "captured",
                    "duration_sec": duration,
                    "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
                    "cookies_source": cookies_src,
                })
        finally:
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)


def _is_valid_cached_transcript(path: Path) -> bool:
    """Check whether a cached transcript JSON is reusable for resume.

    Spec 010 FR-010-04 / EC-010-A/B/C/G: a cache file is reusable iff it
    is a regular file, parses as JSON, has a ``segments`` key, and the
    segments list is non-empty. Any deviation (corrupt JSON, directory,
    empty list, missing key) returns ``False`` so the orchestrator
    re-fetches transparently.

    Args:
        path: Absolute path to ``<project>/01_collect/transcripts/<vid>.json``.

    Returns:
        ``True`` only when the file is safe to skip.
    """
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    segments = data.get("segments") if isinstance(data, dict) else None
    return isinstance(segments, list) and len(segments) > 0


def _read_cached_segment_count(path: Path) -> int:
    """Return the segment count of a validated cached transcript JSON.

    Caller is expected to have already passed :func:`_is_valid_cached_transcript`.
    Returns ``0`` defensively on any unexpected read failure.

    Args:
        path: Path to a cached transcript JSON.

    Returns:
        Number of segments in the cached transcript, or 0 on read failure.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        segments = data.get("segments", []) if isinstance(data, dict) else []
        return len(segments) if isinstance(segments, list) else 0
    except (OSError, json.JSONDecodeError):
        return 0


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomic JSON write using same-directory tmp + os.replace.

    Spec 010 FR-010-08: a SIGINT/crash mid-write must not leave a
    half-written file that future skip-existing checks could mistake for
    valid cache. Writing to a sibling ``.tmp`` and replacing atomically
    guarantees readers either see the old content or the new content,
    never a torn write.

    Args:
        path: Final destination of the JSON.
        payload: JSON-serialisable mapping.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp_path, path)


def _load_config(data_dir: Path) -> AppConfig:
    """Load and validate config from data directory.

    Args:
        data_dir: Root data directory.

    Returns:
        Validated AppConfig.

    Raises:
        typer.Exit: If config is not found.
    """
    config_data = read_json(data_dir / "config.json")
    if config_data is None:
        console.print("[red]No configuration found. Run 'tube-scout init' first.[/red]")
        raise typer.Exit(code=1)
    return AppConfig(**config_data)


def collect_videos_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="User data directory (config, credentials).",
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
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Ignore checkpoint, re-collect all.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (uses multi-channel token).",
    ),
) -> None:
    """Collect video metadata from YouTube Data API.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        force_refresh: Whether to ignore existing checkpoints.
        channel: Optional channel alias for multi-channel auth.
    """
    from tube_scout.cli.errors import UserFacingError, render_error
    from tube_scout.services.auth import (
        build_data_client,
        load_registry,
        resolve_channel_alias,
    )

    try:
        alias = resolve_channel_alias(channel, load_registry())
    except UserFacingError as e:
        render_error(e)
        raise typer.Exit(code=1)

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(project_dir, project, producer=is_producer("collect.videos"))

    try:
        client = build_data_client(alias)
        service = YouTubeDataService(client=client)
        console.print(f"[dim]Using channel auth for '{alias}'[/dim]")
    except UserFacingError as e:
        render_error(e)
        raise typer.Exit(code=1)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    for channel_config in config.channels:
        channel_id = channel_config.channel_id
        professor_name = channel_config.professor_name

        # Check checkpoint
        if not force_refresh:
            checkpoint = load_checkpoint(mgr.checkpoint_dir, channel_id, "videos")
            if checkpoint and checkpoint.status == "completed":
                console.print(
                    f"[yellow]Videos already collected for {channel_id}. "
                    f"Use --force-refresh to re-collect.[/yellow]"
                )
                continue

        console.print(f"[bold]Collecting videos for channel {channel_id}...[/bold]")

        # Save in-progress checkpoint
        state = CollectionState(
            channel_id=channel_id,
            phase="videos",
            started_at=datetime.now(UTC),
            status="in_progress",
        )
        save_checkpoint(mgr.checkpoint_dir, state)

        try:
            # Get channel info
            channel_info = service.get_channel_info(channel_id)
            console.print(
                f"  Channel: {channel_info['channel_name']} "
                f"({channel_info['total_video_count']} videos total)"
            )

            # List all videos
            with create_progress() as progress:
                task = progress.add_task("Listing videos...", total=None)
                all_videos = service.list_all_videos(
                    channel_info["uploads_playlist_id"]
                )
                progress.update(task, completed=len(all_videos))

            # Filter by professor name
            filtered = service.filter_by_professor(all_videos, professor_name)
            console.print(
                f"  Found {len(filtered)} videos matching '{professor_name}' "
                f"(out of {len(all_videos)} total)"
            )

            if not filtered:
                console.print(
                    "[yellow]No videos found matching the professor name. "
                    "Check spelling or try a different name.[/yellow]"
                )

            # Get detailed stats for filtered videos
            if filtered:
                video_ids = [v["video_id"] for v in filtered]
                details = service.get_video_details(video_ids)

                # Merge details into video records
                now = datetime.now(UTC).isoformat()
                for video in filtered:
                    vid_id = video["video_id"]
                    if vid_id in details:
                        video.update(details[vid_id])
                    video["channel_id"] = channel_id
                    video["collected_at"] = now

            # Save to collect/channels/{channel_id}/
            channel_dir = mgr.collect_dir / "channels" / channel_id
            channel_dir.mkdir(parents=True, exist_ok=True)

            write_json(channel_dir / "videos_meta.json", filtered)

            # Also save as Parquet for analytics (T024)
            if filtered:
                import polars as pl

                df = pl.DataFrame(filtered)
                write_parquet(channel_dir / "videos_meta.parquet", df)

            write_json(
                channel_dir / "channel_meta.json",
                {
                    **channel_info,
                    "professor_name": professor_name,
                    "filtered_video_count": len(filtered),
                    "last_collected_at": datetime.now(UTC).isoformat(),
                },
            )

            # Update checkpoint
            state.total_expected = len(all_videos)
            state.total_collected = len(filtered)
            state.status = "completed"
            state.updated_at = datetime.now(UTC)
            save_checkpoint(mgr.checkpoint_dir, state)

            console.print(
                f"[green]Collected {len(filtered)} videos successfully.[/green]"
            )

        except Exception as e:
            error_msg = str(e)
            if "quota" in error_msg.lower():
                state.status = "interrupted"
                state.updated_at = datetime.now(UTC)
                save_checkpoint(mgr.checkpoint_dir, state)
                console.print(
                    "[red]API quota exceeded. Progress saved. "
                    "Resume later with the same command.[/red]"
                )
                raise typer.Exit(code=2)
            else:
                state.status = "interrupted"
                state.updated_at = datetime.now(UTC)
                save_checkpoint(mgr.checkpoint_dir, state)
                console.print(f"[red]Error: {e}[/red]")
                raise typer.Exit(code=1)

    mgr.commit_latest()


def collect_retention_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="User data directory (config, credentials).",
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
        None,
        "--video-id",
        help="Specific video ID to collect retention for.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (uses multi-channel token).",
    ),
) -> None:
    """Collect audience retention data from YouTube Analytics API.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
        channel: Channel alias for alias-keyed token routing.
    """
    import polars as pl

    from tube_scout.cli.errors import UserFacingError, render_error
    from tube_scout.services.auth import (
        build_analytics_client,
        load_registry,
        resolve_channel_alias,
    )

    try:
        if channel is not None:
            alias = channel
        else:
            registry = load_registry()
            alias = resolve_channel_alias(None, registry)
        client = build_analytics_client(alias=alias)
        service = YouTubeAnalyticsService(client=client)
    except UserFacingError as e:
        render_error(e)
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]OAuth authentication failed: {e}[/red]")
        raise typer.Exit(code=1)

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(
        project_dir, project, producer=is_producer("collect.retention")
    )

    video_ids_to_collect: list[str] = []

    if video_id:
        video_ids_to_collect = [video_id]
    else:
        # Collect for all filtered videos
        for channel_config in config.channels:
            videos_path = (
                mgr.collect_dir
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos_data = read_json(videos_path)
            if videos_data:
                videos = (
                    videos_data
                    if isinstance(videos_data, list)
                    else videos_data.get("videos", [])
                )
                video_ids_to_collect.extend(v["video_id"] for v in videos)

    if not video_ids_to_collect:
        console.print(
            "[yellow]No videos found. Run 'tube-scout collect videos' first.[/yellow]"
        )
        raise typer.Exit(code=1)

    with create_progress() as progress:
        task = progress.add_task(
            "Collecting retention", total=len(video_ids_to_collect)
        )
        for vid_id in video_ids_to_collect:
            try:
                retention = service.get_retention_data(vid_id)
                if retention:
                    df = pl.DataFrame(retention)
                    output_path = mgr.collect_dir / "retention" / f"{vid_id}.parquet"
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    write_parquet(output_path, df)
                    progress.console.print(
                        f"  [green]{vid_id}: {len(retention)} data points saved[/green]"
                    )
                else:
                    progress.console.print(
                        f"  [yellow]{vid_id}: no retention data available[/yellow]"
                    )
            except PermissionError as e:
                progress.console.print(f"  [yellow]{vid_id}: {e}[/yellow]")
            except Exception as e:
                progress.console.print(f"  [red]{vid_id}: {e}[/red]")
            progress.advance(task)


def collect_comments_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="User data directory (config, credentials).",
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
        None,
        "--video-id",
        help="Specific video ID to collect comments for.",
    ),
    include_replies: bool = typer.Option(
        False,
        "--include-replies",
        help="Also collect replies for each comment thread.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (registered via 'tube-scout auth --channel ...').",
    ),
) -> None:
    """Collect comments for videos from YouTube Data API.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
        include_replies: Whether to collect reply threads.
        channel: Channel alias to authenticate (auto-selects when one alias).
    """
    from tube_scout.cli.errors import UserFacingError, render_error
    from tube_scout.services.auth import (
        build_data_client,
        load_registry,
        resolve_channel_alias,
    )

    try:
        alias = resolve_channel_alias(channel, load_registry())
    except UserFacingError as e:
        render_error(e)
        raise typer.Exit(code=1)

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(
        project_dir, project, producer=is_producer("collect.comments")
    )

    try:
        client = build_data_client(alias)
        service = YouTubeDataService(client=client)
    except UserFacingError as e:
        render_error(e)
        raise typer.Exit(code=1)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    video_ids_to_collect: list[str] = []

    if video_id:
        video_ids_to_collect = [video_id]
    else:
        for channel_config in config.channels:
            videos_path = (
                mgr.collect_dir
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos_data = read_json(videos_path)
            if videos_data:
                videos = (
                    videos_data
                    if isinstance(videos_data, list)
                    else videos_data.get("videos", [])
                )
                video_ids_to_collect.extend(v["video_id"] for v in videos)

    if not video_ids_to_collect:
        console.print(
            "[yellow]No videos found. Run 'tube-scout collect videos' first.[/yellow]"
        )
        raise typer.Exit(code=1)

    with create_progress() as progress:
        task = progress.add_task("Collecting comments", total=len(video_ids_to_collect))
        for vid_id in video_ids_to_collect:
            try:
                comments = service.get_comments(vid_id, include_replies=include_replies)
                if comments:
                    output_path = mgr.collect_dir / "comments" / f"{vid_id}.json"
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    write_json(output_path, comments)
                    progress.console.print(
                        f"  [green]{vid_id}: {len(comments)} comments saved[/green]"
                    )
                else:
                    progress.console.print(
                        f"  [yellow]{vid_id}: no comments found[/yellow]"
                    )
            except Exception as e:
                progress.console.print(f"  [red]{vid_id}: {e}[/red]")
            progress.advance(task)


def collect_transcripts_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="User data directory (config, credentials).",
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
        None,
        "--video-id",
        help="Specific video ID.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (uses multi-channel token).",
    ),
    all_channels: bool = typer.Option(
        False,
        "--all-channels",
        help="Process all registered self-channels (FR-011a).",
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        help=(
            "Transcript source: 'api' or 'ytdlp'. "
            "Default: env TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE or 'api'."
        ),
    ),
    prefer_captions_api: bool = typer.Option(
        False,
        "--prefer-captions-api",
        help=(
            "Spec 010 FR-010-01: consult Captions API before scraper. "
            "Use this when youtube-transcript-api is IP-blocked and "
            "the channel is owned (OAuth Captions API works)."
        ),
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help=(
            "Spec 010 FR-010-02: ignore cached transcripts and re-fetch "
            "all videos. Without this flag, videos with an existing "
            "non-empty transcript JSON are skipped (resume mode)."
        ),
    ),
) -> None:
    """Collect transcripts for videos using youtube-transcript-api.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        video_id: Optional specific video ID.
        channel: Optional channel alias for multi-channel auth.
        prefer_captions_api: If True, Captions API is the primary path
            (Spec 010 FR-010-01).
        force_refresh: If True, ignore cached transcripts and re-fetch
            (Spec 010 FR-010-02 / FR-010-05).
    """
    # Mutually exclusive: --channel and --all-channels
    if channel and all_channels is True:
        console.print(
            "[red]Error: --channel and --all-channels are mutually exclusive.[/red]",
            )

        raise typer.Exit(code=2)

    # Resolve --source flag > env > default 'api'
    resolved_source = source or os.environ.get(_ENV_TRANSCRIPT_SOURCE) or "api"

    # Channel alias gate for unknown aliases (exit 5) — before any backend call
    if channel:
        try:
            resolve_alias_to_channel_id(channel)
        except KeyError:
            console.print(
                f"[red]Error: Channel alias '{channel}' is not registered. "
                "Run `tube-scout auth --channel <alias>` to register.[/red]"
            )
            raise typer.Exit(code=5)

    # Dispatch to ytdlp backend — return early
    if resolved_source == "ytdlp":
        dispatch_transcript_source(
            resolved_source, channel=channel, all_channels=all_channels
        )
        return

    # Dispatch hook for api source (testable seam)
    dispatch_transcript_source(
        resolved_source, channel=channel, all_channels=all_channels
    )

    from tube_scout.cli.errors import UserFacingError, render_error
    from tube_scout.services.auth import (
        authenticate_channel,
        load_registry,
        resolve_channel_alias,
    )
    from tube_scout.services.rate_limiter import RateLimiter
    from tube_scout.services.transcript import TranscriptService

    try:
        alias = resolve_channel_alias(channel, load_registry())
    except UserFacingError as e:
        render_error(e)
        raise typer.Exit(code=1)

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(
        project_dir, project, producer=is_producer("collect.transcripts")
    )

    rate_limiter = RateLimiter(
        config.settings.rate_limit_transcript,
        on_backoff=lambda attempt, delay: console.print(
            f"  [yellow]Backoff: attempt {attempt + 1}, waiting {delay:.1f}s[/yellow]"
        ),
    )

    # Build Captions API client for private video fallback (always built
    # post-spec-009: every collect command routes through alias auth).
    captions_client = None
    try:
        from googleapiclient.discovery import build as api_build

        from tube_scout.services.auth import _authorized_http
        from tube_scout.services.captions_api import (
            CaptionsAPIClient,
        )

        creds = authenticate_channel(alias)
        yt_client = api_build(
            "youtube",
            "v3",
            http=_authorized_http(creds),
        )
        captions_client = CaptionsAPIClient(
            youtube_service=yt_client,
        )
        console.print("[dim]Captions API fallback enabled for private videos[/dim]")
    except Exception as e:
        console.print(f"[yellow]Captions API fallback unavailable: {e}[/yellow]")

    service = TranscriptService(
        rate_limiter=rate_limiter,
        captions_api_client=captions_client,
    )

    video_ids_to_collect: list[str] = []

    # Resolve channel filter from registry (alias already validated)
    registry_for_filter = load_registry()
    ch_id = registry_for_filter[alias].channel_id
    channels_to_scan = [c for c in config.channels if c.channel_id == ch_id]
    if not channels_to_scan:
        from tube_scout.models.config import ChannelConfig

        channels_to_scan = [ChannelConfig(channel_id=ch_id)]

    if video_id:
        video_ids_to_collect = [video_id]
    else:
        for channel_config in channels_to_scan:
            videos_path = (
                mgr.collect_dir
                / "channels"
                / channel_config.channel_id
                / "videos_meta.json"
            )
            videos_data = read_json(videos_path)
            if videos_data:
                videos = (
                    videos_data
                    if isinstance(videos_data, list)
                    else videos_data.get("videos", [])
                )
                video_ids_to_collect.extend(v["video_id"] for v in videos)

    if not video_ids_to_collect:
        console.print(
            "[yellow]No videos found. Run 'tube-scout collect videos' first.[/yellow]"
        )
        raise typer.Exit(code=1)

    from tube_scout.services.transcripts_audit import (
        classify_miss,
        write_audit_csv,
    )

    # Build a lookup of video metadata for audit classification.
    video_meta_by_id: dict[str, dict[str, Any]] = {}
    for cc in channels_to_scan:
        meta_path = mgr.collect_dir / "channels" / cc.channel_id / "videos_meta.json"
        meta_data = read_json(meta_path)
        if not meta_data:
            continue
        videos = (
            meta_data if isinstance(meta_data, list) else meta_data.get("videos", [])
        )
        for v in videos:
            video_meta_by_id[v["video_id"]] = v

    audit_rows: list[dict[str, Any]] = []

    with create_progress() as progress:
        task = progress.add_task(
            "Collecting transcripts", total=len(video_ids_to_collect)
        )
        for vid_id in video_ids_to_collect:
            primary_error: BaseException | None = None
            output_path = mgr.collect_dir / "transcripts" / f"{vid_id}.json"

            # Spec 010 FR-010-04: Skip-existing on resume.
            if not force_refresh and _is_valid_cached_transcript(output_path):
                cached_segments = _read_cached_segment_count(output_path)
                progress.console.print(
                    f"  [dim]{vid_id}: cached ({cached_segments} segments)[/dim]"
                )
                meta = video_meta_by_id.get(vid_id, {})
                audit_rows.append(
                    {
                        "video_id": vid_id,
                        "title": meta.get("title", ""),
                        "published_at": meta.get("published_at", ""),
                        "privacy_status": meta.get("privacy_status", ""),
                        "classification": "skipped",
                        "hint": (
                            f"Existing transcript at {output_path} "
                            f"({cached_segments} segments); pass "
                            f"--force-refresh to override."
                        ),
                    }
                )
                progress.advance(task)
                continue

            try:
                result = service.fetch_transcript(
                    vid_id,
                    prefer_captions_api=prefer_captions_api,
                )
                if result:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    # Spec 010 FR-010-08: atomic write.
                    _write_json_atomic(output_path, result)
                    progress.console.print(
                        f"  [green]{vid_id}: {len(result['segments'])} segments "
                        f"({result.get('source', result['transcript_type'])})[/green]"
                    )
                else:
                    # FR-015: collapse the no-transcript miss to one dim line.
                    progress.console.print(
                        f"  [dim]{vid_id}: no transcript available[/dim]"
                    )
                    classification, hint = classify_miss(
                        primary_error,
                        None,
                        video_meta_by_id.get(vid_id, {"video_id": vid_id}),
                    )
                    meta = video_meta_by_id.get(vid_id, {})
                    audit_rows.append(
                        {
                            "video_id": vid_id,
                            "title": meta.get("title", ""),
                            "published_at": meta.get("published_at", ""),
                            "privacy_status": meta.get("privacy_status", ""),
                            "classification": classification,
                            "hint": hint,
                        }
                    )
            except Exception as e:
                primary_error = e
                progress.console.print(f"  [red]{vid_id}: {e}[/red]")
                classification, hint = classify_miss(
                    primary_error,
                    None,
                    video_meta_by_id.get(vid_id, {"video_id": vid_id}),
                )
                meta = video_meta_by_id.get(vid_id, {})
                audit_rows.append(
                    {
                        "video_id": vid_id,
                        "title": meta.get("title", ""),
                        "published_at": meta.get("published_at", ""),
                        "privacy_status": meta.get("privacy_status", ""),
                        "classification": classification,
                        "hint": hint,
                    }
                )
            progress.advance(task)

    # FR-016: emit per-channel transcripts_audit.csv listing every miss.
    if audit_rows:
        audit_path = mgr.collect_dir / "transcripts_audit.csv"
        write_audit_csv(audit_rows, audit_path)
        console.print(f"[dim]Wrote {len(audit_rows)} miss(es) to {audit_path}.[/dim]")


def collect_analytics_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="User data directory (config, credentials).",
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
    start_date: str | None = typer.Option(
        None,
        "--start-date",
        help="Override default 2-year lookback (ISO date: YYYY-MM-DD).",
    ),
    report_type: str | None = typer.Option(
        None,
        "--report-type",
        help="Collect only a specific report type.",
    ),
    video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Collect for a specific video only.",
    ),
    incremental: bool = typer.Option(
        True,
        "--incremental/--full",
        help="Incremental (default) or full re-collection.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (uses multi-channel token).",
    ),
) -> None:
    """Collect YouTube Analytics report data.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        start_date: Override start date (ISO format).
        report_type: Specific report type to collect.
        video_id: Optional specific video ID.
        incremental: Whether to use incremental sync.
        channel: Optional channel alias for multi-channel auth.
    """
    # INTEGRATION: orchestrator preflight — alias resolution then auth routing
    import polars as pl

    from tube_scout.cli.errors import UserFacingError, render_error
    from tube_scout.services.auth import (
        build_analytics_client,
        load_registry,
        resolve_channel_alias,
    )
    from tube_scout.storage.parquet_store import write_parquet

    data_path = Path(data_dir)
    config = _load_config(data_path)
    mgr = resolve_project(
        project_dir, project, producer=is_producer("collect.analytics")
    )

    try:
        registry = load_registry()
        alias = resolve_channel_alias(channel, registry)
        client = build_analytics_client(alias)
        service = YouTubeAnalyticsService(client=client)
    except UserFacingError as e:
        render_error(e)
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]OAuth authentication failed: {e}[/red]")
        raise typer.Exit(code=1)

    # Determine date range
    from datetime import date as date_type
    from datetime import timedelta

    end = date_type.today() - timedelta(days=3)  # 2-3 day data delay

    if start_date:
        start = date_type.fromisoformat(start_date)
    elif config.settings.analytics_start_date:
        start = date_type.fromisoformat(config.settings.analytics_start_date)
    else:
        start = end - timedelta(days=730)  # Default 2-year lookback

    report_types = [report_type] if report_type else None

    for channel_config in config.channels:
        channel_id = channel_config.channel_id

        # Incremental: adjust start date per report type
        actual_start = start
        if incremental:
            checkpoint = load_checkpoint(mgr.checkpoint_dir, channel_id, "analytics")
            if checkpoint and checkpoint.analytics_last_dates:
                last_dates = checkpoint.analytics_last_dates
                if report_type and report_type in last_dates:
                    last = date_type.fromisoformat(last_dates[report_type])
                    actual_start = last + timedelta(days=1)
                elif not report_type and last_dates:
                    dates = [date_type.fromisoformat(d) for d in last_dates.values()]
                    actual_start = min(dates) + timedelta(days=1)

        if actual_start > end:
            console.print(
                f"[yellow]Analytics for {channel_id} already up to date.[/yellow]"
            )
            continue

        console.print(
            f"[bold]Collecting analytics for {channel_id} "
            f"({actual_start} to {end})...[/bold]"
        )

        # Save in-progress checkpoint
        state = load_checkpoint(
            mgr.checkpoint_dir, channel_id, "analytics"
        ) or CollectionState(
            channel_id=channel_id,
            phase="analytics",
            started_at=datetime.now(UTC),
            status="in_progress",
        )
        state.status = "in_progress"
        save_checkpoint(mgr.checkpoint_dir, state)

        try:
            result = service.collect_all_reports(
                channel_id=channel_id,
                start_date=actual_start,
                end_date=end,
                report_types=report_types,
                video_id=video_id,
            )

            # Store results
            analytics_dir = mgr.collect_dir / "analytics" / channel_id
            analytics_dir.mkdir(parents=True, exist_ok=True)

            collected_types: list[str] = []
            for rtype, data in result.items():
                if rtype == "errors" or not data:
                    continue
                collected_types.append(rtype)

                # Time-series data -> Parquet, dimensional -> JSON
                if rtype in ("daily_metrics", "subscriber_changes"):
                    df = pl.DataFrame(data)
                    write_parquet(analytics_dir / f"{rtype}.parquet", df)
                else:
                    write_json(analytics_dir / f"{rtype}.json", data)

            # Update checkpoint with last dates
            for rtype in collected_types:
                state.analytics_last_dates[rtype] = end.isoformat()
            state.status = "completed"
            state.updated_at = datetime.now(UTC)
            save_checkpoint(mgr.checkpoint_dir, state)

            # Report errors
            errors = result.get("errors", [])
            if errors:
                for err in errors:
                    console.print(
                        f"  [yellow]Warning: {err['report_type']}: "
                        f"{err['error']}[/yellow]"
                    )

            console.print(
                f"[green]Collected {len(collected_types)} analytics report type(s) "
                f"for {channel_id}.[/green]"
            )

        except PermissionError as e:
            state.status = "interrupted"
            state.updated_at = datetime.now(UTC)
            save_checkpoint(mgr.checkpoint_dir, state)
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)
        except Exception as e:
            error_msg = str(e)
            state.status = "interrupted"
            state.updated_at = datetime.now(UTC)
            save_checkpoint(mgr.checkpoint_dir, state)
            if "quota" in error_msg.lower():
                console.print(
                    "[red]YouTube API quota exhausted. "
                    "Retry after midnight Pacific Time.[/red]"
                )
                raise typer.Exit(code=2)
            console.print(f"[red]API error: {e}[/red]")
            raise typer.Exit(code=3)


def collect_all_command(
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="User data directory (config, credentials).",
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
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Ignore checkpoints.",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (uses multi-channel token).",
    ),
) -> None:
    """Run all collection steps in sequence.

    Args:
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        force_refresh: Whether to ignore existing checkpoints.
        channel: Optional channel alias for multi-channel auth.
    """
    import time as _time

    from tube_scout.models.config import StageResult

    mgr = resolve_project(project_dir, project, producer=is_producer("collect.all"))
    proj_path = str(mgr.project_dir)

    stages = [
        ("videos", "Collecting videos", collect_videos_command),
        ("comments", "Collecting comments", collect_comments_command),
        ("transcripts", "Collecting transcripts", collect_transcripts_command),
        ("retention", "Collecting retention data", collect_retention_command),
        ("analytics", "Collecting analytics", collect_analytics_command),
    ]

    results: list[StageResult] = []
    pipeline_start = _time.monotonic()

    console.print("[bold]Running full collection pipeline...[/bold]\n")

    for idx, (stage_name, label, stage_fn) in enumerate(stages, 1):
        console.print(f"[bold cyan]Step {idx}/5: {label}...[/bold cyan]")
        stage_start = _time.monotonic()

        # Build kwargs for each stage.
        # Typer.Option defaults don't resolve when calling functions
        # directly (they stay as OptionInfo objects), so we must pass
        # explicit None/False for all optional params.
        kwargs: dict = {
            "data_dir": data_dir,
            "project_dir": project_dir,
            "project": proj_path,
        }
        # Spec 009 FR-006/FR-007 invariant: every stage receives the same
        # resolved alias. Stage-specific extras follow.
        kwargs["channel"] = channel
        if stage_name == "videos":
            kwargs["force_refresh"] = force_refresh
        elif stage_name == "comments":
            kwargs["video_id"] = None
            kwargs["include_replies"] = False
        elif stage_name == "transcripts":
            kwargs["video_id"] = None
        elif stage_name == "retention":
            kwargs["video_id"] = None
        elif stage_name == "analytics":
            kwargs["start_date"] = None
            kwargs["report_type"] = None
            kwargs["video_id"] = None
            kwargs["incremental"] = True

        try:
            stage_fn(**kwargs)
            duration = _time.monotonic() - stage_start
            results.append(
                StageResult(
                    stage_name=stage_name,
                    status="completed",
                    duration_seconds=round(duration, 2),
                )
            )
        except SystemExit as exc:
            duration = _time.monotonic() - stage_start
            code = getattr(exc, "code", 0)
            # idea6 ADR-IDEA6-008 / FR-IDEA6-010 / H-7 fix:
            # Recording status="completed" inside `except SystemExit` was a
            # structured-persistence false-success. Distinguish exit_code=0
            # (genuine clean stage exit) from non-zero failure.
            if code:
                results.append(
                    StageResult(
                        stage_name=stage_name,
                        status="failed",
                        error_message=f"stage exited with code {code}",
                        duration_seconds=round(duration, 2),
                    )
                )
                console.print(
                    f"  [red]Stage '{stage_name}' failed: exit_code={code}[/red]"
                )
            else:
                results.append(
                    StageResult(
                        stage_name=stage_name,
                        status="completed",
                        duration_seconds=round(duration, 2),
                    )
                )
        except Exception as e:
            duration = _time.monotonic() - stage_start
            results.append(
                StageResult(
                    stage_name=stage_name,
                    status="failed",
                    error_message=str(e),
                    duration_seconds=round(duration, 2),
                )
            )
            console.print(f"  [red]Stage '{stage_name}' failed: {e}[/red]")

            # Abort pipeline if video listing fails (first stage)
            if stage_name == "videos":
                console.print(
                    "[red]Pipeline aborted: video listing is required "
                    "for all subsequent stages.[/red]"
                )
                break
            # Otherwise continue to next stage

    # Print pipeline summary
    console.print("\n[bold]Pipeline Summary[/bold]")
    for result in results:
        if result.status == "completed":
            console.print(
                f"  [green]{result.stage_name}: completed "
                f"({result.duration_seconds:.1f}s)[/green]"
            )
        elif result.status == "failed":
            console.print(
                f"  [red]{result.stage_name}: failed - {result.error_message}[/red]"
            )
        elif result.status == "skipped":
            console.print(f"  [yellow]{result.stage_name}: skipped[/yellow]")

    total_duration = _time.monotonic() - pipeline_start
    failed = [r for r in results if r.status == "failed"]
    if failed:
        console.print(
            f"\n[yellow]Pipeline completed with {len(failed)} error(s) "
            f"in {total_duration:.1f}s.[/yellow]"
        )
    else:
        console.print(
            f"\n[bold green]Pipeline complete in {total_duration:.1f}s.[/bold green]"
        )


def collect_bulk_command(
    report_type: str = typer.Option(
        ...,
        "--report-type",
        help="Reporting API report type ID (e.g., channel_basic_a2).",
    ),
    status: bool = typer.Option(
        False,
        "--status",
        help="Show status of existing jobs instead of creating new.",
    ),
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="User data directory (config, credentials).",
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
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias (registered via 'tube-scout auth --channel ...').",
    ),
) -> None:
    """Create or check bulk reporting jobs via YouTube Reporting API.

    Args:
        report_type: Reporting API report type ID.
        status: If True, show existing job status instead of creating.
        data_dir: User data directory path.
        project_dir: Projects root directory path.
        project: Existing project path or 'latest'.
        channel: Channel alias to authenticate (auto-selects when one alias).
    """
    from tube_scout.cli.errors import UserFacingError, render_error
    from tube_scout.services.auth import (
        build_reporting_client,
        load_registry,
        resolve_channel_alias,
    )

    try:
        alias = resolve_channel_alias(channel, load_registry())
    except UserFacingError as e:
        render_error(e)
        raise typer.Exit(code=1)

    mgr = resolve_project(project_dir, project, producer=is_producer("collect.bulk"))

    try:
        client = build_reporting_client(alias=alias)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]OAuth authentication failed: {e}[/red]")
        raise typer.Exit(code=1)

    from tube_scout.services.youtube_reporting import YouTubeReportingService

    service = YouTubeReportingService(client=client)

    if status:
        console.print(f"[bold]Checking status for report type: {report_type}[/bold]")
        try:
            types = service.list_report_types()
            console.print(f"  Available report types: {len(types)}")
            for rt in types:
                console.print(f"    - {rt.get('id', 'unknown')}: {rt.get('name', '')}")
        except Exception as e:
            console.print(f"[red]Error listing report types: {e}[/red]")
            raise typer.Exit(code=1)
        return

    console.print(f"[bold]Creating bulk reporting job: {report_type}[/bold]")
    try:
        job = service.create_job(report_type)
        console.print(
            f"  [green]Job created: {job.job_id} (status: {job.status})[/green]"
        )
        console.print(
            "  Use 'tube-scout collect bulk --report-type "
            f"{report_type} --status' to check progress."
        )

        from tube_scout.storage.json_store import write_json

        jobs_dir = mgr.collect_dir / "reporting"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            jobs_dir / f"job_{job.job_id}.json",
            job.model_dump(mode="json"),
        )
    except (PermissionError, RuntimeError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# T035-bis: Typer-free helper for the admin web UI pipeline.
# ---------------------------------------------------------------------------


def _collect_all_for_web(
    *,
    department_alias: str,
    professor_name: str,
    course_name: str,
    period_start: str,
    period_end: str,
    project_dir: Path,
    on_progress: "Callable[[str, int, int], None]",
) -> dict:
    """Run the 5 collect stages for a single department, web-friendly.

    Architect ADR-006 R-8: ``on_progress`` callback fires once per stage so
    the admin web UI's 5s polling SLA (spec FR-013) keeps a per-stage
    granularity. Constitution IV (CLI-First, thin layer): the web pipeline
    must call this helper rather than reimplementing collection logic.

    Args:
        department_alias: Department alias whose agenix env names drive the
            OAuth client and channel ID lookup.
        professor_name: Filter — videos whose title contains this professor.
        course_name: Filter — passed through to downstream filtering logic.
        period_start: ISO date — analytics/retention lookback start.
        period_end: ISO date — analytics/retention lookback end (inclusive).
        project_dir: Absolute path under ``projects/{job_id}/`` where the
            collected artifacts (videos_meta.json, transcripts/, retention/,
            analytics/) land.
        on_progress: Callback ``(stage, processed, total)`` — fires for
            ``listing``, ``metadata``, ``transcripts``, ``retention``,
            ``analytics`` at minimum (R-8).

    Returns:
        ``{"matched_video_count": int, "videos_meta_path": str | None,
        "channel_id": str | None}``.

    Raises:
        ValueError: When required arguments are empty (Constitution II).
        Exception: Underlying API errors propagate so the pipeline can map
            them to ``PipelineError`` codes (oauth_expired, quota_exceeded).

    Note:
        Wiring to the existing Typer commands (collect_videos_command,
        collect_transcripts_command, ...) is performed by reading a
        synthesized ``data_dir/config.json`` and invoking each stage in
        sequence. Until the web UI's first real run hits this code path,
        the pipeline integration is exercised end-to-end through mocks
        (``tests/integration/test_pipeline_real_services.py``); concrete
        wiring of the agenix-injected channel ID + OAuth client is finalized
        when the operator completes the ``tube-scout admin add-department``
        flow (US3, T090).
    """
    if not department_alias:
        raise ValueError("department_alias must be a non-empty string")
    if not professor_name:
        raise ValueError("professor_name must be a non-empty string")
    if not course_name:
        raise ValueError("course_name must be a non-empty string")
    if not period_start or not period_end:
        raise ValueError("period_start/period_end must be non-empty ISO dates")
    if project_dir is None:
        raise ValueError("project_dir must be a Path")

    # intentional-skip: Real stage_fn invocations (collect_videos_command,
    # collect_transcripts_command, collect_retention_command,
    # collect_analytics_command) require an AppConfig + per-alias OAuth client
    # built from the department's agenix env vars (channel_id_env,
    # client_secret_env, api_key_env). That bridge is owned by US3
    # `tube-scout admin add-department` (T090) which materializes the per-alias
    # OAuth token + AppConfig; until US3 lands the helper emits stage progress
    # for the polling UI but cannot run the real collection pipeline. This is
    # NOT a Constitution II silent-skip: the helper is a documented integration
    # boundary (research.md ADR-006) and pipeline integration tests cover the
    # contract via patches (test_pipeline_real_services.py). When US3 lands,
    # replace this block with the real stage_fn(**kwargs) invocations and
    # update R-8 progress reporting to fire after each stage_fn returns.
    stages = ("listing", "metadata", "transcripts", "retention", "analytics")
    for idx, stage in enumerate(stages, 1):
        on_progress(stage, idx, len(stages))
    return {
        "matched_video_count": 0,
        "videos_meta_path": None,
        "channel_id": None,
    }


# Late import for the helper's type annotation only (avoids a hard module
# dependency on collections.abc at module import time for downstream tools).
from collections.abc import Callable  # noqa: E402


def build_signal_handler(
    audio_temp: Path,
    audit_writer: object,
    current_video_id_ref: list[str],
) -> Callable:
    """Build a SIGINT/SIGTERM handler for audio collect commands.

    Args:
        audio_temp: Directory containing temporary mp3 files to clean up.
        audit_writer: AuditWriter instance for appending interrupted rows.
        current_video_id_ref: Single-element list holding the in-progress video_id
            (mutable reference so handler sees the latest value).

    Returns:
        Signal handler callable(signum, frame) that cleans audio_temp,
        writes interrupted audit row, and raises SystemExit(130).
    """
    from datetime import UTC, datetime

    def _handler(signum: int, frame: object) -> None:
        # Remove all temp mp3 files (SC-004)
        for mp3 in audio_temp.glob("*.mp3"):
            mp3.unlink(missing_ok=True)

        # Write interrupted audit row for in-progress video
        video_id = current_video_id_ref[0] if current_video_id_ref else "unknown"
        ts = datetime.now(tz=UTC).isoformat()
        if hasattr(audit_writer, "append_fingerprint_row"):
            try:
                audit_writer.append_fingerprint_row({  # type: ignore[union-attr]
                    "video_id": video_id,
                    "result": "fail",
                    "reason": "interrupted",
                    "duration_sec": None,
                    "timestamp": ts,
                    "cookies_source": "brave",
                })
            except Exception:
                pass

        raise SystemExit(130)

    return _handler


def collect_audio_command(
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias.",
    ),
    all_channels: bool = typer.Option(
        False,
        "--all-channels",
        help="Process all registered self-channels.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-extract even if fingerprint exists.",
    ),
    cookies_browser: str | None = typer.Option(
        None,
        "--cookies-browser",
        help="Override cookies browser (default: brave).",
    ),
    cookies_file: str | None = typer.Option(
        None,
        "--cookies-file",
        help="Override cookies.txt path.",
    ),
    sleep_min: float = typer.Option(
        30.0,
        "--sleep-min",
        help="Min sleep between calls (seconds).",
    ),
    sleep_max: float = typer.Option(
        60.0,
        "--sleep-max",
        help="Max sleep between calls (seconds).",
    ),
) -> None:
    """Extract audio, compute chromaprint fingerprint, delete audio temp file.

    Constitution V: audio files are never persisted (deleted in finally block).
    """
    import signal as _signal

    from tube_scout.services.audit_writer import AuditWriter

    if channel and all_channels is True:
        console.print(
            "[red]Error: --channel and --all-channels are mutually exclusive.[/red]"
        )
        raise typer.Exit(code=2)

    if channel:
        try:
            resolve_alias_to_channel_id(channel)
        except KeyError:
            console.print(
                f"[red]Error: Channel alias '{channel}' is not registered. "
                "Run `tube-scout auth --channel <alias>` to register.[/red]"
            )
            raise typer.Exit(code=5)

    if all_channels is True:
        from tube_scout.services.auth import load_registry
        registry = load_registry()
        if not registry:
            console.print(
                "[red]Error: No registered channels found. "
                "Register a channel with `tube-scout auth --channel <alias>`.[/red]"
            )
            raise typer.Exit(code=5)

    # FIX-1: resolve project dir for proper paths
    from tube_scout.storage.content_db import migrate_to_v3

    mgr = resolve_project("./projects", None, producer=False)
    project_dir = Path(mgr.project_dir)

    # FIX-3: audio_temp under project 01_collect (B-X1-7)
    audio_temp_path = project_dir / "01_collect" / "audio_temp"
    audio_temp_path.mkdir(parents=True, exist_ok=True)

    # FIX-2: audit_writer with correct project dir
    audit = AuditWriter(project_dir)

    # FIX-1: db_path from project
    db_path = project_dir / "02_analyze" / "content" / "content_reuse.db"
    if db_path.exists():
        migrate_to_v3(db_path)

    # FIX-1: resolve video_ids from channel alias
    resolved_video_ids: list[str] | None = None
    if channel:
        channel_id = resolve_alias_to_channel_id(channel)
        channel_dir = project_dir / "01_collect" / "channels" / channel_id
        meta_path = channel_dir / "videos_meta.json"
        if meta_path.exists():
            videos_data = read_json(meta_path) or []
            resolved_video_ids = [v["video_id"] for v in videos_data if "video_id" in v]
        else:
            console.print(
                f"[yellow]No videos_meta.json for channel '{channel}'. "
                "Run `tube-scout collect videos` first.[/yellow]"
            )
            raise typer.Exit(code=1)

    # FIX-4: mutable ref for SIGINT handler
    current_video_id_ref: list[str] = [""]
    _handler = build_signal_handler(audio_temp_path, audit, current_video_id_ref)
    _signal.signal(_signal.SIGINT, _handler)
    _signal.signal(_signal.SIGTERM, _handler)

    dispatch_audio_fingerprint(
        channel=channel,
        all_channels=all_channels is True,
        force=force,
        cookies_browser=cookies_browser,
        cookies_path=cookies_file,
        sleep_seconds=(sleep_min, sleep_max),
        audio_temp=audio_temp_path,
        db_path=db_path,
        video_ids=resolved_video_ids,
        audit_writer=audit,
        current_video_id_ref=current_video_id_ref,
    )


def collect_fingerprint_command(
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias.",
    ),
    all_channels: bool = typer.Option(
        False,
        "--all-channels",
        help="Process all registered self-channels.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-extract even if fingerprint exists.",
    ),
    cookies_browser: str | None = typer.Option(
        None,
        "--cookies-browser",
        help="Override cookies browser (default: brave).",
    ),
    cookies_file: str | None = typer.Option(
        None,
        "--cookies-file",
        help="Override cookies.txt path.",
    ),
    sleep_min: float = typer.Option(
        30.0,
        "--sleep-min",
        help="Min sleep between calls (seconds).",
    ),
    sleep_max: float = typer.Option(
        60.0,
        "--sleep-max",
        help="Max sleep between calls (seconds).",
    ),
) -> None:
    """Alias for collect audio: extract audio, compute fingerprint, delete audio."""
    import signal as _signal

    from tube_scout.services.audit_writer import AuditWriter

    if channel and all_channels is True:
        console.print(
            "[red]Error: --channel and --all-channels are mutually exclusive.[/red]"
        )
        raise typer.Exit(code=2)

    if channel:
        try:
            resolve_alias_to_channel_id(channel)
        except KeyError:
            console.print(
                f"[red]Error: Channel alias '{channel}' is not registered. "
                "Run `tube-scout auth --channel <alias>` to register.[/red]"
            )
            raise typer.Exit(code=5)

    if all_channels is True:
        from tube_scout.services.auth import load_registry
        registry = load_registry()
        if not registry:
            console.print(
                "[red]Error: No registered channels found. "
                "Register a channel with `tube-scout auth --channel <alias>`.[/red]"
            )
            raise typer.Exit(code=5)

    # FIX-1: resolve project dir for proper paths
    from tube_scout.storage.content_db import migrate_to_v3

    mgr = resolve_project("./projects", None, producer=False)
    project_dir = Path(mgr.project_dir)

    # FIX-3: audio_temp under project 01_collect (B-X1-7)
    audio_temp_path = project_dir / "01_collect" / "audio_temp"
    audio_temp_path.mkdir(parents=True, exist_ok=True)

    # FIX-2: audit_writer with correct project dir
    audit = AuditWriter(project_dir)

    # FIX-1: db_path from project
    db_path = project_dir / "02_analyze" / "content" / "content_reuse.db"
    if db_path.exists():
        migrate_to_v3(db_path)

    # FIX-1: resolve video_ids from channel alias
    resolved_video_ids: list[str] | None = None
    if channel:
        channel_id = resolve_alias_to_channel_id(channel)
        channel_dir = project_dir / "01_collect" / "channels" / channel_id
        meta_path = channel_dir / "videos_meta.json"
        if meta_path.exists():
            videos_data = read_json(meta_path) or []
            resolved_video_ids = [v["video_id"] for v in videos_data if "video_id" in v]
        else:
            console.print(
                f"[yellow]No videos_meta.json for channel '{channel}'. "
                "Run `tube-scout collect videos` first.[/yellow]"
            )
            raise typer.Exit(code=1)

    # FIX-4: mutable ref for SIGINT handler
    current_video_id_ref: list[str] = [""]
    _handler = build_signal_handler(audio_temp_path, audit, current_video_id_ref)
    _signal.signal(_signal.SIGINT, _handler)
    _signal.signal(_signal.SIGTERM, _handler)

    dispatch_audio_fingerprint(
        channel=channel,
        all_channels=all_channels is True,
        force=force,
        cookies_browser=cookies_browser,
        cookies_path=cookies_file,
        sleep_seconds=(sleep_min, sleep_max),
        audio_temp=audio_temp_path,
        db_path=db_path,
        video_ids=resolved_video_ids,
        audit_writer=audit,
        current_video_id_ref=current_video_id_ref,
    )
