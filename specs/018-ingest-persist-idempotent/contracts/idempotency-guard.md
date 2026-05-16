# Contract: Idempotency Guard (영상별 멱등 가드)

**Spec**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md) | **FR**: 018C, 018E
**Surface**: `src/tube_scout/services/unified_ingest.py::_check_already_processed` (신규 helper)

## 1. 입력 / 출력

### 1.1 Signature

```python
def _check_already_processed(
    video_id: str,
    transcript_dir: Path,
    db_path: Path,
    *,
    force: bool = False,
) -> IdempotencyGuardResult: ...
```

### 1.2 Return type

```python
@dataclass(frozen=True)
class IdempotencyGuardResult:
    video_id: str
    transcript_skip: bool
    fingerprint_skip: bool
    wav_decode_skip: bool  # transcript_skip AND fingerprint_skip
```

## 2. 평가 규약

### 2.1 `force=True` 분기

```python
if force:
    return IdempotencyGuardResult(
        video_id=video_id,
        transcript_skip=False,
        fingerprint_skip=False,
        wav_decode_skip=False,
    )
```

`force=True` 일 때는 디스크·DB 조회 자체를 건너뛴다 (성능 + 명시성).

### 2.2 `force=False` 분기

자막 가드 (필수):

```python
transcript_skip = (transcript_dir / f"{video_id}.json").exists()
```

지문 가드 (필수, SQLite):

```python
with sqlite3.connect(db_path) as conn:
    fingerprint_skip = bool(
        conn.execute(
            "SELECT 1 FROM audio_fingerprint WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    )
```

결합:

```python
wav_decode_skip = transcript_skip and fingerprint_skip
```

## 3. 독립 평가 보장 (FR-018C)

두 가드는 **반드시 독립적으로 평가**되어야 한다. 부분 영구화 상태 (자막 json 있고 DB row 없음 등) 에 대해 한 단계만 skip 하고 다른 단계는 처리한다. 즉:

| transcript_skip | fingerprint_skip | wav_decode_skip | 영상 처리 동작 |
|---|---|---|---|
| False | False | False | WAV 디코딩 1 회 + 자막 + 지문 |
| True | False | False | WAV 디코딩 1 회 + 지문만 |
| False | True | False | WAV 디코딩 1 회 + 자막만 |
| True | True | **True** | WAV 디코딩 **0 회**, 영상 루프 continue (FR-018E) |

## 4. SQL 가드 contract

### 4.1 사용 statement

```sql
SELECT 1 FROM audio_fingerprint WHERE video_id = ? LIMIT 1;
```

- `EXPLAIN QUERY PLAN` 결과는 PK index 사용 (audio_fingerprint.video_id PK). 영상당 평가 비용 O(log n).
- 9 영상 archive 기준 약 < 1 ms.

### 4.2 connection 재사용

영상 루프 진입 전에 sqlite3.Connection 1 개를 열어 모든 영상에 대해 재사용. row 평가가 끝나면 `conn.close()`. 멱등 hot path 의 ≤ 2 초 목표 (SC-018-1) 보장.

### 4.3 transaction 의도

가드 평가는 read-only — auto-commit 모드면 충분. 동일 connection 내에서 처리 후 `INSERT OR REPLACE` 가 실행될 수 있으나 SQLite 의 기본 transaction 동작 (`BEGIN DEFERRED`) 에 의해 자동 처리됨.

## 5. 자막 가드 contract

### 5.1 검사 대상

`(transcript_dir / f"{video_id}.json").exists()` 만 평가. `*.tmp` 파일은 자연스럽게 제외 (파일명 패턴 불일치). 디렉토리 자체가 부재면 자동으로 False.

### 5.2 디렉토리 생성 의무

`_run_transcript_and_fingerprint` 진입 시점에 `transcript_dir.mkdir(parents=True, exist_ok=True)` 호출. 가드 평가는 mkdir 후 시점에 일어나므로 항상 디렉토리 존재 보장.

## 6. WAV 디코딩 skip (FR-018E)

`wav_decode_skip = True` 인 영상에 대해 영상 루프는:

```python
for mp4_path_str, video_id in mp4_video_id_map.items():
    guard = _check_already_processed(
        video_id, transcript_dir, db_path, force=force
    )
    if guard.wav_decode_skip:
        # audit + skip count 증가
        audit_writer.append_row("ingest_orchestrator", {
            "video_id": video_id,
            "result": "skip",
            "reason": "already_transcribed_and_fingerprinted",
            ...
        })
        transcript_skip_count += 1
        fingerprint_skip_count += 1
        continue

    # WAV 디코딩 1 회 (B-3)
    with WavLifecycle(mp4_path, wav_dir, video_id) as wav_path:
        extract_wav_16k_mono(mp4_path, wav_path)
        if not guard.transcript_skip:
            ...
        if not guard.fingerprint_skip:
            ...
```

## 7. 모델 로딩 skip 의 자연스러운 보장 (FR-018E 의 절반)

`faster_whisper` 모델은 `services/asr.py:62` 의 `@functools.lru_cache` 데코레이터가 보유하는 lazy singleton. `transcribe_audio` 가 한 번도 호출되지 않으면 `_load_model` 도 호출되지 않으며 GPU 메모리 점유 0, 모델 init 시간 0.

본 PATCH 는 별도 분기 코드 없이 "wav_decode_skip 영상 + transcript_skip 영상 에서 transcribe_audio 호출 0" 만 보장하면 모델 로딩이 자연스럽게 회피된다. 영상 전체가 자막 skip 인 hot path 에서는 모델 로딩 자체가 발생하지 않아 SC-018-1 의 ≤ 2 초 안정 달성.

## 8. 감사 기록 contract

| 영상 처리 결과 | audit row reason |
|---|---|
| `wav_decode_skip = True` (둘 다 skip) | `already_transcribed_and_fingerprinted` (또는 각 단계 별 2 row) |
| 자막 skip + 지문 처리 성공 | 자막: `already_transcribed`, 지문: `captured` |
| 자막 처리 성공 + 지문 skip | 자막: `asr_transcribed`, 지문: `already_fingerprinted` |
| 둘 다 처리 성공 | 자막: `asr_transcribed`, 지문: `captured` |
| 한 단계 실패 | 해당 단계의 fail reason (분리 명령과 동일 어휘) |

표현 선택지 (단일 row vs 단계 별 2 row) 는 implementation 단계에서 결정 (spec 013 분리 명령 패턴 인계 = 단계 별 1 row).

## 9. Acceptance scenarios

- **GS-1**: video_id 가 transcript json 있고 DB row 도 있음 → `IdempotencyGuardResult(transcript_skip=True, fingerprint_skip=True, wav_decode_skip=True)` 반환, WAV 디코딩 0 회 검증.
- **GS-2**: video_id 가 transcript json 있고 DB row 없음 → `(True, False, False)` 반환, WAV 디코딩 1 회 + 지문만 처리.
- **GS-3**: 둘 다 없음 + `force=True` → `(False, False, False)`, 전체 처리.
- **GS-4**: 둘 다 있음 + `force=True` → `(False, False, False)`, 전체 재처리 (가드 우회).
- **GS-5**: 디렉토리 자체가 부재 → mkdir 후 `(False, False, False)`, 정상 처리.
