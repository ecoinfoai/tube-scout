"""Spec 013 SC-002 + SC-010 — ASR throughput measurement on prod GPU pool.

This test is env-gated by ``TUBE_SCOUT_PERF_GPU_PROD``. The environment
variable MUST point at a v4 ContentDB file pre-populated with audio
queue rows (processing_status.stage='asr', status='collected',
caption_source IS NULL) and a matching audio cache directory containing
the .wav inputs that ``run_pool`` will transcribe.

The intent is to measure sustained throughput (videos/hour and average
seconds-per-minute-of-audio) of the ``prod-a6000-pool`` configuration
(2 workers × A6000, faster-whisper large-v3, float16) over a 30-minute
window. The measurement is appended to
``_workspace/measurement/asr_throughput_prod_phase2.md`` for SC-010
sign-off evidence.

When the env var is absent the test ``pytest.skip``s — CI and laptop
runs do not need the fixture. The file must still import-clean so
collection works everywhere.

Mark: ``@pytest.mark.slow``.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

PERF_GPU_PROD_ENV = "TUBE_SCOUT_PERF_GPU_PROD"
AUDIO_CACHE_ENV = "TUBE_SCOUT_PERF_AUDIO_CACHE"
TRANSCRIPTS_OUT_ENV = "TUBE_SCOUT_PERF_TRANSCRIPTS_OUT"
N_WORKERS_ENV = "TUBE_SCOUT_PERF_N_WORKERS"
DEVICE_INDICES_ENV = "TUBE_SCOUT_PERF_DEVICE_INDICES"
MODEL_SIZE_ENV = "TUBE_SCOUT_PERF_MODEL_SIZE"
COMPUTE_TYPE_ENV = "TUBE_SCOUT_PERF_COMPUTE_TYPE"
WINDOW_SECONDS_ENV = "TUBE_SCOUT_PERF_WINDOW_SECONDS"

MEASUREMENT_OUT = (
    Path(__file__).resolve().parents[2]
    / "_workspace"
    / "measurement"
    / "asr_throughput_prod_phase2.md"
)

_DEFAULT_WINDOW_SECONDS = 30 * 60  # 30 minutes (SC-010 evidence window)


def _resolve_db_path() -> Path:
    raw = os.environ.get(PERF_GPU_PROD_ENV)
    if not raw:
        pytest.skip(
            f"{PERF_GPU_PROD_ENV} unset — production GPU pool fixture "
            "required for SC-002/SC-010 ASR throughput evidence"
        )
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        pytest.fail(
            f"{PERF_GPU_PROD_ENV}={raw!r} does not exist; build the v4 "
            "ASR-queue fixture before running this perf test."
        )
    return path


def _resolve_dir_env(env: str, default_subdir: str, *, must_exist: bool) -> Path:
    raw = os.environ.get(env)
    if not raw:
        path = (
            Path(__file__).resolve().parents[2] / "_workspace" / default_subdir
        )
    else:
        path = Path(raw).expanduser().resolve()
    if must_exist and not path.exists():
        pytest.fail(
            f"{env}={path!r} does not exist; populate the directory before "
            "running this perf test."
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_device_indices(n_workers: int) -> list[int]:
    raw = os.environ.get(DEVICE_INDICES_ENV)
    if not raw:
        return list(range(n_workers))
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        return [int(p) for p in parts]
    except ValueError as exc:
        pytest.fail(
            f"{DEVICE_INDICES_ENV}={raw!r} must be a comma-separated list "
            f"of integer CUDA device indices (e.g. '0,1'). Parse error: {exc}"
        )


def _append_measurement(record: str) -> None:
    MEASUREMENT_OUT.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not MEASUREMENT_OUT.exists()
    with MEASUREMENT_OUT.open("a", encoding="utf-8") as fh:
        if header_needed:
            fh.write(
                "# spec 013 SC-002 + SC-010 — prod-a6000-pool ASR throughput\n\n"
                "Each entry is appended by "
                "`tests/perf/test_asr_throughput_prod_gpu.py`.\n\n"
                "| timestamp_utc | db_fixture | n_workers | device_indices | "
                "model_size | compute_type | window_seconds | processed | "
                "failed | skipped | videos_per_hour |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|\n"
            )
        fh.write(record)


@pytest.mark.slow
def test_sc002_sc010_asr_throughput_prod_gpu() -> None:
    """Measure sustained ASR throughput on the prod-a6000-pool config.

    Skips unless ``TUBE_SCOUT_PERF_GPU_PROD`` points at a v4 ContentDB.
    Does NOT assert a throughput budget — the budget is committed by
    the spec maintainer after enough runs accumulate (SC-002/SC-010
    wording). The measured throughput is appended to
    ``_workspace/measurement/asr_throughput_prod_phase2.md``.
    """
    fixture_db = _resolve_db_path()
    audio_cache_dir = _resolve_dir_env(
        AUDIO_CACHE_ENV, "perf_audio_cache", must_exist=True
    )
    transcripts_dir = _resolve_dir_env(
        TRANSCRIPTS_OUT_ENV, "perf_transcripts_out", must_exist=False
    )

    n_workers = int(os.environ.get(N_WORKERS_ENV, "2"))
    device_indices = _resolve_device_indices(n_workers)
    model_size = os.environ.get(MODEL_SIZE_ENV, "large-v3")
    compute_type = os.environ.get(COMPUTE_TYPE_ENV, "float16")
    window_seconds = int(
        os.environ.get(WINDOW_SECONDS_ENV, str(_DEFAULT_WINDOW_SECONDS))
    )
    if window_seconds <= 0:
        pytest.fail(
            f"{WINDOW_SECONDS_ENV}={window_seconds!r} must be a positive "
            "integer (seconds)."
        )

    from tube_scout.services.worker_pool import run_pool
    from tube_scout.storage.content_db import _ensure_v4

    _ensure_v4(fixture_db)

    start = time.monotonic()
    pool_result = run_pool(
        db_path=fixture_db,
        audio_cache_dir=audio_cache_dir,
        transcripts_dir=transcripts_dir,
        n_workers=n_workers,
        device_indices=device_indices,
        model_size=model_size,
        compute_type=compute_type,
    )
    elapsed = time.monotonic() - start

    measured_window = max(elapsed, 1.0)
    videos_per_hour = (
        (pool_result.total_processed / measured_window) * 3600.0
        if measured_window > 0
        else 0.0
    )

    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    record = (
        f"| {timestamp} | {fixture_db} | {n_workers} | "
        f"{','.join(str(d) for d in device_indices)} | {model_size} | "
        f"{compute_type} | {window_seconds} | {pool_result.total_processed} | "
        f"{pool_result.total_failed} | {pool_result.total_skipped} | "
        f"{videos_per_hour:.2f} |\n"
    )
    _append_measurement(record)

    assert pool_result.total_processed + pool_result.total_failed > 0, (
        "fixture queue produced zero work — ensure the v4 ContentDB has "
        "processing_status rows with status='collected' and "
        "caption_source IS NULL before running this perf test"
    )
    assert elapsed > 0.0
