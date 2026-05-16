"""Unified ingest orchestrator — collect ingest command backend (spec 017 US1).

FR-005~FR-009, FR-011~FR-017, SC-004, SC-005.
Wraps spec 016 ingest_takeout + transcript + fingerprint + retry manifest +
optional source video cleanup into a single call.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from tube_scout.models.content import (
    FailureEntry,
    FingerprintStageResult,
    RetryManifestDelta,
    TranscriptStageResult,
    UnifiedIngestSummary,
)
from tube_scout.services.asr import TranscribeResult, transcribe_audio
from tube_scout.services.audio_extract import WavLifecycle, extract_wav_16k_mono
from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint
from tube_scout.services.takeout_ingest import IngestResult, ingest_takeout
from tube_scout.storage.content_db import insert_audio_fingerprint

# Resolve forward reference IngestResult → UnifiedIngestSummary.ingest_result field
UnifiedIngestSummary.model_rebuild()

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.services.source_video_cleanup import PromptIO


@dataclass(frozen=True)
class IdempotencyGuardResult:
    """Per-video idempotency check result (spec 018 data-model §2.1).

    Attributes:
        video_id: YouTube video ID being checked.
        transcript_skip: True when transcript json already exists on disk.
        fingerprint_skip: True when audio_fingerprint row already in DB.
        wav_decode_skip: True when both transcript_skip and fingerprint_skip are True
            (WAV decode can be skipped entirely).
    """

    video_id: str
    transcript_skip: bool
    fingerprint_skip: bool
    wav_decode_skip: bool


def _persist_transcript(
    transcript_dir: Path,
    video_id: str,
    asr_result: TranscribeResult,
    ts: str,
) -> Path:
    """Atomically write ASR result as transcript JSON (spec 018 FR-018A).

    Uses tempfile + os.replace for atomic write. Raises PermissionError if
    transcript_dir is not writable. No .tmp residue on failure.

    Args:
        transcript_dir: Directory where transcript JSON files are stored.
        video_id: YouTube video ID; used as filename stem.
        asr_result: ASR transcription result with segments and quality flags.
        ts: ISO-8601 timestamp string for the fetched_at field.

    Returns:
        Absolute path of the written JSON file.
    """
    dst_path = transcript_dir / f"{video_id}.json"
    transcript_dict = {
        "video_id": video_id,
        "source": asr_result.caption_source_detail,
        "language": asr_result.language_detected,
        "duration": asr_result.duration,
        "segments": asr_result.segments,
        "asr_quality_flags": asr_result.asr_quality_flags.model_dump(),
        "fetched_at": ts,
    }
    fd, tmp_name = tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(transcript_dict, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, dst_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return dst_path.resolve()


def _check_already_processed(
    video_id: str,
    transcript_dir: Path,
    db_path: Path,
    *,
    force: bool = False,
) -> IdempotencyGuardResult:
    """Check whether transcript and fingerprint have already been persisted.

    When force=True, returns all-False result (bypass guard). When force=False,
    checks transcript JSON existence on disk and audio_fingerprint row in DB.

    Args:
        video_id: YouTube video ID to check.
        transcript_dir: Directory containing per-video transcript JSON files.
        db_path: SQLite DB path for audio_fingerprint row lookup.
        force: If True, skip all checks and return (False, False, False) guard.

    Returns:
        IdempotencyGuardResult with per-stage skip flags.
    """
    if force:
        return IdempotencyGuardResult(
            video_id=video_id,
            transcript_skip=False,
            fingerprint_skip=False,
            wav_decode_skip=False,
        )

    transcript_skip = (transcript_dir / f"{video_id}.json").exists()

    with sqlite3.connect(db_path) as conn:
        fingerprint_skip = bool(
            conn.execute(
                "SELECT 1 FROM audio_fingerprint WHERE video_id = ? LIMIT 1",
                (video_id,),
            ).fetchone()
        )

    wav_decode_skip = transcript_skip and fingerprint_skip

    return IdempotencyGuardResult(
        video_id=video_id,
        transcript_skip=transcript_skip,
        fingerprint_skip=fingerprint_skip,
        wav_decode_skip=wav_decode_skip,
    )


def _run_transcript_and_fingerprint(
    mp4_video_id_map: dict[str, str],
    work_root: Path,
    audit_writer: AuditWriter,
    *,
    skipped_no_mp4_count: int = 0,
    transcript_dir: Path | None = None,
    db_path: Path | None = None,
    force: bool = False,
) -> tuple[TranscriptStageResult, FingerprintStageResult]:
    """Run ASR + chromaprint fingerprint for each mp4-mapped video.

    Each mp4 is decoded to a temporary WAV once (SC-005). Both ASR and
    fingerprint share that WAV, then WavLifecycle deletes it on exit (B-1).
    Results are persisted: transcript JSON (FR-018A) and DB row (FR-018B).

    Args:
        mp4_video_id_map: Mapping of mp4 absolute path str → video_id.
        work_root: Channel work directory root for WAV temp storage.
        audit_writer: AuditWriter for per-video audit rows.
        skipped_no_mp4_count: Videos with no mp4 file (excluded from processing).
        transcript_dir: Directory for transcript JSON files (FR-018A).
        db_path: SQLite DB path for audio_fingerprint persistence (FR-018B).
        force: If True, bypass idempotency guard — reprocess all videos (Phase 5).

    Returns:
        (TranscriptStageResult, FingerprintStageResult) tuple.
    """
    wav_dir = work_root / "tmp_wav"
    wav_dir.mkdir(parents=True, exist_ok=True)

    # T017: transcript_dir mkdir (FR-018A)
    if transcript_dir is not None:
        transcript_dir.mkdir(parents=True, exist_ok=True)

    transcript_successes = 0
    transcript_skips = 0
    transcript_failures: list[FailureEntry] = []
    fingerprint_successes = 0
    fingerprint_skips = 0
    fingerprint_failures: list[FailureEntry] = []
    t_start = time.monotonic()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        transient=False,
        disable=not sys.stdout.isatty(),
    ) as progress:
        task_id = progress.add_task("자막+지문 처리", total=len(mp4_video_id_map))
        for mp4_path_str, video_id in mp4_video_id_map.items():
            progress.update(task_id, description=f"자막+지문: {video_id[:11]}")
            mp4_path = Path(mp4_path_str)
            attempted_at = datetime.now(tz=UTC)
            ts = attempted_at.isoformat()

            # T028: idempotency guard — check before any IO (FR-018C)
            guard: IdempotencyGuardResult | None = None
            if transcript_dir is not None and db_path is not None:
                guard = _check_already_processed(
                    video_id, transcript_dir, db_path, force=force
                )

            if guard is not None and guard.wav_decode_skip:
                # T028: both already done — skip WAV decode entirely (FR-018E)
                transcript_skips += 1
                fingerprint_skips += 1
                audit_writer.append_row("ingest_orchestrator", {
                    "video_id": video_id,
                    "result": "skip",
                    "reason": "already_transcribed",
                    "channel_alias": work_root.name,
                    "elapsed_ms": 0,
                    "timestamp": ts,
                })
                audit_writer.append_row("ingest_orchestrator", {
                    "video_id": video_id,
                    "result": "skip",
                    "reason": "already_fingerprinted",
                    "channel_alias": work_root.name,
                    "elapsed_ms": 0,
                    "timestamp": ts,
                })
                progress.advance(task_id)
                continue

            with WavLifecycle(mp4_path, wav_dir, video_id) as wav_path:
                # SC-005: extract WAV once, share between ASR and fingerprint
                try:
                    extract_wav_16k_mono(mp4_path, wav_path)
                except Exception as exc:
                    reason = f"audio_decode_failed: {exc}"
                    transcript_failures.append(FailureEntry(
                        video_id=video_id,
                        title=mp4_path.stem,
                        failed_stage="transcript",
                        failure_reason=reason,
                        attempted_at=attempted_at,
                    ))
                    fingerprint_failures.append(FailureEntry(
                        video_id=video_id,
                        title=mp4_path.stem,
                        failed_stage="fingerprint",
                        failure_reason=reason,
                        attempted_at=attempted_at,
                    ))
                    progress.advance(task_id)
                    continue

                # T029: ASR stage — skip if guard says transcript already present
                if guard is not None and guard.transcript_skip:
                    transcript_skips += 1
                    audit_writer.append_row("ingest_orchestrator", {
                        "video_id": video_id,
                        "result": "skip",
                        "reason": "already_transcribed",
                        "channel_alias": work_root.name,
                        "elapsed_ms": 0,
                        "timestamp": ts,
                    })
                else:
                    # ASR (boundary B-2) + persist transcript JSON (FR-018A)
                    try:
                        asr_result = transcribe_audio(wav_path)
                        if transcript_dir is not None:
                            _persist_transcript(
                                transcript_dir, video_id, asr_result, ts
                            )
                        transcript_successes += 1
                        audit_writer.append_row("ingest_orchestrator", {
                            "video_id": video_id,
                            "result": "success",
                            "reason": "asr_transcribed",
                            "channel_alias": work_root.name,
                            "elapsed_ms": 0,
                            "timestamp": ts,
                        })
                    except Exception as exc:
                        transcript_failures.append(FailureEntry(
                            video_id=video_id,
                            title=mp4_path.stem,
                            failed_stage="transcript",
                            failure_reason=str(exc),
                            attempted_at=attempted_at,
                        ))
                        audit_writer.append_row("ingest_orchestrator", {
                            "video_id": video_id,
                            "result": "fail",
                            "reason": "asr_fail",
                            "channel_alias": work_root.name,
                            "elapsed_ms": 0,
                            "timestamp": ts,
                        })

                # T029: fingerprint stage — skip if guard says already done
                if guard is not None and guard.fingerprint_skip:
                    fingerprint_skips += 1
                    audit_writer.append_row("ingest_orchestrator", {
                        "video_id": video_id,
                        "result": "skip",
                        "reason": "already_fingerprinted",
                        "channel_alias": work_root.name,
                        "elapsed_ms": 0,
                        "timestamp": ts,
                    })
                else:
                    # Fingerprint (boundary B-3) + persist DB row (FR-018B)
                    try:
                        fp_bytes, duration = extract_chromaprint_fingerprint(wav_path)
                        if db_path is not None:
                            insert_audio_fingerprint(
                                db_path, video_id, fp_bytes, duration, ts
                            )
                        fingerprint_successes += 1
                        audit_writer.append_row("ingest_orchestrator", {
                            "video_id": video_id,
                            "result": "success",
                            "reason": "captured",
                            "channel_alias": work_root.name,
                            "elapsed_ms": 0,
                            "timestamp": ts,
                        })
                    except Exception as exc:
                        fingerprint_failures.append(FailureEntry(
                            video_id=video_id,
                            title=mp4_path.stem,
                            failed_stage="fingerprint",
                            failure_reason=str(exc),
                            attempted_at=attempted_at,
                        ))
                        audit_writer.append_row("ingest_orchestrator", {
                            "video_id": video_id,
                            "result": "fail",
                            "reason": "fp_fail",
                            "channel_alias": work_root.name,
                            "elapsed_ms": 0,
                            "timestamp": ts,
                        })

            progress.advance(task_id)

    # SC-005: transcript + fingerprint share one WAV pass; elapsed covers both.
    # elapsed_seconds unit: wall-clock seconds (float). audit rows use elapsed_ms (int).
    elapsed = time.monotonic() - t_start
    transcript_result = TranscriptStageResult(
        success_count=transcript_successes,
        failure_count=len(transcript_failures),
        skipped_no_mp4_count=skipped_no_mp4_count,
        skip_count=transcript_skips,
        failures=transcript_failures,
        elapsed_seconds=elapsed,
    )
    fingerprint_result = FingerprintStageResult(
        success_count=fingerprint_successes,
        failure_count=len(fingerprint_failures),
        skipped_no_mp4_count=skipped_no_mp4_count,
        skip_count=fingerprint_skips,
        failures=fingerprint_failures,
        elapsed_seconds=elapsed,
    )
    return transcript_result, fingerprint_result


def _update_retry_manifest(
    failures: list[FailureEntry],
    succeeded_video_ids: set[str],
    manifest_path: Path,
    audit_writer: AuditWriter,
) -> RetryManifestDelta:
    """Update retry_pending.json — add failures, resolve successes.

    Args:
        failures: Combined failures from transcript + fingerprint stages.
        succeeded_video_ids: Video IDs that succeeded this run (for resolution).
        manifest_path: Path to retry_pending.json.
        audit_writer: AuditWriter for audit rows.

    Returns:
        RetryManifestDelta describing changes to the manifest.
    """
    from tube_scout.services import retry_manifest as _rm

    manifest = _rm.load_manifest(manifest_path)
    now = datetime.now(tz=UTC)

    add_delta = _rm.add_or_update_failures(manifest, failures, now=now)
    resolve_delta = _rm.resolve_successes(manifest, succeeded_video_ids)

    manifest.updated_at = now
    _rm.save_manifest(manifest_path, manifest)

    return RetryManifestDelta(
        added_count=add_delta.added_count,
        resolved_count=resolve_delta.resolved_count,
        remaining_count=len(manifest.entries),
        manifest_path=manifest_path,
    )


def _print_summary_table(
    summary: UnifiedIngestSummary,
    *,
    console: Console,
) -> None:
    """Print the 5-row Rich Table of stage results (T017, contracts/collect-ingest.md).

    Args:
        summary: Completed UnifiedIngestSummary.
        console: Rich Console for output.
    """
    table = Table(title=None, show_header=True, header_style="bold")
    table.add_column("단계", style="cyan")
    table.add_column("처리", justify="right")
    table.add_column("skip", justify="right")
    table.add_column("실패", justify="right")
    table.add_column("소요 시간", justify="right")

    ir = summary.ingest_result
    table.add_row(
        "적재",
        str(ir.total_videos),
        "-",
        "0",
        f"{ir.elapsed_seconds:.0f}s",
    )

    tr = summary.transcript_result
    table.add_row(
        "자막 생성",
        str(tr.success_count),
        str(tr.skip_count),
        str(tr.failure_count),
        f"{tr.elapsed_seconds:.1f}s",
    )

    fr = summary.fingerprint_result
    table.add_row(
        "음원 지문",
        str(fr.success_count),
        str(fr.skip_count),
        str(fr.failure_count),
        f"{fr.elapsed_seconds:.1f}s",
    )

    rd = summary.retry_manifest_delta
    table.add_row(
        "매니페스트 갱신",
        f"{rd.added_count} 추가",
        "-",
        f"{rd.resolved_count} 해소",
        "<1s",
    )

    if summary.cleanup_result is not None:
        cr = summary.cleanup_result
        table.add_row(
            "영상 정리",
            str(cr.deleted_count),
            "-",
            str(cr.failed_to_delete_count),
            f"{cr.elapsed_seconds:.1f}s",
        )
    else:
        table.add_row("영상 정리", "skip", "-", "-", "-")

    console.print(table)
    total = summary.total_elapsed_seconds
    console.print(
        f"[green]✓ 통합 명령 완료[/green] "
        f"(alias={summary.channel_alias}, 총 소요 {total:.1f}s)"
    )


def ingest_unified(
    takeout_dir: Path,
    channel_alias: str,
    db_path: Path,
    work_root: Path,
    *,
    use_symlinks: bool = True,
    dry_run: bool = False,
    delete_source: bool = False,
    force: bool = False,
    audit_writer: AuditWriter,
    prompt_io: PromptIO | None = None,
) -> UnifiedIngestSummary:
    """Run the unified ingest pipeline (spec 017 US1).

    Steps: (1) Takeout ingest → (2) Transcript+Fingerprint → (3) Retry manifest
    → (4) Source video cleanup (--delete-source only).

    Args:
        takeout_dir: Takeout decompressed root (archive root or Takeout/ dir).
        channel_alias: Department alias registered in channels/departments.
        db_path: SQLite v4 database path.
        work_root: Channel work directory root (data/ parent).
        use_symlinks: Symlink mp4 files instead of copying.
        dry_run: Skip DB writes and stages 2-4; measure ingest only.
        delete_source: Enter source video cleanup stage after analysis.
        force: Bypass idempotency guard — reprocess all videos (FR-018D).
        audit_writer: AuditWriter for ingest_orchestrator stage rows.
        prompt_io: Operator prompt adapter; uses TTY stdin/stdout if None.

    Returns:
        UnifiedIngestSummary with all stage results.

    Raises:
        ValueError: alias not registered or mismatch.
        FileNotFoundError: takeout_dir does not exist.
    """
    is_tty = sys.stdout.isatty()
    _console = Console(stderr=False)
    started_at = datetime.now(tz=UTC)
    _t0 = time.monotonic()

    audit_writer.append_row("ingest_orchestrator", {
        "video_id": "",
        "result": "success",
        "reason": "started",
        "channel_alias": channel_alias,
        "elapsed_ms": 0,
        "timestamp": started_at.isoformat(),
    })

    # T040: forced_reprocess audit row (FR-018D visibility)
    if force:
        audit_writer.append_row("ingest_orchestrator", {
            "video_id": "",
            "result": "success",
            "reason": "forced_reprocess",
            "channel_alias": channel_alias,
            "elapsed_ms": 0,
            "timestamp": started_at.isoformat(),
        })

    # ── Step 1: Takeout ingest ──────────────────────────────────────────────
    if is_tty:
        _console.print("[bold]▶ Step 1/5: Takeout 적재[/bold]")

    ingest_result: IngestResult = ingest_takeout(
        takeout_dir=takeout_dir,
        channel_alias=channel_alias,
        db_path=db_path,
        work_root=work_root,
        use_symlinks=use_symlinks,
        dry_run=dry_run,
    )

    if is_tty:
        _console.print(
            f"  [green]→[/green] 영상 {ingest_result.total_videos}, "
            f"mp4 매핑 {ingest_result.high_confidence_mappings} high, "
            f"소요 {ingest_result.elapsed_seconds:.0f}s"
        )

    # ── Step 2: dry-run 시 조기 종료 ───────────────────────────────────────
    if dry_run:
        completed_at = datetime.now(tz=UTC)
        total_elapsed = time.monotonic() - _t0
        empty_tr = TranscriptStageResult(
            success_count=0, failure_count=0,
            skipped_no_mp4_count=ingest_result.total_videos,
            failures=[], elapsed_seconds=0.0,
        )
        empty_fr = FingerprintStageResult(
            success_count=0, failure_count=0,
            skipped_no_mp4_count=ingest_result.total_videos,
            failures=[], elapsed_seconds=0.0,
        )
        manifest_path = work_root / channel_alias / "retry_pending.json"
        empty_rd = RetryManifestDelta(
            added_count=0, resolved_count=0, remaining_count=0,
            manifest_path=manifest_path,
        )
        summary = UnifiedIngestSummary(
            channel_alias=channel_alias,
            ingest_result=ingest_result,
            transcript_result=empty_tr,
            fingerprint_result=empty_fr,
            cleanup_result=None,
            retry_manifest_delta=empty_rd,
            total_elapsed_seconds=total_elapsed,
            started_at=started_at,
            completed_at=completed_at,
        )
        _print_summary_table(summary, console=_console)
        return summary

    # ── Step 3: 자막 + 지문 (retry targets 우선) ──────────────────────────
    if is_tty:
        _console.print("[bold]▶ Step 2/5: 자막 생성 (faster-whisper)[/bold]")
        _console.print("[bold]▶ Step 3/5: 음원 지문 추출 (chromaprint)[/bold]")

    raw_mp4_map = ingest_result.mp4_video_id_map
    absent_count = ingest_result.total_videos - len(raw_mp4_map)

    # FR-015, FR-018: prioritise manifest retry targets at front of processing queue
    from tube_scout.services import retry_manifest as _rm_pre
    _pre_manifest_path = work_root / channel_alias / "retry_pending.json"
    _pre_manifest = _rm_pre.load_manifest(_pre_manifest_path)
    _retry_target_ids = set(_rm_pre.select_retry_targets(_pre_manifest, max_attempts=5))
    # Retry targets processed first; _check_already_processed handles per-video skip.
    # force=True bypasses the guard inside _run_transcript_and_fingerprint.
    _retry_mp4 = {k: v for k, v in raw_mp4_map.items() if v in _retry_target_ids}
    _rest_mp4 = {k: v for k, v in raw_mp4_map.items() if v not in _retry_target_ids}
    mp4_video_id_map = {**_retry_mp4, **_rest_mp4}

    _channel_work = work_root / channel_alias
    _transcript_dir = _channel_work / "02_analyze" / "transcripts"
    transcript_result, fingerprint_result = _run_transcript_and_fingerprint(
        mp4_video_id_map,
        _channel_work,
        audit_writer,
        skipped_no_mp4_count=absent_count,
        transcript_dir=_transcript_dir,
        db_path=db_path,
        force=force,
    )

    if is_tty:
        _console.print(
            f"  [green]→[/green] 자막 성공 {transcript_result.success_count}, "
            f"실패 {transcript_result.failure_count}, "
            f"mp4 부재 skip {transcript_result.skipped_no_mp4_count}"
        )

    # ── Step 4: 재시도 매니페스트 갱신 ────────────────────────────────────
    if is_tty:
        _console.print("[bold]▶ Step 4/5: 재시도 매니페스트 갱신[/bold]")

    failed_video_ids: set[str] = {
        f.video_id
        for f in transcript_result.failures + fingerprint_result.failures
    }
    succeeded_video_ids: set[str] = {
        vid for vid in mp4_video_id_map.values() if vid not in failed_video_ids
    }
    all_failures = transcript_result.failures + fingerprint_result.failures
    manifest_path = work_root / channel_alias / "retry_pending.json"
    retry_manifest_delta = _update_retry_manifest(
        all_failures, succeeded_video_ids, manifest_path, audit_writer
    )

    if is_tty:
        _console.print(
            f"  [green]→[/green] 신규 추가 {retry_manifest_delta.added_count}, "
            f"해소 {retry_manifest_delta.resolved_count}, "
            f"잔여 {retry_manifest_delta.remaining_count}"
        )

    # ── Step 5: 영상 본체 정리 (--delete-source 지정 시만) ─────────────────
    cleanup_result = None
    if is_tty:
        if delete_source:
            _console.print("[bold]▶ Step 5/5: 영상 본체 정리[/bold]")
        else:
            _console.print(
                "[bold]▶ Step 5/5: 영상 본체 정리 "
                "[dim](--delete-source 미지정으로 skip)[/dim][/bold]"
            )

    if delete_source:
        from tube_scout.services.source_video_cleanup import (
            confirm_and_cleanup,
            present_failure_table,
        )
        present_failure_table(all_failures, console=_console, audit_writer=audit_writer)
        # SC-003: only successfully processed videos are deletion candidates
        candidates = [
            mp4_path for mp4_path, vid in mp4_video_id_map.items()
            if vid not in failed_video_ids
        ]
        # T-04: restrict unlink to archive root + channel symlink dir only
        _allowed_roots = [
            takeout_dir.resolve(),
            (work_root / channel_alias / "동영상").resolve(),
        ]
        cleanup_result = confirm_and_cleanup(
            candidates,
            prompt_io=prompt_io,
            audit_writer=audit_writer,
            allowed_roots=_allowed_roots,
        )

    # ── 최종 집계 ──────────────────────────────────────────────────────────
    completed_at = datetime.now(tz=UTC)
    total_elapsed = time.monotonic() - _t0

    audit_writer.append_row("ingest_orchestrator", {
        "video_id": "",
        "result": "success",
        "reason": "completed",
        "channel_alias": channel_alias,
        "elapsed_ms": int(total_elapsed * 1000),
        "timestamp": completed_at.isoformat(),
    })

    summary = UnifiedIngestSummary(
        channel_alias=channel_alias,
        ingest_result=ingest_result,
        transcript_result=transcript_result,
        fingerprint_result=fingerprint_result,
        cleanup_result=cleanup_result,
        retry_manifest_delta=retry_manifest_delta,
        total_elapsed_seconds=total_elapsed,
        started_at=started_at,
        completed_at=completed_at,
    )
    _print_summary_table(summary, console=_console)
    return summary
