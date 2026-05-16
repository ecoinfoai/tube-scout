# Phase 1 Data Model: unified_ingest 영구화 + 멱등 가드

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-05-16

본 PATCH 는 **새 entity 0 개**, **새 SQLite 테이블 0 개**, **schema migration 0 건**. 모든 entity 는 spec 013 / spec 017 의 기존 정의를 그대로 보존하거나, 영구화 경로의 명시성을 강화하기 위한 표현형 entity (in-memory dataclass) 1 개를 새로 정의한다.

## 1. 영속 entity (디스크 / DB 에 저장됨)

### 1.1 Transcript Artifact

**정의**: 영상 한 개의 ASR 산출물. spec 013 의 `collect transcripts` 가 산출하는 transcript json 과 schema-for-schema 동치 (top-level 7 키 + asr_quality_flags 6 종 + segment 객체 키).

**위치**: `data/<alias>/02_analyze/transcripts/<video_id>.json` (atomic write 단위).

**Schema (JSON keys, 본 PATCH 가 강제)**:

| Key | Type | Source | Description |
|---|---|---|---|
| `video_id` | str | 입력 video_id | 11-char YouTube video ID |
| `source` | str | `TranscribeResult.caption_source_detail` | 예: `asr:faster-whisper:large-v3:int8_float16` |
| `language` | str | `TranscribeResult.language_detected` | 감지된 언어 코드 (예: `ko`) |
| `duration` | float | `TranscribeResult.duration` | 오디오 길이 (초) |
| `segments` | list[dict] | `TranscribeResult.segments` | segment 객체 list — 각 segment 는 `{start, end, text, compression_ratio, no_speech_prob}` 키 |
| `asr_quality_flags` | dict | `TranscribeResult.asr_quality_flags.model_dump()` | `AsrQualityFlags` 의 6 종 flag dict |
| `fetched_at` | str | now() ISO 8601 | atomic write 시점의 UTC ISO 8601 |

**asr_quality_flags 의 내부 schema** (spec 013 FR-018 의 정의 보존, `src/tube_scout/models/content.py:AsrQualityFlags`):

| Field | Type | Description |
|---|---|---|
| `hallucination_repeat` | bool | 3+ 연속 동일 segment (환각 반복) |
| `vad_over_truncated` | bool | VAD 가 과도하게 자름 (현재 항상 False, TODO) |
| `language_mismatch` | bool | 감지 언어 ≠ 기대 언어 |
| `short_segments_excess` | bool | 0.5s 미만 segment 가 30% 초과 |
| `silence_hallucination` | bool | 침묵 구간에 학습 잔재 패턴 발견 |
| `compression_ratio_violations` | int | 압축률 2.4 초과 segment 수 (count, not bool) |

**Atomic write 규약**: `tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")` 로 임시 파일 생성 → `os.fdopen` 으로 json dump → `os.replace(tmp, dst)` 로 atomic rename. 종료 시점에 `*.tmp` 잔재 0 개 (FR-018A).

**Lifecycle 상태**:

- `absent` — 파일 부재 (멱등 가드: 처리 대상)
- `present` — 파일 존재 (멱등 가드: skip, `--force` 시에만 재처리)
- `partial` (`*.tmp` 존재) — atomic write 실패 잔재. 가드 평가에서 `absent` 와 동치 (다음 atomic write 가 덮어쓰기). 본 PATCH 가 명시적 cleanup 을 별도로 두지 않음 (Edge case 명시).

### 1.2 Audio Fingerprint Row

**정의**: 영상 한 개의 chromaprint 지문. spec 013 의 `audio_fingerprint` 테이블 정의 그대로 보존.

**위치**: SQLite v4 의 `audio_fingerprint` 테이블 (alias 별 DB).

**Schema (테이블 컬럼, 변경 없음)**:

| Column | Type | Constraint | Source |
|---|---|---|---|
| `video_id` | TEXT | PK | 11-char YouTube video ID |
| `fingerprint` | BLOB | NOT NULL | chromaprint base64-decoded fingerprint bytes |
| `duration_seconds` | REAL | NOT NULL | chromaprint 측정 길이 |
| `fetched_at` | TEXT | NOT NULL | ISO 8601 UTC (atomic insert 시점) |

**Upsert 규약**: `INSERT OR REPLACE INTO audio_fingerprint(video_id, fingerprint, duration_seconds, fetched_at) VALUES (?, ?, ?, ?)`. video_id PK 단일성이 SQL 수준에서 자동 보장. `--force` 재처리 시에도 row 수가 정확히 1 개로 유지 (SC-018-3).

**Lifecycle 상태**:

- `absent` — `SELECT 1 FROM audio_fingerprint WHERE video_id=?` 결과 없음 (멱등 가드: 처리 대상)
- `present` — row 존재 (멱등 가드: skip)
- `partial` 상태 없음 (DB transaction commit 단위가 statement 1 개).

### 1.3 Retry Manifest (보존, 변경 없음)

**정의**: spec 017 의 `retry_pending.json` 매니페스트. 본 PATCH 는 schema 를 변경하지 않으며, 상호작용 규약만 확장한다.

**위치**: `data/<alias>/retry_pending.json`.

**Schema (보존)**: `RetryManifest { entries: list[RetryEntry { video_id, failed_stages, attempts, last_failure_reason, first_seen_at, last_attempted_at } ], updated_at: ISO 8601 }`.

**본 PATCH 의 상호작용 변화 (Q2 결정)**:

- 일반 호출 (no `--force`): 처리 대상 영상만이 매니페스트 갱신 대상. 멱등 skip 인 영상은 매니페스트와 무관.
- `--force` 호출: archive 내 **전체 영상** 이 처리 대상. 호출 종료 시점에 (a) 성공한 영상 → `resolve_successes()` 가 매니페스트에서 제거, (b) 새 실패 영상 → `add_or_update_failures()` 가 추가 또는 attempts 증가.

## 2. 비영속 entity (in-memory)

### 2.1 IdempotencyGuardResult (신규, in-memory dataclass)

**정의**: 영상별·단계별 멱등 가드 평가 결과. 본 PATCH 가 명시적으로 도입하는 표현형 entity (영속되지 않음, 단일 호출의 분기 결정용).

**위치**: `services/unified_ingest.py` 내부 `_check_already_processed()` 가 반환.

**Schema (in-memory)**:

| Field | Type | Description |
|---|---|---|
| `video_id` | str | 평가 대상 영상 ID |
| `transcript_skip` | bool | True = 자막 단계 skip (json 존재), False = 처리 대상 |
| `fingerprint_skip` | bool | True = 지문 단계 skip (DB row 존재), False = 처리 대상 |
| `wav_decode_skip` | bool | `transcript_skip` AND `fingerprint_skip` — 양쪽 skip 시 WAV 디코딩 자체 회피 (FR-018E) |

**평가 입력**:

- `video_id` (string)
- `transcript_dir` (Path) — 자막 표준 위치
- `db_path` (Path) — SQLite v4 DB
- `force: bool` — True 시 무조건 (False, False, False) 반환 (FR-018D)

**평가 규약** (force=False 일 때):

```python
transcript_skip = (transcript_dir / f"{video_id}.json").exists()
fingerprint_skip = bool(
    conn.execute(
        "SELECT 1 FROM audio_fingerprint WHERE video_id = ?",
        (video_id,),
    ).fetchone()
)
wav_decode_skip = transcript_skip and fingerprint_skip
```

### 2.2 TranscriptStageResult (보존, 컬럼 1 개 추가 검토)

**정의**: spec 017 의 `services/unified_ingest.py` 에서 정의된 자막 단계 결과 집계 모델.

**기존 필드** (보존): `success_count`, `failure_count`, `skipped_no_mp4_count`, `failures: list[FailureEntry]`, `elapsed_seconds`.

**본 PATCH 의 선택적 확장**: `skip_count: int` 추가 — 멱등 가드에 의해 skip 된 영상 수. Rich Table 의 "skip" 열 (FR-018F) 의 source. 만약 기존 `skipped_no_mp4_count` 와 의미가 충분히 분리되면 추가, 아니면 표현 layer 에서만 분기 처리.

**결정**: 컬럼 추가 (의미 분리: `skipped_no_mp4_count` = mp4 파일 부재, `skip_count` = 멱등 가드 skip). pydantic v2 모델이므로 default = 0 으로 backward compat 유지.

### 2.3 FingerprintStageResult (보존, 컬럼 1 개 추가 검토)

TranscriptStageResult 와 동일한 패턴으로 `skip_count: int` 추가. 의미 = 지문 단계 멱등 가드 skip 영상 수.

### 2.4 UnifiedIngestSummary (보존, 변경 없음)

상위 집계 모델은 본 PATCH 가 손대지 않음. `transcript_result.skip_count` / `fingerprint_result.skip_count` 가 추가됨으로써 자연스럽게 Rich Table layer 가 표시할 수 있게 됨.

## 3. Entity 관계도

```text
┌────────────────────────────────────────────────────────────────┐
│ collect ingest (1 alias 단위 호출)                              │
└───────────────────────┬────────────────────────────────────────┘
                        │
                        ▼
   ┌────────────────────────────────────────────────┐
   │ 영상 루프 (raw_mp4_map → retry-priority sort)    │
   └────────┬───────────────────────────────────────┘
            │  (each video_id)
            ▼
   ┌────────────────────────────────────────────────┐
   │ IdempotencyGuardResult                          │
   │   ─ transcript_skip (json exists?)              │
   │   ─ fingerprint_skip (DB row exists?)           │
   │   ─ wav_decode_skip (둘 다 skip?)               │
   └────────┬───────────────────────────────────────┘
            │
            ├─ wav_decode_skip = True → 영상 루프 continue (FR-018E)
            │
            └─ False → WavLifecycle context 진입 (B-3)
                       │
                       ├─ extract_wav_16k_mono (디코딩 1 회)
                       │
                       ├─ if not transcript_skip:
                       │     transcribe_audio → TranscribeResult
                       │     _persist_transcript (atomic write → Transcript Artifact)
                       │
                       └─ if not fingerprint_skip:
                             extract_chromaprint_fingerprint → (bytes, duration)
                             insert_audio_fingerprint (INSERT OR REPLACE → Audio Fingerprint Row)

      (영상 루프 종료 후)
            ▼
   ┌────────────────────────────────────────────────┐
   │ _update_retry_manifest (보존)                    │
   │   ─ failures: list[FailureEntry]                │
   │   ─ succeeded_video_ids: set[str]               │
   │   ─ Retry Manifest mutation                     │
   └────────────────────────────────────────────────┘
            ▼
   ┌────────────────────────────────────────────────┐
   │ _print_summary_table (Rich Table 보강)           │
   │   ─ 자막: 처리 / skip / 실패 / 소요             │
   │   ─ 지문: 처리 / skip / 실패 / 소요             │
   └────────────────────────────────────────────────┘
```

## 4. Validation Rules (FR 추적)

| Rule | FR | 검증 시점 |
|---|---|---|
| transcript json 의 7 키 모두 존재 | FR-018A, FR-018H | atomic write 직후 read-back 또는 reader 호출 |
| `asr_quality_flags` 가 6 종 flag 모두 포함 | FR-018A | transcript json 읽기 → AsrQualityFlags pydantic 검증 |
| `audio_fingerprint` row 의 video_id 단일성 | FR-018B | `SELECT COUNT(*) GROUP BY video_id` 모든 결과 = 1 |
| 자막 json 존재 ⇒ 자막 단계 skip | FR-018C | unit test (단일 video_id) |
| DB row 존재 ⇒ 지문 단계 skip | FR-018C | unit test (단일 video_id) |
| `--force` ⇒ 두 가드 모두 무시 | FR-018D | unit test |
| 두 단계 모두 skip ⇒ WAV 디코딩 0 회 | FR-018E | integration test (filesystem 검증) |
| Rich Table 5 행 × 5 열 (자막 생성·음원 지문 행의 skip 열에 정수, 다른 행은 `-`) | FR-018F | contract test (stdout 캡처 + 행 수 / 열 수 / skip 셀 정수 여부 assert) |
| spec 013 분리 명령 산출물과 schema-for-schema 동치 (키 집합) | FR-018H | contract test (json keys diff + DB column diff) |

## 5. 영향 받는 기존 entity (변경 없음 확인)

| Entity | 위치 | 변경 |
|---|---|---|
| `IngestResult` | spec 016 `services/takeout_ingest.py` | 없음 |
| `RetryManifest` / `RetryEntry` | spec 017 `services/retry_manifest.py` | 없음 (호출 입력 분포만 다름) |
| `SourceVideoCleanupResult` | spec 017 `services/source_video_cleanup.py` | 없음 |
| `FailureEntry` | spec 017 `models/content.py` | 없음 |
| `processing_status` 테이블 | spec 013 SQLite v4 | 없음 |
| `quality_results` 테이블 | spec 013 SQLite v4 | 없음 (본 PATCH 가 row 영속 도입 안 함 — Assumption 명시) |
| `comparison_results` 테이블 | spec 013 SQLite v4 | 없음 |
| `channel_metadata` / `video_metadata` | spec 013 SQLite v4 | 없음 |
| `channels.json` / `departments.json` | spec 003 / 016 | 없음 |
| `audit_writer.append_row("ingest_orchestrator", ...)` | spec 017 | reason 어휘에 `already_transcribed` / `already_fingerprinted` 2 개 추가 (B-5) |

## 결론

본 PATCH 의 data model 변화는 (1) 표현형 in-memory entity `IdempotencyGuardResult` 신규 1 개, (2) `TranscriptStageResult` / `FingerprintStageResult` 의 `skip_count` 필드 추가 (default 0, backward compat), (3) audit reason 어휘 확장 2 개 — 의 3 가지로 압축. SQLite schema migration 0 건, JSON schema 변경 0 건, 영속 entity 신규 0 건. Phase 1 의 contracts 작성으로 진행 가능.
