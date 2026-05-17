"""Contract tests — worker_pool service signatures (spec 013 T048 RED).

FR-022 + C-5: run_asr_worker, run_pool, WorkerResult, PoolResult.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

import inspect
from pathlib import Path

# ---------------------------------------------------------------------------
# T048-1: run_asr_worker signature matches contract
# ---------------------------------------------------------------------------

def test_run_asr_worker_signature_matches_contract() -> None:
    """run_asr_worker must have the exact parameter set from the contract."""
    from tube_scout.services.worker_pool import run_asr_worker

    sig = inspect.signature(run_asr_worker)
    params = sig.parameters

    required_params = [
        "db_path",
        "audio_cache_dir",
        "transcripts_dir",
        "device_index",
        "model_size",
        "compute_type",
        "language",
        "auto_normalize",
        "retry_failed",
        "keep_audio",
        "progress",
    ]

    for name in required_params:
        assert name in params, f"Parameter '{name}' missing from run_asr_worker signature"

    # Verify keyword-only defaults
    assert params["model_size"].default == "large-v3"
    assert params["compute_type"].default == "float16"
    assert params["language"].default == "ko"
    assert params["auto_normalize"].default is True
    assert params["retry_failed"].default is False
    assert params["keep_audio"].default is False
    assert params["progress"].default is None


# ---------------------------------------------------------------------------
# T048-2: run_pool returns PoolResult with n_workers WorkerResult entries
# ---------------------------------------------------------------------------

def test_run_pool_returns_pool_result_with_n_workers_entries(
    tmp_path: Path,
) -> None:
    """run_pool returns PoolResult with workers list of length n_workers."""
    from unittest.mock import patch

    from tube_scout.services.worker_pool import PoolResult, WorkerResult, run_pool

    db_path = tmp_path / "test.db"
    audio_dir = tmp_path / "audio"
    transcripts_dir = tmp_path / "transcripts"
    audio_dir.mkdir()
    transcripts_dir.mkdir()

    # Mock run_asr_worker to return a WorkerResult without actually running
    mock_worker_result = WorkerResult(
        worker_id=0,
        device_index=0,
        processed=0,
        failed=0,
        skipped=0,
        elapsed_seconds=0.1,
    )

    with patch(
        "tube_scout.services.worker_pool.run_asr_worker",
        return_value=mock_worker_result,
    ):
        result = run_pool(
            db_path=db_path,
            audio_cache_dir=audio_dir,
            transcripts_dir=transcripts_dir,
            n_workers=2,
            device_indices=[0, 1],
        )

    assert isinstance(result, PoolResult), f"run_pool must return PoolResult, got {type(result)}"
    assert result.n_workers == 2, f"PoolResult.n_workers must be 2, got {result.n_workers}"
    assert len(result.workers) == 2, (
        f"PoolResult.workers must have 2 entries, got {len(result.workers)}"
    )
    for w in result.workers:
        assert isinstance(w, WorkerResult)
