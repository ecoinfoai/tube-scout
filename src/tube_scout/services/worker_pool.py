"""Dual-GPU ASR worker pool with SQLite atomic claim (spec 013 FR-022 + C-5)."""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from tube_scout.services.progress_reporter import ProgressReporter

_logger = logging.getLogger(__name__)


class WorkerResult(BaseModel):
    """Result summary for a single ASR worker process."""

    worker_id: int
    device_index: int
    processed: int
    failed: int
    skipped: int
    elapsed_seconds: float


class PoolResult(BaseModel):
    """Aggregated result from all worker processes in a pool run."""

    n_workers: int
    workers: list[WorkerResult]
    total_processed: int
    total_failed: int
    total_skipped: int
    elapsed_seconds: float


def _ensure_wal_mode(db_path: Path) -> None:
    """Enable WAL journal mode for concurrent worker access.

    Args:
        db_path: SQLite database path.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")


def _resolve_device_and_compute_type(compute_type: str) -> tuple[str, str]:
    """Resolve ASR device + compute_type for the current host.

    Honors ``TUBE_SCOUT_ASR_DEVICE`` env override (``cuda`` or ``cpu``).
    Otherwise auto-detects: presence of ``nvidia-smi`` and a non-empty
    ``CUDA_VISIBLE_DEVICES`` => ``cuda``; else ``cpu``. When CPU is
    selected, ``float16`` is silently downgraded to ``int8`` because
    CTranslate2 does not support float16 on CPU.

    Args:
        compute_type: Requested compute type (e.g. ``float16``, ``int8``).

    Returns:
        Tuple of ``(device, compute_type)``. ``device`` is one of
        ``"cuda"`` or ``"cpu"``.
    """
    import shutil

    explicit = os.environ.get("TUBE_SCOUT_ASR_DEVICE")
    if explicit in ("cuda", "cpu"):
        device = explicit
    elif (
        shutil.which("nvidia-smi") is None
        or os.environ.get("CUDA_VISIBLE_DEVICES") == ""
    ):
        device = "cpu"
    else:
        device = "cuda"

    if device == "cpu" and compute_type == "float16":
        compute_type = "int8"
    return device, compute_type


_MIN_SQLITE_VERSION: tuple[int, int, int] = (3, 35, 0)


def _require_sqlite_returning() -> None:
    """Raise ``RuntimeError`` if the runtime SQLite is too old for RETURNING.

    SQLite ``RETURNING`` (used by :func:`_atomic_claim`) requires
    SQLite >= 3.35. NixOS pins the runtime SQLite via
    ``commonBuildInputs.sqlite`` in ``flake.nix`` (audit v3 F-1). If a
    user enters a non-flake shell or a system Python with an older
    SQLite, the worker pool would otherwise raise an opaque
    ``sqlite3.OperationalError: near "RETURNING": syntax error``.
    """
    if sqlite3.sqlite_version_info < _MIN_SQLITE_VERSION:
        required = ".".join(str(n) for n in _MIN_SQLITE_VERSION)
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} is too old for worker_pool "
            f"atomic claim (requires SQLite >= {required} for RETURNING). "
            "Re-enter the nix devShell (`nix develop` or `direnv reload`) "
            "to pick up the pinned sqlite from flake.nix."
        )


def _atomic_claim(db_path: Path, *, retry_failed: bool = False) -> str | None:
    """Atomically claim one unclaimed row from processing_status.

    Uses BEGIN IMMEDIATE to serialize concurrent workers. Claims oldest
    unclaimed 'collected' row (or 'asr_failed' if retry_failed=True).

    Args:
        db_path: SQLite database path.
        retry_failed: If True, also claim rows with status='asr_failed' (C-5).

    Returns:
        video_id of claimed row, or None if queue is empty.

    Raises:
        RuntimeError: SQLite runtime is older than 3.35 (RETURNING
            unsupported). audit v3 F-18 / ADV-45.
    """
    _require_sqlite_returning()

    # Parameterize the status filter so the SQL stays free of user-
    # influenced f-string fragments (audit v3 F-18 / SEC-2). Two
    # placeholders are enough because the worker pool only ever
    # considers at most two statuses ('collected' [, 'asr_failed']).
    if retry_failed:
        status_values: tuple[str, ...] = ("collected", "asr_failed")
    else:
        status_values = ("collected",)
    placeholders = ",".join("?" * len(status_values))

    sql = f"""
    UPDATE processing_status
       SET status = 'asr_in_progress',
           updated_at = datetime('now')
     WHERE video_id = (
         SELECT video_id FROM processing_status
          WHERE status IN ({placeholders})
            AND caption_source IS NULL
          ORDER BY updated_at ASC
          LIMIT 1
     )
       AND status IN ({placeholders})
       AND caption_source IS NULL
    RETURNING video_id;
    """

    with sqlite3.connect(db_path, isolation_level=None) as conn:
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("BEGIN IMMEDIATE;")
        row = conn.execute(sql, status_values + status_values).fetchone()
        conn.execute("COMMIT;")

    return row[0] if row else None


def run_asr_worker(
    db_path: Path,
    audio_cache_dir: Path,
    transcripts_dir: Path,
    *,
    device_index: int,
    model_size: str = "large-v3",
    compute_type: str = "float16",
    language: str = "ko",
    auto_normalize: bool = True,
    retry_failed: bool = False,
    keep_audio: bool = False,
    progress: ProgressReporter | None = None,
) -> WorkerResult:
    """Single ASR worker — claims rows from processing_status and processes them.

    Args:
        db_path: content_reuse.db path (v4 recommended).
        audio_cache_dir: Directory for WAV extraction.
        transcripts_dir: Directory for transcript JSON output.
        device_index: CUDA device index for this worker.
        model_size: Whisper model size.
        compute_type: Quantization type.
        language: Forced transcription language.
        auto_normalize: Normalize transcript immediately after ASR.
        retry_failed: Claim asr_failed rows too (C-5).
        keep_audio: Preserve WAV after processing.
        progress: Optional progress reporter.

    Returns:
        WorkerResult with processed/failed/skipped counts.

    Raises:
        ImportError: faster-whisper not installed (actionable message).
    """
    import datetime
    import json

    from tube_scout.services.asr import transcribe_audio
    from tube_scout.services.audio_extract import WavLifecycle
    from tube_scout.services.text_normalizer import normalize_transcript_json

    _ensure_wal_mode(db_path)
    audio_cache_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    failed = 0
    skipped = 0
    t_start = time.monotonic()
    n = 0

    while True:
        video_id = _atomic_claim(db_path, retry_failed=retry_failed)
        if video_id is None:
            break

        n += 1
        mp4_path = _resolve_mp4_path(db_path, video_id)
        if mp4_path is None:
            skipped += 1
            _update_status(db_path, video_id, "asr_failed", error_message="mp4_path missing")
            continue

        transcript_path = transcripts_dir / f"{video_id}.json"
        ts = datetime.datetime.now(tz=datetime.UTC).isoformat()

        device, resolved_compute_type = _resolve_device_and_compute_type(compute_type)

        try:
            with WavLifecycle(mp4_path, audio_cache_dir, video_id, keep=keep_audio) as wav_path:
                from tube_scout.services.audio_extract import extract_wav_16k_mono
                extract_wav_16k_mono(mp4_path, wav_path, force=True)

                result = transcribe_audio(
                    wav_path,
                    model_size=model_size,
                    compute_type=resolved_compute_type,
                    device=device,
                    device_index=device_index if device == "cuda" else 0,
                    language=language,
                )

            transcript = {
                "video_id": video_id,
                "source": "whisper",
                "language": result.language_detected,
                "fetched_at": ts,
                "segments": result.segments,
                "asr_quality_flags": result.asr_quality_flags.model_dump(),
                "caption_source_detail": result.caption_source_detail,
            }

            import tempfile
            tmp_fd, tmp_name = tempfile.mkstemp(
                dir=transcripts_dir, suffix=".tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(transcript, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, transcript_path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise

            _update_status(
                db_path, video_id, "collected",
                caption_source="whisper",
                caption_source_detail=result.caption_source_detail,
            )

            if auto_normalize:
                normalized_dir = transcripts_dir.parent / "transcripts_normalized"
                normalized_dir.mkdir(parents=True, exist_ok=True)
                normalize_transcript_json(
                    transcript_path,
                    normalized_dir / f"{video_id}.json",
                    force=False,
                )

            processed += 1

        except Exception as exc:
            failed += 1
            _logger.exception(
                "ASR failed for %s (worker pid=%d)", video_id, os.getpid()
            )
            _update_status(
                db_path, video_id, "asr_failed",
                error_message=str(exc)[:500],
            )

        if progress is not None:
            progress.update(video_id, n)

    return WorkerResult(
        worker_id=os.getpid(),
        device_index=device_index,
        processed=processed,
        failed=failed,
        skipped=skipped,
        elapsed_seconds=time.monotonic() - t_start,
    )


def _resolve_mp4_path(db_path: Path, video_id: str) -> Path | None:
    """Look up mp4_relative_path for video_id from video_metadata.

    Returns ``None`` if the lookup fails (e.g. missing row or DB locked)
    so the caller can decide whether to skip the row, mark it
    asr_failed, or retry later. Emits a logger.warning so the lookup
    failure is not silent (audit v3 F-22 / LOG-2).
    """
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT vm.mp4_relative_path, cm.channel_alias"
                " FROM video_metadata vm"
                " JOIN channel_metadata cm ON vm.channel_id = cm.channel_id"
                " WHERE vm.video_id = ?",
                (video_id,),
            ).fetchone()
        if row and row[0]:
            data_root = db_path.parent.parent
            return data_root / row[1] / row[0]
    except Exception as exc:
        _logger.warning("mp4 path lookup failed for %s: %s", video_id, exc)
    return None


def _update_status(
    db_path: Path,
    video_id: str,
    status: str,
    *,
    error_message: str | None = None,
    caption_source: str | None = None,
    caption_source_detail: str | None = None,
) -> None:
    """Update processing_status row for video_id.

    Args:
        db_path: SQLite database path.
        video_id: Row to update.
        status: New ``status`` value.
        error_message: When provided, written to ``error_message``.
        caption_source: When provided, written to ``caption_source``.
        caption_source_detail: When provided, written to
            ``caption_source_detail`` (e.g.
            ``"asr:faster-whisper:large-v3:int8_float16"``). Previously
            accepted but silently dropped — audit v3 F-22 / SEC-3.
    """
    sets = ["status = ?", "updated_at = datetime('now')"]
    values: list[Any] = [status]

    if error_message is not None:
        sets.append("error_message = ?")
        values.append(error_message)
    if caption_source is not None:
        sets.append("caption_source = ?")
        values.append(caption_source)
    if caption_source_detail is not None:
        sets.append("caption_source_detail = ?")
        values.append(caption_source_detail)

    values.append(video_id)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE processing_status SET {', '.join(sets)} WHERE video_id = ?",
            values,
        )


def run_pool(
    db_path: Path,
    audio_cache_dir: Path,
    transcripts_dir: Path,
    *,
    n_workers: int = 2,
    device_indices: list[int] | None = None,
    model_size: str = "large-v3",
    compute_type: str = "float16",
    **kwargs: Any,
) -> PoolResult:
    """Spawn N independent worker processes (prod-a6000-pool).

    Args:
        db_path: content_reuse.db path.
        audio_cache_dir: WAV extraction directory.
        transcripts_dir: Transcript JSON output directory.
        n_workers: Number of worker processes.
        device_indices: CUDA device index per worker (default: [0, 1, ...]).
        model_size: Whisper model size forwarded to workers.
        compute_type: Quantization type forwarded to workers.
        **kwargs: Additional kwargs forwarded to run_asr_worker.

    Returns:
        PoolResult aggregating all worker results.
    """
    if device_indices is None:
        device_indices = list(range(n_workers))

    t_start = time.monotonic()
    worker_results: list[WorkerResult] = []

    result_queue: multiprocessing.Queue = multiprocessing.Queue()

    def _worker_target(worker_id: int, dev_idx: int) -> None:
        # Restore the default SIGINT handler in the child so Ctrl+C in
        # the parent terminates the worker promptly instead of being
        # swallowed by an inherited handler (audit v3 F-22 / ADV-52).
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        # Drop any parent-inherited lru_cache slot so the child
        # initializes faster-whisper against its own GPU context;
        # otherwise a fork-copied cache holding the parent's CUDA
        # context can cause OOM on first transcribe (F-22 / ADV-42).
        try:
            from tube_scout.services.asr import _load_model
            _load_model.cache_clear()
        except Exception as exc:
            _logger.debug("worker cache_clear skipped: %s", exc)
        os.environ["CUDA_VISIBLE_DEVICES"] = str(dev_idx)
        result = run_asr_worker(
            db_path=db_path,
            audio_cache_dir=audio_cache_dir,
            transcripts_dir=transcripts_dir,
            device_index=0,
            model_size=model_size,
            compute_type=compute_type,
            **kwargs,
        )
        result_queue.put(result)

    processes: list[multiprocessing.Process] = []
    for i, dev_idx in enumerate(device_indices[:n_workers]):
        p = multiprocessing.Process(
            target=_worker_target,
            args=(i, dev_idx),
            name=f"asr-worker-{i}",
        )
        p.start()
        processes.append(p)

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        # Parent received Ctrl+C; politely terminate every worker, then
        # escalate to kill if any refuse to exit. Without this the
        # children would linger holding GPU VRAM (audit v3 F-22 /
        # ADV-52).
        _logger.warning(
            "run_pool: SIGINT received, terminating %d worker(s)", len(processes)
        )
        for p in processes:
            if p.is_alive():
                p.terminate()
        for p in processes:
            p.join(timeout=5)
        for p in processes:
            if p.is_alive():
                p.kill()
                p.join()
        raise

    while not result_queue.empty():
        worker_results.append(result_queue.get_nowait())

    elapsed = time.monotonic() - t_start
    return PoolResult(
        n_workers=n_workers,
        workers=worker_results,
        total_processed=sum(w.processed for w in worker_results),
        total_failed=sum(w.failed for w in worker_results),
        total_skipped=sum(w.skipped for w in worker_results),
        elapsed_seconds=elapsed,
    )
