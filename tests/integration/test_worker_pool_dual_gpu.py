"""T056 RED — worker_pool dual-GPU integration test (mock).

Verifies that run_pool spawns N workers, each gets a distinct device_index,
and PoolResult aggregates correctly. Does NOT spawn real processes or touch
real GPUs: monkeypatches run_asr_worker.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.integration


def _make_worker_result(worker_id: int, device_index: int, processed: int = 3) -> object:
    from tube_scout.services.worker_pool import WorkerResult

    return WorkerResult(
        worker_id=worker_id,
        device_index=device_index,
        processed=processed,
        failed=0,
        skipped=0,
        elapsed_seconds=1.0,
    )


def test_run_pool_returns_pool_result(tmp_path: Path) -> None:
    """run_pool with 2 mocked workers returns PoolResult with n_workers=2."""
    from tube_scout.services.worker_pool import PoolResult, run_pool

    db = tmp_path / "content_reuse.db"
    db.touch()
    audio_dir = tmp_path / "audio"
    transcript_dir = tmp_path / "transcripts"

    mock_result_0 = _make_worker_result(0, 0, processed=3)
    mock_result_1 = _make_worker_result(1, 1, processed=2)

    with patch(
        "tube_scout.services.worker_pool.run_asr_worker",
        side_effect=[mock_result_0, mock_result_1],
    ):
        result = run_pool(
            db_path=db,
            audio_cache_dir=audio_dir,
            transcripts_dir=transcript_dir,
            n_workers=2,
            device_indices=[0, 1],
        )

    assert isinstance(result, PoolResult)
    assert result.n_workers == 2


def test_run_pool_aggregates_totals(tmp_path: Path) -> None:
    """run_pool total_processed = sum of worker processed counts (2 workers × 5 = 10)."""
    from tube_scout.services.worker_pool import run_pool

    db = tmp_path / "content_reuse.db"
    db.touch()

    # Each worker gets the same mocked result (5 processed); total = 10
    with patch(
        "tube_scout.services.worker_pool.run_asr_worker",
        return_value=_make_worker_result(0, 0, processed=5),
    ):
        result = run_pool(
            db_path=db,
            audio_cache_dir=tmp_path,
            transcripts_dir=tmp_path,
            n_workers=2,
            device_indices=[0, 1],
        )

    assert result.total_processed == 10
    assert result.total_failed == 0
    assert result.total_skipped == 0


def test_run_pool_workers_list_length_matches_n_workers(tmp_path: Path) -> None:
    """run_pool workers list has exactly n_workers entries."""
    from tube_scout.services.worker_pool import run_pool

    db = tmp_path / "content_reuse.db"
    db.touch()

    with patch(
        "tube_scout.services.worker_pool.run_asr_worker",
        side_effect=[_make_worker_result(i, i) for i in range(2)],
    ):
        result = run_pool(
            db_path=db,
            audio_cache_dir=tmp_path,
            transcripts_dir=tmp_path,
            n_workers=2,
            device_indices=[0, 1],
        )

    assert len(result.workers) == 2


def test_run_pool_single_worker(tmp_path: Path) -> None:
    """run_pool with n_workers=1 works correctly."""
    from tube_scout.services.worker_pool import run_pool

    db = tmp_path / "content_reuse.db"
    db.touch()

    with patch(
        "tube_scout.services.worker_pool.run_asr_worker",
        return_value=_make_worker_result(0, 0, processed=7),
    ):
        result = run_pool(
            db_path=db,
            audio_cache_dir=tmp_path,
            transcripts_dir=tmp_path,
            n_workers=1,
            device_indices=[0],
        )

    assert result.n_workers == 1
    assert result.total_processed == 7
