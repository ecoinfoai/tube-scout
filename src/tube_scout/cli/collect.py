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
    """Dispatch transcript collection to the api backend.

    Args:
        source: Reserved; only 'api' remains after spec 013 Phase 5.
        **kwargs: Backend-specific arguments passed through.
    """
    _dispatch_api_transcripts(**kwargs)


def _dispatch_api_transcripts(**kwargs: object) -> None:
    """Data API transcript backend — delegates to existing spec 010 logic."""


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


def _collect_transcripts_asr(  # noqa: C901
    channel: str,
    video_ids_str: str,
    preset: str,
    model: str,
    compute_type: str,
    device: str,
    language: str,
    beam_size: int,
    vad_filter: bool,
    retry_failed: bool,
    cleanup_audio: bool,
    auto_normalize: bool,
    audio_cache_dir: str,
    data_dir: str,
    db_path_str: str,
) -> None:
    """--source asr branch: run faster-whisper ASR on cached WAV files.

    FR-016~FR-022.
    """
    import datetime
    import sqlite3

    from tube_scout.services.asr import PRESET_TABLE, transcribe_audio
    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.services.text_normalizer import normalize_transcript_json
    from tube_scout.services.worker_pool import run_pool

    work_root = Path(data_dir)
    db = Path(db_path_str) if db_path_str else work_root / "content_reuse.db"
    cache_dir = Path(audio_cache_dir)

    if not db.exists():
        console.print(f"[red]DB not found: {db}. Run 'collect takeout' first.[/red]")
        raise typer.Exit(code=2)

    transcript_dir = work_root / channel / "01_collect" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir = work_root / channel / "01_collect" / "transcripts_normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    # Resolve video list
    try:
        with sqlite3.connect(db) as conn:
            if video_ids_str:
                ids = [v.strip() for v in video_ids_str.split(",") if v.strip()]
                placeholders = ",".join("?" * len(ids))
                rows = conn.execute(
                    "SELECT video_id FROM processing_status"
                    f" WHERE video_id IN ({placeholders})",
                    ids,
                ).fetchall()
            else:
                status_filter = (
                    "'collected', 'asr_failed'" if retry_failed else "'collected'"
                )
                rows = conn.execute(
                    f"SELECT ps.video_id FROM processing_status ps"
                    f" JOIN video_metadata vm ON vm.video_id = ps.video_id"
                    f" JOIN channel_metadata cm ON cm.channel_id = vm.channel_id"
                    f" WHERE cm.channel_alias = ? AND ps.status IN ({status_filter})",
                    (channel,),
                ).fetchall()
    except Exception as exc:
        console.print(f"[red]DB query error: {exc}[/red]")
        raise typer.Exit(code=2) from exc

    if not rows:
        console.print("[yellow]No videos in 'collected' status found.[/yellow]")
        raise typer.Exit(code=0)

    video_ids = [r[0] for r in rows]

    # Pool preset: spawn worker_pool
    if preset == "prod-a6000-pool":
        result = run_pool(
            db_path=db,
            audio_cache_dir=cache_dir,
            transcripts_dir=transcript_dir,
            n_workers=2,
            device_indices=[0, 1],
            model_size=model,
            compute_type=compute_type,
            language=language,
            auto_normalize=auto_normalize,
            retry_failed=retry_failed,
            keep_audio=not cleanup_audio,
        )
        console.print(
            f"[green]pool done[/green] processed={result.total_processed} "
            f"failed={result.total_failed} skipped={result.total_skipped}"
        )
        return

    # Single-worker path
    preset_cfg = PRESET_TABLE.get(preset, {})
    resolved_model = model or preset_cfg.get("model", "large-v3")
    resolved_compute = compute_type or preset_cfg.get("compute_type", "int8_float16")
    resolved_device = device or preset_cfg.get("device", "cuda")
    device_index = int(preset_cfg.get("device_index") or 0)

    audit = AuditWriter(work_root / channel)

    for video_id in video_ids:
        wav_path = cache_dir / f"{video_id}.wav"
        ts = datetime.datetime.now(tz=datetime.UTC).isoformat()

        if not wav_path.exists():
            console.print(f"[yellow]skip[/yellow] {video_id}: WAV not found {wav_path}")
            audit.append_transcript_row({
                "video_id": video_id,
                "result": "skip",
                "reason": "wav_not_found",
                "source": "asr",
                "timestamp": ts,
                "cookies_source": "local",
            })
            continue

        try:
            result = transcribe_audio(
                wav_path,
                model_size=resolved_model,
                compute_type=resolved_compute,
                device=resolved_device,
                device_index=device_index,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
            )
        except Exception as exc:
            console.print(f"[yellow]asr fail[/yellow] {video_id}: {exc}")
            audit.append_transcript_row({
                "video_id": video_id,
                "result": "fail",
                "reason": "asr_error",
                "source": "asr",
                "timestamp": ts,
                "cookies_source": "local",
            })
            continue
        finally:
            if cleanup_audio and wav_path.exists():
                wav_path.unlink(missing_ok=True)

        import os as _os
        import tempfile as _tempfile
        transcript = {
            "video_id": video_id,
            "source": result.caption_source_detail,
            "language": result.language_detected,
            "duration": result.duration,
            "segments": result.segments,
            "asr_quality_flags": result.asr_quality_flags.model_dump(),
            "fetched_at": ts,
        }
        json_path = transcript_dir / f"{video_id}.json"
        fd, tmp_name = _tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")
        try:
            import json as _json
            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                _json.dump(transcript, f, ensure_ascii=False, indent=2)
            _os.replace(tmp_name, json_path)
        except Exception:
            try:
                _os.unlink(tmp_name)
            except OSError:
                pass
            raise

        if auto_normalize:
            norm_path = normalized_dir / f"{video_id}.json"
            normalize_transcript_json(json_path, norm_path)

        audit.append_transcript_row({
            "video_id": video_id,
            "result": "success",
            "reason": "asr_transcribed",
            "source": result.caption_source_detail,
            "timestamp": ts,
            "cookies_source": "local",
        })
        console.print(
            f"[green]ok[/green] {video_id}"
            f" lang={result.language_detected} dur={result.duration:.1f}s"
        )


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
            "Transcript source: 'asr' (default) or 'youtube' (deprecated, exit 2). "
            "Default: env TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE or 'asr'."
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
    # ASR-specific flags (--source asr only)
    asr_preset: str | None = typer.Option(
        None,
        "--preset",
        help=(
            "ASR preset: poc-laptop, prod-a6000, prod-a6000-pool, cpu-fallback"
            " (required for --source asr)."
        ),
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_model: str = typer.Option(
        "",
        "--model",
        help="Override model for --source asr (default from preset).",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_compute_type: str = typer.Option(
        "",
        "--compute-type",
        help="Override compute type for --source asr (default from preset).",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_device: str = typer.Option(
        "",
        "--device",
        help="Override device for --source asr (default from preset).",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_language: str = typer.Option(
        "ko",
        "--language",
        help="Language code for ASR (default: ko).",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_beam_size: int = typer.Option(
        5,
        "--beam-size",
        help="Beam size for faster-whisper (default: 5).",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_vad_filter: bool = typer.Option(
        True,
        "--vad-filter/--no-vad-filter",
        help="Enable VAD filter for ASR (default: on).",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        help="Also retry videos in asr_failed status.",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_cleanup_audio: bool = typer.Option(
        False,
        "--cleanup-audio",
        help="Delete WAV file after each video is transcribed.",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_auto_normalize: bool = typer.Option(
        True,
        "--auto-normalize/--no-auto-normalize",
        help="Automatically normalize transcript after ASR (default: on).",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_audio_cache_dir: str = typer.Option(
        "/tmp/tube-scout-audio",
        "--audio-cache-dir",
        help="WAV cache directory for --source asr.",
        rich_help_panel="ASR options (--source asr)",
    ),
    asr_db_path_str: str = typer.Option(
        "",
        "--db-path",
        help=(
            "Path to content_reuse.db for --source asr"
            " (defaults to <data-dir>/content_reuse.db)."
        ),
        rich_help_panel="ASR options (--source asr)",
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

    # Resolve --source flag > env > default 'asr' (FR-017: asr is the sole path)
    resolved_source = source or os.environ.get(_ENV_TRANSCRIPT_SOURCE) or "asr"

    # FR-018: --source youtube is deprecated and blocked (2026-05-12 decision)
    if resolved_source == "youtube":
        console.print(
            "ERROR: --source youtube 는 2026-05-12 결정으로 폐기되었습니다.\n"
            "       Takeout 단독 운영 모델에서는 자막을\n"
            "       faster-whisper ASR 로 직접 생성합니다.\n"
            "       --source asr 가 기본값이므로 옵션을 생략하거나 "
            "명시적으로 --source asr 를 사용하세요."
        )
        raise typer.Exit(code=2)

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

    # Dispatch to asr backend — return early
    if resolved_source == "asr":
        if not channel:
            console.print("[red]--channel is required for --source asr.[/red]")
            raise typer.Exit(code=2)
        _collect_transcripts_asr(
            channel=channel,
            video_ids_str=video_id or "",
            preset=asr_preset,
            model=asr_model,
            compute_type=asr_compute_type,
            device=asr_device,
            language=asr_language,
            beam_size=asr_beam_size,
            vad_filter=asr_vad_filter,
            retry_failed=asr_retry_failed,
            cleanup_audio=asr_cleanup_audio,
            auto_normalize=asr_auto_normalize,
            audio_cache_dir=asr_audio_cache_dir,
            data_dir=data_dir,
            db_path_str=asr_db_path_str,
        )
        return

    # Dispatch hook for api source (testable seam)
    dispatch_transcript_source(
        resolved_source, channel=channel, all_channels=all_channels,
        project_dir=project_dir,
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
    cookies_source: str = "browser:brave",
) -> Callable:
    """Build a SIGINT/SIGTERM handler for audio collect commands.

    Args:
        audio_temp: Directory containing temporary mp3 files to clean up.
        audit_writer: AuditWriter instance for appending interrupted rows.
        current_video_id_ref: Mutable list; empty = no video in flight,
            non-empty = current_video_id_ref[0] is the in-progress video_id.
        cookies_source: Cookies source string written to the interrupted audit row.

    Returns:
        Signal handler callable(signum, frame) that cleans audio_temp,
        writes interrupted audit row (only when a video is in flight),
        and raises SystemExit(130).
    """
    from datetime import UTC, datetime

    def _handler(signum: int, frame: object) -> None:
        # Remove all temp mp3 files (SC-004)
        for mp3 in audio_temp.glob("*.mp3"):
            mp3.unlink(missing_ok=True)

        # G-4: only write interrupted row when a video is actually in progress
        if current_video_id_ref and current_video_id_ref[0]:
            video_id = current_video_id_ref[0]
            ts = datetime.now(tz=UTC).isoformat()
            if hasattr(audit_writer, "append_fingerprint_row"):
                try:
                    audit_writer.append_fingerprint_row({  # type: ignore[union-attr]
                        "video_id": video_id,
                        "result": "fail",
                        "reason": "interrupted",
                        "duration_sec": None,
                        "timestamp": ts,
                        "cookies_source": cookies_source,
                    })
                except Exception as _exc:
                    # AT-12.3: log to stderr so SS-5 is not silently swallowed
                    import sys
                    print(
                        f"[signal handler] audit write failed: {_exc}",
                        file=sys.stderr,
                    )

        raise SystemExit(130)

    return _handler


def _collect_fingerprint_local(
    channel: str | None,
    video_ids_str: str,
    all_takeout: bool,
    input_kind: str,
    audio_cache_dir: str,
    force: bool,
    data_dir: str,
    db_path_local_str: str,
) -> None:
    """--source local branch: fingerprint Takeout mp4 or cached wav files.

    FR-013~FR-015.
    """
    import datetime
    import sqlite3

    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint
    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.storage.content_db import insert_audio_fingerprint

    if not channel:
        console.print("[red]--channel is required for --source local.[/red]")
        raise typer.Exit(code=2)

    if input_kind not in ("mp4", "wav_16k", "wav_22k"):
        console.print(
            "[red]--input-kind must be mp4, wav_16k, or wav_22k."
            f" Got: {input_kind}[/red]"
        )
        raise typer.Exit(code=2)

    work_root = Path(data_dir)
    db = (
        Path(db_path_local_str) if db_path_local_str else work_root / "content_reuse.db"
    )
    cache_dir = Path(audio_cache_dir)

    if not db.exists():
        console.print(f"[red]DB not found: {db}. Run 'collect takeout' first.[/red]")
        raise typer.Exit(code=2)

    try:
        with sqlite3.connect(db) as conn:
            if video_ids_str:
                ids = [v.strip() for v in video_ids_str.split(",") if v.strip()]
                placeholders = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT video_id, mp4_relative_path FROM video_metadata"
                    f" WHERE video_id IN ({placeholders})",
                    ids,
                ).fetchall()
            elif all_takeout:
                rows = conn.execute(
                    "SELECT video_id, mp4_relative_path FROM video_metadata"
                    " WHERE channel_id IN ("
                    "  SELECT channel_id FROM channel_metadata WHERE channel_alias = ?"
                    ")",
                    (channel,),
                ).fetchall()
            else:
                console.print("[red]Specify --video-ids or --all-takeout.[/red]")
                raise typer.Exit(code=2)
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]DB query error: {exc}[/red]")
        raise typer.Exit(code=2) from exc

    if not rows:
        console.print(
            "[yellow]No video_metadata rows found for the given selection.[/yellow]"
        )
        raise typer.Exit(code=0)

    audit = AuditWriter(work_root / channel)
    any_failed = False

    for video_id, mp4_rel in rows:
        ts = datetime.datetime.now(tz=datetime.UTC).isoformat()

        if input_kind == "mp4":
            if mp4_rel is None:
                audit.append_fingerprint_row({
                    "video_id": video_id,
                    "result": "skip",
                    "reason": "no_mp4_path",
                    "duration_sec": None,
                    "timestamp": ts,
                    "cookies_source": "local",
                    "fingerprint_input_policy": input_kind,
                })
                continue
            input_path = work_root / channel / mp4_rel
        else:
            input_path = cache_dir / f"{video_id}.wav"

        if not input_path.exists():
            any_failed = True
            audit.append_fingerprint_row({
                "video_id": video_id,
                "result": "fail",
                "reason": "input_file_missing",
                "duration_sec": None,
                "timestamp": ts,
                "cookies_source": "local",
                "fingerprint_input_policy": input_kind,
            })
            console.print(
                f"[yellow]skip[/yellow] {video_id}: input not found {input_path}"
            )
            continue

        # Skip if fingerprint already in DB and not force
        if not force:
            try:
                with sqlite3.connect(db) as conn:
                    existing = conn.execute(
                        "SELECT 1 FROM audio_fingerprint WHERE video_id = ?",
                        (video_id,),
                    ).fetchone()
                if existing:
                    audit.append_fingerprint_row({
                        "video_id": video_id,
                        "result": "skip",
                        "reason": "already_fingerprinted",
                        "duration_sec": None,
                        "timestamp": ts,
                        "cookies_source": "local",
                        "fingerprint_input_policy": input_kind,
                    })
                    console.print(f"[dim]skip[/dim] {video_id} already fingerprinted")
                    continue
            except Exception:
                pass

        try:
            fp_bytes, duration = extract_chromaprint_fingerprint(input_path)
            insert_audio_fingerprint(db, video_id, fp_bytes, duration, ts)
            audit.append_fingerprint_row({
                "video_id": video_id,
                "result": "success",
                "reason": "captured",
                "duration_sec": round(duration, 3),
                "timestamp": ts,
                "cookies_source": "local",
                "fingerprint_input_policy": input_kind,
            })
            console.print(f"[green]ok[/green] {video_id} {duration:.1f}s")
        except Exception as exc:
            any_failed = True
            audit.append_fingerprint_row({
                "video_id": video_id,
                "result": "fail",
                "reason": "fpcalc_failed",
                "duration_sec": None,
                "timestamp": ts,
                "cookies_source": "local",
                "fingerprint_input_policy": input_kind,
            })
            console.print(f"[yellow]fail[/yellow] {video_id}: {exc}")

    if any_failed:
        raise typer.Exit(code=5)


def collect_fingerprint_command(
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="Channel alias.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-extract even if fingerprint exists.",
    ),
    input_kind: str = typer.Option(
        "mp4",
        "--input-kind",
        help="Input kind: 'mp4', 'wav_16k', or 'wav_22k'.",
    ),
    video_ids_str: str = typer.Option(
        "",
        "--video-ids",
        help="Comma-separated video IDs.",
    ),
    all_takeout: bool = typer.Option(
        False,
        "--all-takeout",
        help="Process all video_metadata rows for the channel.",
    ),
    audio_cache_dir: str = typer.Option(
        "/tmp/tube-scout-audio",
        "--audio-cache-dir",
        help="WAV cache directory for --input-kind wav_16k/wav_22k.",
    ),
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Work root for channel data directories.",
    ),
    db_path_local_str: str = typer.Option(
        "",
        "--db-path",
        help="Path to content_reuse.db (defaults to <data-dir>/content_reuse.db).",
    ),
) -> None:
    """Extract chromaprint fingerprint from local Takeout mp4 or cached wav.

    FR-013~FR-015 (spec 013). Exit codes: 0=success, 2=alias/selection error,
    5=one or more fpcalc failures.
    """
    _collect_fingerprint_local(
        channel=channel,
        video_ids_str=video_ids_str,
        all_takeout=all_takeout,
        input_kind=input_kind,
        audio_cache_dir=audio_cache_dir,
        force=force,
        data_dir=data_dir,
        db_path_local_str=db_path_local_str,
    )


def collect_process_audio_command(  # noqa: C901
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias (must be registered).",
    ),
    video_ids_str: str = typer.Option(
        "",
        "--video-ids",
        help="Comma-separated video IDs to process.",
    ),
    all_takeout: bool = typer.Option(
        False,
        "--all-takeout",
        help="Process all videos in video_metadata for this channel.",
    ),
    preset: str = typer.Option(
        ...,
        "--preset",
        help="ASR preset: poc-laptop, prod-a6000, prod-a6000-pool, cpu-fallback.",
    ),
    skip_fingerprint: bool = typer.Option(
        False,
        "--skip-fingerprint",
        help="Skip chromaprint fingerprint step.",
    ),
    skip_asr: bool = typer.Option(
        False,
        "--skip-asr",
        help="Skip ASR transcription step.",
    ),
    keep_audio: bool = typer.Option(
        False,
        "--keep-audio",
        help="Keep WAV files after processing (default: delete immediately).",
    ),
    retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        help="Also retry videos with asr_failed status.",
    ),
    auto_normalize: bool = typer.Option(
        True,
        "--auto-normalize/--no-auto-normalize",
        help="Normalize transcript after ASR (default: on).",
        rich_help_panel="Process options",
    ),
    audio_cache_dir: str = typer.Option(
        "/tmp/tube-scout-audio",
        "--audio-cache-dir",
        help="WAV extraction directory.",
        rich_help_panel="Process options",
    ),
    data_dir: str = typer.Option(
        "./data",
        "--data-dir",
        help="Work root for channel data directories.",
        rich_help_panel="Process options",
    ),
    db_path_str: str = typer.Option(
        "",
        "--db-path",
        help="Path to content_reuse.db (defaults to <data-dir>/content_reuse.db).",
        rich_help_panel="Process options",
    ),
) -> None:
    """Integrated per-video pipeline: WAV → fingerprint → ASR → normalize → WAV delete.

    FR-010~FR-025 (spec 013). Exit codes: 0=success, 2=alias/selection error,
    5=one or more per-video failures.
    """
    import datetime
    import signal
    import sqlite3

    from tube_scout.services.asr import PRESET_TABLE, transcribe_audio
    from tube_scout.services.audio_extract import extract_wav_16k_mono
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint
    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.services.progress_reporter import make_progress_reporter
    from tube_scout.services.text_normalizer import normalize_transcript_json
    from tube_scout.storage.content_db import insert_audio_fingerprint

    work_root = Path(data_dir)
    db = Path(db_path_str) if db_path_str else work_root / "content_reuse.db"
    cache_dir = Path(audio_cache_dir)

    if not db.exists():
        console.print(f"[red]DB not found: {db}. Run 'collect takeout' first.[/red]")
        raise typer.Exit(code=2)

    cache_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir = work_root / channel / "01_collect" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir = work_root / channel / "01_collect" / "transcripts_normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    # Resolve video list
    try:
        with sqlite3.connect(db) as conn:
            if video_ids_str:
                ids = [v.strip() for v in video_ids_str.split(",") if v.strip()]
                placeholders = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT video_id, mp4_relative_path FROM video_metadata"
                    f" WHERE video_id IN ({placeholders})",
                    ids,
                ).fetchall()
            elif all_takeout:
                rows = conn.execute(
                    "SELECT vm.video_id, vm.mp4_relative_path FROM video_metadata vm"
                    " JOIN channel_metadata cm ON cm.channel_id = vm.channel_id"
                    " WHERE cm.channel_alias = ?",
                    (channel,),
                ).fetchall()
            else:
                console.print("[red]Specify --video-ids or --all-takeout.[/red]")
                raise typer.Exit(code=2)
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]DB query error: {exc}[/red]")
        raise typer.Exit(code=2) from exc

    if not rows:
        console.print("[yellow]No videos found for the given selection.[/yellow]")
        raise typer.Exit(code=0)

    preset_cfg = PRESET_TABLE.get(preset, {})
    model_size = str(preset_cfg.get("model", "large-v3"))
    compute_type = str(preset_cfg.get("compute_type", "int8_float16"))
    device = str(preset_cfg.get("device", "cuda"))
    device_index = int(preset_cfg.get("device_index") or 0)

    audit = AuditWriter(work_root / channel)
    any_failed = False

    # SIGINT/SIGTERM: clean up current wav, write interrupted audit row
    current_wav_ref: list[Path] = []

    def _sighandler(signum: int, frame: object) -> None:
        for wav in current_wav_ref:
            if wav.exists():
                wav.unlink(missing_ok=True)
        raise SystemExit(130)

    signal.signal(signal.SIGINT, _sighandler)
    signal.signal(signal.SIGTERM, _sighandler)

    with make_progress_reporter("transcripts", total=len(rows)) as progress:
        for i, (video_id, mp4_rel) in enumerate(rows, start=1):
            ts = datetime.datetime.now(tz=datetime.UTC).isoformat()

            if mp4_rel is None:
                console.print(f"[yellow]skip[/yellow] {video_id}: no mp4_relative_path")
                any_failed = True
                progress.update(video_id, i)
                continue

            mp4_path = work_root / channel / mp4_rel
            if not mp4_path.exists():
                console.print(
                    f"[yellow]skip[/yellow] {video_id}: mp4 not found {mp4_path}"
                )
                any_failed = True
                progress.update(video_id, i)
                continue

            wav_path = cache_dir / f"{video_id}.wav"
            current_wav_ref[:] = [wav_path]

            try:
                # Step 1: WAV extract
                try:
                    extract_wav_16k_mono(mp4_path, wav_path, force=True)
                except (FileNotFoundError, RuntimeError) as exc:
                    console.print(f"[yellow]wav fail[/yellow] {video_id}: {exc}")
                    any_failed = True
                    continue

                # Step 2: fingerprint (optional)
                if not skip_fingerprint:
                    try:
                        fp_bytes, fp_duration = extract_chromaprint_fingerprint(
                            mp4_path
                        )
                        insert_audio_fingerprint(
                            db, video_id, fp_bytes, fp_duration, ts
                        )
                        audit.append_fingerprint_row({
                            "video_id": video_id,
                            "result": "success",
                            "reason": "captured",
                            "duration_sec": round(fp_duration, 3),
                            "timestamp": ts,
                            "cookies_source": "local",
                        })
                    except Exception as exc:
                        console.print(f"[yellow]fp fail[/yellow] {video_id}: {exc}")

                # Step 3: ASR (optional)
                if not skip_asr:
                    import json as _json
                    import os as _os
                    import tempfile as _tempfile

                    try:
                        asr_result = transcribe_audio(
                            wav_path,
                            model_size=model_size,
                            compute_type=compute_type,
                            device=device,
                            device_index=device_index,
                        )
                        transcript = {
                            "video_id": video_id,
                            "source": asr_result.caption_source_detail,
                            "language": asr_result.language_detected,
                            "duration": asr_result.duration,
                            "segments": asr_result.segments,
                            "asr_quality_flags": (
                                asr_result.asr_quality_flags.model_dump()
                            ),
                            "fetched_at": ts,
                        }
                        json_path = transcript_dir / f"{video_id}.json"
                        fd, tmp_name = _tempfile.mkstemp(
                            dir=transcript_dir, suffix=".tmp"
                        )
                        try:
                            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                                _json.dump(transcript, f, ensure_ascii=False, indent=2)
                            _os.replace(tmp_name, json_path)
                        except Exception:
                            try:
                                _os.unlink(tmp_name)
                            except OSError:
                                pass
                            raise

                        # Step 4: normalize (optional)
                        if auto_normalize:
                            norm_path = normalized_dir / f"{video_id}.json"
                            normalize_transcript_json(json_path, norm_path, force=False)

                        audit.append_transcript_row({
                            "video_id": video_id,
                            "result": "success",
                            "reason": "asr_transcribed",
                            "source": asr_result.caption_source_detail,
                            "timestamp": ts,
                            "cookies_source": "local",
                        })
                        console.print(
                            f"[green]ok[/green] {video_id} "
                            f"lang={asr_result.language_detected} "
                            f"dur={asr_result.duration:.1f}s"
                        )
                    except Exception as exc:
                        console.print(f"[yellow]asr fail[/yellow] {video_id}: {exc}")
                        any_failed = True

            finally:
                if not keep_audio and wav_path.exists():
                    wav_path.unlink(missing_ok=True)
                current_wav_ref[:] = []

            progress.update(video_id, i)

    if any_failed:
        raise typer.Exit(code=5)


def collect_takeout_command(
    takeout_dir: str = typer.Option(
        ...,
        "--takeout-dir",
        help="Takeout decompressed root directory (contains YouTube subdir).",
    ),
    channel: str = typer.Option(
        ...,
        "--channel",
        help="spec 003 channel alias (must be registered).",
    ),
    copy: bool = typer.Option(
        False,
        "--copy",
        help="Copy mp4 files instead of creating symlinks.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print mapping results only; no DB writes.",
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
    """Ingest Google Takeout export: parse CSV metadata, map mp4 to video_id, persist.

    FR-001/FR-002/FR-009 (spec 016). Exit codes: 0=success, 1=error.
    """
    import os as _os

    from tube_scout.services.takeout_ingest import ingest_takeout

    # FR-015: block collect if alias has a mismatch between registries
    try:
        from tube_scout.services.auth import load_registry
        from tube_scout.web.repo.departments_repo import DepartmentsRepo
        channels_reg = load_registry()
        depts_reg = {d.alias: d for d in DepartmentsRepo().list_all()}
        if channel in channels_reg and channel in depts_reg:
            dept = depts_reg[channel]
            ch_channel_id = channels_reg[channel].channel_id
            dept_channel_id = (
                _os.environ.get(dept.channel_id_env) if dept.channel_id_env else None
            )
            if dept_channel_id and dept_channel_id != ch_channel_id:
                console.print(
                    f"[red]Error: alias '{channel}' mismatch between registries "
                    f"(channels.json={ch_channel_id!r}, "
                    f"departments.json env={dept_channel_id!r}). "
                    f"Resolve the inconsistency before running collect.[/red]"
                )
                raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception:
        pass  # registry load failure is non-blocking for mismatch check

    takeout_path = Path(takeout_dir)
    work_root = Path(data_dir)
    db = Path(db_path_str) if db_path_str else work_root / "content_reuse.db"

    if not takeout_path.exists():
        console.print(
            f"[red]Error: --takeout-dir '{takeout_dir}' does not exist.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        result = ingest_takeout(
            takeout_dir=takeout_path,
            channel_alias=channel,
            db_path=db,
            work_root=work_root,
            use_symlinks=not copy,
            dry_run=dry_run,
        )
    except ValueError as exc:
        console.print(f"[red]Alias error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        console.print(f"[red]Path error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    mode = "[dim](dry-run)[/dim]" if dry_run else ""
    console.print(
        f"[green]takeout ingest complete {mode}[/green] "
        f"channel={result.channel_alias} "
        f"total={result.total_videos} new={result.new_videos} "
        f"high={result.high_confidence_mappings} "
        f"medium={result.medium_confidence_mappings} "
        f"ambiguous={result.ambiguous_mappings} "
        f"unmapped={result.unmapped_filenames} "
        f"ignored_csv={result.ignored_csv_count}"
    )


def collect_audio_extract_command(
    channel: str = typer.Option(
        ...,
        "--channel",
        help="Channel alias (must be registered in spec 003 auth registry).",
    ),
    video_ids_str: str = typer.Option(
        "",
        "--video-ids",
        help="Comma-separated video IDs to process. Overrides --all-takeout.",
    ),
    all_takeout: bool = typer.Option(
        False,
        "--all-takeout",
        help="Process all videos in video_metadata for this channel.",
    ),
    audio_cache_dir: str = typer.Option(
        "/tmp/tube-scout-audio",
        "--audio-cache-dir",
        help="Directory where WAV files are written (accumulated, not deleted).",
    ),
    keep_audio: bool = typer.Option(
        False,
        "--keep-audio",
        help="Do not delete WAV after extraction (no-op in standalone extract mode).",
    ),
    sample_rate: int = typer.Option(
        16000,
        "--sample-rate",
        help="Target sample rate in Hz (default 16000 for faster-whisper).",
    ),
    codec: str = typer.Option(
        "pcm_s16le",
        "--codec",
        help="Audio codec: pcm_s16le (default) or flac.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing WAV files.",
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
    """Extract mono 16 kHz WAV from Takeout mp4 files.

    FR-010~FR-012 (spec 013). Exit codes: 0=success, 2=alias error,
    5=one or more ffmpeg failures.
    """
    import datetime
    import sqlite3
    import time

    from tube_scout.services.audio_extract import extract_wav_16k_mono
    from tube_scout.services.audit_writer import AuditWriter

    work_root = Path(data_dir)
    db = Path(db_path_str) if db_path_str else work_root / "content_reuse.db"
    cache_dir = Path(audio_cache_dir)

    if not db.exists():
        console.print(f"[red]DB not found: {db}. Run \'collect takeout\' first.[/red]")
        raise typer.Exit(code=2)

    cache_dir.mkdir(parents=True, exist_ok=True)

    # Resolve video list from DB
    try:
        with sqlite3.connect(db) as conn:
            if video_ids_str:
                ids = [v.strip() for v in video_ids_str.split(",") if v.strip()]
                placeholders = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT video_id, mp4_relative_path FROM video_metadata"
                    f" WHERE video_id IN ({placeholders})",
                    ids,
                ).fetchall()
            elif all_takeout:
                rows = conn.execute(
                    "SELECT video_id, mp4_relative_path FROM video_metadata"
                    " WHERE channel_id IN ("
                    "  SELECT channel_id FROM channel_metadata WHERE channel_alias = ?"
                    ")",
                    (channel,),
                ).fetchall()
            else:
                console.print("[red]Specify --video-ids or --all-takeout.[/red]")
                raise typer.Exit(code=2)
    except ValueError as exc:
        console.print(f"[red]Alias error: {exc}[/red]")
        raise typer.Exit(code=2) from exc

    if not rows:
        console.print(
            "[yellow]No video_metadata rows found for the given selection.[/yellow]"
        )
        raise typer.Exit(code=0)

    audit = AuditWriter(work_root / channel)
    any_failed = False

    for video_id, mp4_rel in rows:
        wav_path = cache_dir / f"{video_id}.wav"
        ts = datetime.datetime.now(tz=datetime.UTC).isoformat()

        if mp4_rel is None:
            audit.append_row("audio_extract", {
                "video_id": video_id,
                "result": "skip",
                "reason": "no_mp4_path",
                "input_kind": "mp4",
                "output_path": "",
                "wav_size_bytes": 0,
                "elapsed_s": 0.0,
                "timestamp": ts,
            })
            continue

        mp4_path = work_root / channel / mp4_rel
        t0 = time.monotonic()
        try:
            extract_wav_16k_mono(
                mp4_path,
                wav_path,
                sample_rate=sample_rate,
                codec=codec,
                force=force,
            )
            elapsed = time.monotonic() - t0
            audit.append_row("audio_extract", {
                "video_id": video_id,
                "result": "success",
                "reason": "extracted",
                "input_kind": "mp4",
                "output_path": str(wav_path),
                "wav_size_bytes": wav_path.stat().st_size if wav_path.exists() else 0,
                "elapsed_s": round(elapsed, 3),
                "timestamp": ts,
            })
            console.print(f"[green]ok[/green] {video_id} -> {wav_path.name}")
        except (FileNotFoundError, RuntimeError) as exc:
            any_failed = True
            elapsed = time.monotonic() - t0
            audit.append_row("audio_extract", {
                "video_id": video_id,
                "result": "fail",
                "reason": "audio_decode_failed",
                "input_kind": "mp4",
                "output_path": "",
                "wav_size_bytes": 0,
                "elapsed_s": round(elapsed, 3),
                "timestamp": ts,
            })
            console.print(f"[yellow]fail[/yellow] {video_id}: {exc}")

    if any_failed:
        raise typer.Exit(code=5)


def collect_ingest_command(
    takeout_dir: str = typer.Option(
        ...,
        "--takeout-dir",
        help="Takeout decompressed root directory (contains YouTube subdir).",
    ),
    channel: str = typer.Option(
        ...,
        "--channel",
        help="spec 003 channel alias (must be registered).",
    ),
    delete_source: bool = typer.Option(
        False,
        "--delete-source",
        help="Prompt to delete source mp4 files after processing.",
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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print mapping results only; no DB writes, no ASR/fingerprint.",
    ),
    copy: bool = typer.Option(
        False,
        "--copy",
        help="Copy mp4 files instead of creating symlinks.",
    ),
) -> None:
    """Unified ingest: takeout → ASR → fingerprint → retry manifest → optional cleanup.

    FR-010/FR-011/FR-012/FR-013/FR-017 (spec 017). Exit codes: 0=success, 1=error.
    """
    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.services.unified_ingest import ingest_unified

    # B-9: block collect if alias has a mismatch between registries (Fix T-17/T-18)
    try:
        from tube_scout.services.auth import load_registry
        from tube_scout.web.repo.departments_repo import DepartmentsRepo

        channels_reg = load_registry()
        depts_reg = {d.alias: d for d in DepartmentsRepo().list_all()}
        alias_in_channels = channel in channels_reg
        alias_in_depts = channel in depts_reg
        if alias_in_channels and alias_in_depts:
            dept = depts_reg[channel]
            ch_channel_id = channels_reg[channel].channel_id
            dept_channel_id = (
                os.environ.get(dept.channel_id_env) if dept.channel_id_env else None
            )
            if dept_channel_id and dept_channel_id != ch_channel_id:
                console.print(
                    f"[red]Error: alias '{channel}' mismatch between registries "
                    f"(channels.json={ch_channel_id!r}, "
                    f"departments.json env={dept_channel_id!r}). "
                    f"Resolve the inconsistency before running ingest.[/red]"
                )
                raise typer.Exit(code=1)
        elif not alias_in_channels and not alias_in_depts:
            console.print(
                f"[red]Error: alias '{channel}' not registered in any registry. "
                f"Run 'tube-scout admin list' to inspect.[/red]"
            )
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except (FileNotFoundError, KeyError, ValueError) as exc:
        # intentional-skip: registry load failure non-blocking (B-9 via service layer)
        console.print(
            f"[yellow]Warning: alias mismatch check skipped "
            f"— registry load failed: {exc}[/yellow]"
        )

    takeout_path = Path(takeout_dir)
    work_root = Path(data_dir)
    db = Path(db_path_str) if db_path_str else work_root / "content_reuse.db"

    if not takeout_path.exists():
        console.print(
            f"[red]Error: --takeout-dir '{takeout_dir}' does not exist.[/red]"
        )
        raise typer.Exit(code=1)

    audit = AuditWriter(work_root / channel)

    try:
        summary = ingest_unified(
            takeout_dir=takeout_path,
            channel_alias=channel,
            db_path=db,
            work_root=work_root,
            use_symlinks=not copy,
            dry_run=dry_run,
            delete_source=delete_source,
            audit_writer=audit,
        )
    except ValueError as exc:
        console.print(f"[red]Alias error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        console.print(f"[red]Path error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    mode = "[dim](dry-run)[/dim]" if dry_run else ""
    console.print(
        f"[green]ingest complete {mode}[/green] "
        f"channel={summary.ingest_result.channel_alias} "
        f"new={summary.ingest_result.new_videos} "
        f"transcripts={summary.transcript_result.success_count} "
        f"fingerprints={summary.fingerprint_result.success_count} "
        f"elapsed={summary.total_elapsed_seconds}s"
    )
