# Contract: services/worker_pool.py

**Module**: `src/tube_scout/services/worker_pool.py` (신규)
**Spec FR mapping**: FR-022 + C-5 (retry-failed semantics).
**Boundary**: B-2 (processing_status atomic claim), B-13 (모델 캐시).

---

## 함수 시그니처

```python
from pathlib import Path
from typing import Literal

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

    Single-process entry. For dual-GPU pool, the orchestrator spawns two
    separate Python processes (multiprocessing.Process), each calling this
    function with device_index=0 / =1 and CUDA_VISIBLE_DEVICES exported.

    Atomic claim (C-5):
        BEGIN IMMEDIATE;
        UPDATE processing_status
           SET status='asr_in_progress', updated_at=CURRENT_TIMESTAMP
         WHERE video_id = (
             SELECT video_id FROM processing_status
              WHERE status IN ('collected', 'asr_failed' if retry_failed else 'collected')
                AND caption_source IS NULL
              ORDER BY updated_at ASC
              LIMIT 1
         )
           AND status IN ('collected', 'asr_failed' if retry_failed else 'collected')
           AND caption_source IS NULL
        RETURNING video_id;
        COMMIT;

    Per-video lifecycle:
        1. Extract WAV (services/audio_extract.extract_wav_16k_mono).
        2. Run faster-whisper (services/asr.transcribe_audio with preset args).
        3. Write transcript JSON.
        4. UPDATE processing_status SET caption_source='whisper',
           caption_source_detail='asr:faster-whisper:...', status='collected',
           updated_at=NOW WHERE video_id = ?
        5. Auto-normalize (services/text_normalizer.normalize_transcript_json).
        6. Delete WAV (unless keep_audio).
        7. progress.update(video_id, ...).
        On exception:
           UPDATE processing_status SET status='asr_failed', error_message=...
           WHERE video_id = ?

    Termination:
        Loops until claim returns no row. Returns WorkerResult.

    Args:
        db_path: content_reuse.db (v4 권장).
        audio_cache_dir: WAV 추출 디렉터리.
        transcripts_dir: 자막 JSON 출력 디렉터리.
        device_index: CUDA 장치 인덱스 (multi-GPU pool 시).
        model_size, compute_type, language: faster-whisper 옵션.
        auto_normalize: True 시 자막 후 즉시 normalize.
        retry_failed: True 시 asr_failed row도 claim 대상.
        keep_audio: True 시 WAV 보존.
        progress: ProgressReporter (optional).

    Returns:
        WorkerResult — processed/failed 카운터.

    Raises:
        SQLiteError: DB 접근 실패.
        ImportError: faster-whisper 미설치 (actionable message).
    """

def run_pool(
    db_path: Path,
    audio_cache_dir: Path,
    transcripts_dir: Path,
    *,
    n_workers: int = 2,
    device_indices: list[int] = [0, 1],
    model_size: str = "large-v3",
    compute_type: str = "float16",
    **kwargs,
) -> PoolResult:
    """Spawn N independent worker processes (prod-a6000-pool).

    Each worker is a separate multiprocessing.Process with
    CUDA_VISIBLE_DEVICES exported to its assigned GPU index.

    Args:
        n_workers: 워커 개수 (기본 2).
        device_indices: 각 워커가 사용할 CUDA 장치 인덱스 list (len == n_workers).
        Others: forwarded to run_asr_worker.

    Returns:
        PoolResult — 각 워커의 WorkerResult 통합 카운터.
    """

class WorkerResult(BaseModel):
    worker_id: int
    device_index: int
    processed: int
    failed: int
    skipped: int
    elapsed_seconds: float

class PoolResult(BaseModel):
    n_workers: int
    workers: list[WorkerResult]
    total_processed: int
    total_failed: int
    total_skipped: int
    elapsed_seconds: float
```

---

## SQLite WAL mode 강제

```python
def _ensure_wal_mode(db_path: Path) -> None:
    """Enable WAL journal mode for concurrent worker access.

    Idempotent. SQLite WAL allows readers + 1 writer simultaneously.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")  # 30s wait on lock contention
```

`run_asr_worker` 진입 시 1회 호출.

---

## Multi-GPU 프로세스 격리

```python
def _spawn_worker(worker_id: int, device_index: int, **kwargs) -> multiprocessing.Process:
    """Spawn a worker process with CUDA_VISIBLE_DEVICES exported."""
    def target():
        os.environ["CUDA_VISIBLE_DEVICES"] = str(device_index)
        # faster-whisper sees only this single GPU as cuda:0 inside the process.
        # Override device_index back to 0 since CUDA_VISIBLE_DEVICES remaps.
        kwargs["device_index"] = 0
        return run_asr_worker(**kwargs)
    proc = multiprocessing.Process(target=target, name=f"asr-worker-{worker_id}")
    proc.start()
    return proc
```

**중요**: `CUDA_VISIBLE_DEVICES=N` 환경에서 프로세스 내부의 cuda 장치 인덱스는 0으로 remap됨 — faster-whisper 호출 시 `device_index=0` 으로 강제.

---

## --retry-failed 의 의미 (C-5)

`retry_failed=True` 인자는 claim predicate를 다음으로 확장:

```sql
WHERE status IN ('collected', 'asr_failed')
  AND caption_source IS NULL
```

별도 reset 단계 없음. `asr_failed` → `asr_in_progress` 직접 atomic 전이. 동시에 두 워커가 같은 row를 retry해도 SQLite 트랜잭션이 단일 워커만 성공시킨다(WHERE 절의 status 재확인).

---

## 멱등성 & race safety

- 두 워커가 동시에 claim 시도 → BEGIN IMMEDIATE의 reserved lock이 순차화 → 한 워커가 UPDATE 성공, 다른 워커는 RETURNING이 비어 다음 시도로 진행.
- 워커가 처리 중 충돌 → row는 `asr_in_progress` 상태로 남음. 운영자가 stale 상태를 `--retry-failed` 로 회복 가능 (단 stale 감지는 본 spec scope OUT — 별도 idea로 모니터링 도구 추가).
- KeyboardInterrupt: 현재 영상의 `processing_status='asr_failed'` 으로 표시 + WAV 삭제 후 종료.

---

## 테스트 진입점

- `tests/contract/test_worker_pool_contract.py`:
  - `test_run_asr_worker_signature_matches_contract`
  - `test_run_pool_returns_pool_result_with_n_workers_entries`
- `tests/unit/test_atomic_claim.py`:
  - `test_atomic_claim_returns_one_row_per_call`
  - `test_atomic_claim_updates_status_to_in_progress`
  - `test_atomic_claim_retry_failed_extends_predicate`
  - `test_concurrent_claim_two_threads_succeeds_for_one_only` (threading 모의)
- `tests/integration/test_worker_pool_dual_gpu.py` (`@pytest.mark.slow`):
  - Mock CUDA_VISIBLE_DEVICES + fake faster-whisper → 두 프로세스 spawn 후 SQLite row 처리 분배 검증.
- `tests/integration/test_retry_failed_direct_transition.py`:
  - `asr_failed` row 1개 + `--retry-failed=True` → 워커가 `asr_in_progress` 로 직접 전이 후 처리 검증 (별도 reset 단계 없음, C-5 검증).
