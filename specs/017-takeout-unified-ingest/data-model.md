# Phase 1 Data Model: Takeout 통합 적재와 운영 효율화

**Branch**: `017-takeout-unified-ingest` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

본 문서는 spec 017 이 새로 도입하거나 기존 entity 에 필드를 추가하는 데이터 단위를 정리한다. 본 spec 은 SQLite v4 스키마를 변경하지 않으며 (boundary B-4 보존), 모든 신규 데이터는 (1) JSON atomic write 파일 또는 (2) 메모리상 pydantic 모델 (직렬화 후 출력) 로 처리한다.

---

## E-1: UnifiedIngestSummary (신규, 메모리상 pydantic 모델)

통합 명령 (`collect ingest`) 의 단일 호출 결과를 표현하는 데이터 클래스. 5 단계 (적재·자막·지문·삭제·재시도 매니페스트 갱신) 의 결과를 한 단위로 묶는다.

### Fields

| 필드 | 타입 | 의미 |
|---|---|---|
| `channel_alias` | `str` | 처리한 학과 alias (예: `nursing`) |
| `ingest_result` | `IngestResult` | spec 016 의 적재 결과 (boundary B-7 보존, 그대로 포함) |
| `transcript_result` | `TranscriptStageResult` | 자막 단계 결과 (E-2) |
| `fingerprint_result` | `FingerprintStageResult` | 지문 단계 결과 (E-3) |
| `cleanup_result` | `CleanupResult \| None` | 영상 삭제 단계 결과 (E-4). `--delete-source` 미지정 시 `None` |
| `retry_manifest_delta` | `RetryManifestDelta` | 재시도 매니페스트 갱신 결과 (E-6) |
| `total_elapsed_seconds` | `float` | 통합 명령 전체 wall-clock 시간 |
| `started_at` | `datetime` | UTC 시작 시각 |
| `completed_at` | `datetime` | UTC 종료 시각 |

### Validation

- `total_elapsed_seconds >= ingest_result.elapsed_seconds` (적재 단계가 전체에 포함)
- `started_at < completed_at`
- `cleanup_result is None` if `--delete-source` 옵션이 지정되지 않은 경우 (FR-011)

### Output / Serialization

CLI 종료 시 Rich Table 5 행 (단계별) + 요약 1 행 으로 운영자에게 표시. JSON 직렬화는 디버깅 / 통합 테스트 용도로만 사용 (운영자 워크플로우에 JSON 출력은 포함하지 않음).

---

## E-2: TranscriptStageResult (신규, 메모리상 pydantic 모델)

자막 생성 단계의 결과를 표현.

### Fields

| 필드 | 타입 | 의미 |
|---|---|---|
| `success_count` | `int` | 자막 생성 성공 영상 수 |
| `failure_count` | `int` | 자막 생성 실패 영상 수 |
| `skipped_no_mp4_count` | `int` | mp4 본체 부재로 자동 skip 된 영상 수 (FR-008) |
| `failures` | `list[FailureEntry]` | 실패한 영상의 상세 목록 (E-5) |
| `elapsed_seconds` | `float` | 자막 단계 wall-clock 시간 |

### Validation

- `success_count + failure_count + skipped_no_mp4_count` 가 자막 단계 진입 시점의 후보 영상 수와 같음
- `len(failures) == failure_count`

---

## E-3: FingerprintStageResult (신규, 메모리상 pydantic 모델)

음원 지문 추출 단계의 결과. 구조는 E-2 와 대칭.

### Fields

| 필드 | 타입 | 의미 |
|---|---|---|
| `success_count` | `int` | 지문 추출 성공 영상 수 |
| `failure_count` | `int` | 지문 추출 실패 영상 수 |
| `skipped_no_mp4_count` | `int` | mp4 부재 skip 영상 수 |
| `failures` | `list[FailureEntry]` | 실패 영상 상세 목록 |
| `elapsed_seconds` | `float` | 지문 단계 wall-clock 시간 |

### Validation

E-2 와 동일.

---

## E-4: CleanupResult (신규, 메모리상 pydantic 모델)

영상 삭제 단계 (`--delete-source` 옵션 + 두 단계 prompt) 의 결과.

### Fields

| 필드 | 타입 | 의미 |
|---|---|---|
| `presented_failure_count` | `int` | 첫 번째 prompt 의 처리 실패 영상 표에 표시된 행 수 |
| `deletion_candidate_count` | `int` | 두 번째 prompt 의 삭제 후보 영상 수 (분석 단계 모두 성공) |
| `operator_response` | `Literal['yes', 'no', 'timeout', 'interrupted']` | 두 번째 prompt 의 운영자 응답 |
| `deleted_count` | `int` | 실제 삭제된 mp4 파일 수 |
| `failed_to_delete_count` | `int` | 삭제 시도 중 실패한 파일 수 (file lock 등) |
| `reclaimed_bytes` | `int` | 회수된 디스크 용량 (byte) |
| `elapsed_seconds` | `float` | 삭제 단계 wall-clock 시간 |

### Validation

- `operator_response == 'yes'` 인 경우만 `deleted_count > 0` 또는 `failed_to_delete_count > 0` 가능. 다른 경우는 모두 0.
- `deleted_count + failed_to_delete_count <= deletion_candidate_count`
- `reclaimed_bytes >= 0`

### State Transitions

```
[entry]
   ↓
presented_failure_count = len(failures)
   ↓
[show failure table to operator]
   ↓
deletion_candidate_count = len(all_successful_videos)
   ↓
[prompt for yes/no]
   ├─ yes      → unlink each candidate → deleted_count + reclaimed_bytes
   ├─ no       → operator_response = 'no', deleted_count = 0
   ├─ timeout  → operator_response = 'timeout', deleted_count = 0
   └─ Ctrl+C   → operator_response = 'interrupted', deleted_count = 0
```

---

## E-5: FailureEntry (신규, 메모리상 pydantic 모델)

자막 또는 지문 단계의 실패 영상 1 건을 표현.

### Fields

| 필드 | 타입 | 의미 |
|---|---|---|
| `video_id` | `str` | YouTube video_id |
| `title` | `str` | 영상 제목 (spec 016 의 `동영상 제목(원본)`) |
| `failed_stage` | `Literal['transcript', 'fingerprint']` | 실패 단계 |
| `failure_reason` | `str` | 실패 사유 (예: `model_loading_failed`, `audio_decode_failed`, `chromaprint_timeout`) |
| `attempted_at` | `datetime` | UTC 시도 시각 |

### Validation

- `video_id` 는 SQLite `video_metadata.video_id` 와 일치 (외래키 의미적)
- `failure_reason` 은 사전 정의된 어휘 (audit 로그의 `reason` 컬럼과 통일)

---

## E-6: RetryManifestDelta (신규, 메모리상 pydantic 모델)

본 통합 명령 호출 1 회로 인한 재시도 매니페스트 파일의 변경 요약.

### Fields

| 필드 | 타입 | 의미 |
|---|---|---|
| `added_count` | `int` | 본 호출에서 매니페스트에 새로 추가된 실패 영상 수 |
| `resolved_count` | `int` | 본 호출에서 매니페스트에서 성공 처리 후 제거된 영상 수 |
| `remaining_count` | `int` | 본 호출 종료 시점에 매니페스트에 남은 영상 수 |
| `manifest_path` | `Path` | 매니페스트 파일 절대경로 |

### Validation

- `remaining_count >= 0`
- `manifest_path.parent` 가 alias 의 작업 디렉토리 (`data/<alias>/`) 와 일치

---

## E-7: RetryManifest (신규, JSON atomic write 파일)

`data/<alias>/retry_pending.json` 의 실제 파일 schema. spec 017 의 영속화 데이터 entity 중 유일하게 디스크에 저장됨.

### File Path

`data/<alias>/retry_pending.json`

### Schema (JSON Schema-like)

```json
{
  "schema_version": 1,
  "alias": "nursing",
  "updated_at": "2026-05-16T08:43:42+09:00",
  "entries": [
    {
      "video_id": "abc123def45",
      "title": "1주차 1차시 (간호학과)",
      "failed_stage": "transcript",
      "failure_reason": "model_loading_failed",
      "last_attempt_at": "2026-05-16T08:43:42+09:00",
      "attempt_count": 1
    }
  ]
}
```

### Fields

| 필드 | 타입 | 의미 |
|---|---|---|
| `schema_version` | `int` | 매니페스트 스키마 버전 (현재 `1`) |
| `alias` | `str` | 학과 alias. boundary B-9 와 일치 |
| `updated_at` | `string (ISO 8601)` | 마지막 갱신 시각 (KST 권장) |
| `entries` | `list[RetryEntry]` | 재시도 대상 영상 row 목록 |

### Entry (RetryEntry) Fields

| 필드 | 타입 | 의미 |
|---|---|---|
| `video_id` | `str` | SQLite `video_metadata.video_id` 와 일치 |
| `title` | `str` | 영상 제목 (운영자 식별용) |
| `failed_stage` | `Literal['transcript', 'fingerprint']` | 마지막 실패 단계 |
| `failure_reason` | `str` | 마지막 실패 사유 |
| `last_attempt_at` | `string (ISO 8601)` | 마지막 시도 시각 |
| `attempt_count` | `int (>= 1)` | 누적 시도 횟수. N 회 초과 시 운영자가 수동 점검 |

### State Transitions

```
[새 실패 발생]
   ↓
entries 에 video_id 부재 → append (attempt_count=1)
entries 에 video_id 존재 → attempt_count += 1, last_attempt_at 갱신, failed_stage/failure_reason 갱신

[다음 통합 명령에서 성공 처리]
   ↓
entries 에서 해당 video_id row 제거 (resolved)

[파일이 비어 있음]
   ↓
entries == [] 로 유지 (파일 자체는 보존, schema_version + updated_at 만 갱신)
```

### Validation

- `schema_version` 이 알려진 버전과 불일치하면 명시적 에러로 fail-fast (Principle II)
- `alias` 가 alias 등록부에 부재하면 명시적 에러
- 한 매니페스트의 `entries` 는 동일 alias 의 영상만 포함 (alias 별 격리)

### Atomic Write

`_write_json_atomic()` 헬퍼 (spec 013 / spec 016 와 동일 패턴) 사용. tmp 파일 → fsync → rename. 0600 권장 (학과 데이터의 privacy 보존).

---

## E-8: AuditLogRow (변경, 기존 entity 확장)

spec 013 / spec 016 의 `data/<alias>/01_collect/takeout_ingest_audit.csv` 에 신규 stage 두 가지를 추가한다. 기존 컬럼 셋과 append-only 보존 (boundary B-5).

### 기존 컬럼 (보존)

`stage, video_id, result, reason, mp4_filename, match_confidence, score, timestamp, raw_value, elapsed_ms` (spec 016 의 FR-023 컬럼 셋)

### 신규 stage 어휘 (FR-017)

| stage | 의미 | 신규 reason 어휘 |
|---|---|---|
| `ingest_orchestrator` | 통합 명령 진입/종료 | `started`, `completed`, `aborted_by_user`, `failed_intermediate_stage` |
| `source_video_cleanup` | 영상 삭제 단계 | `presented_failures`, `confirmed_yes`, `confirmed_no`, `timeout`, `interrupted`, `deleted`, `delete_failed_locked`, `delete_failed_io` |

### Backward Compatibility

기존 stage `takeout_ingest` 의 row 형식은 변경 없음. spec 013 / spec 016 의 audit 분석 도구가 본 spec 의 신규 row 를 무시해도 정상 작동 (forward compatible).

---

## E-9: MP4DurationCache (신규, 함수-local 메모이즈)

`evidence_score.py::score_mp4_candidates` 안의 dict 캐시. 영속화 되지 않음.

### Structure

```python
duration_cache: dict[str, float | None] = {}
# key: str(mp4_path.resolve())
# value: _probe_duration_via_ffprobe() 의 반환값
```

### Lifecycle

`score_mp4_candidates` 함수 시작 시 빈 dict 생성, 함수 종료 시 자동 소멸 (Python GC).

### Validation

캐시 key 는 절대경로 + resolve() 후 문자열이어야 함 (symlink resolved 보장, mp4 가 같은 파일을 가리키는 다른 경로로 호출되어도 같은 캐시 hit).

---

## 데이터 흐름 (요약)

```
[운영자]
   │
   │  collect ingest --channel nursing [--delete-source]
   ▼
[CLI collect_ingest_command]
   │
   ▼
[services/unified_ingest.py::ingest_unified()]
   │
   ├─ Step 1: services/takeout_ingest.py::ingest_takeout()   →   IngestResult (E-7 보존)
   │     │
   │     └─ services/evidence_score.py::score_mp4_candidates()
   │            └─ MP4DurationCache (E-9) 활성 — ffprobe 1회/mp4
   │
   ├─ Step 2: WavLifecycle 컨텍스트 (spec 013 boundary B-1)
   │     ├─ services/asr.py::transcribe_audio()             →   TranscriptStageResult (E-2)
   │     └─ services/audio_fingerprint.py::extract_...()    →   FingerprintStageResult (E-3)
   │
   ├─ Step 3: services/retry_manifest.py::update_manifest()
   │     ├─ FailureEntry (E-5) 누적
   │     └─ RetryManifest (E-7) 파일 갱신                   →   RetryManifestDelta (E-6)
   │
   ├─ Step 4: --delete-source 옵션 있을 때만
   │     ├─ services/source_video_cleanup.py::present_failure_table()
   │     └─ services/source_video_cleanup.py::confirm_and_cleanup()
   │            └─ CleanupResult (E-4)
   │
   └─ 최종 집계: UnifiedIngestSummary (E-1)
         │
         ▼
   [Rich Table 운영자 출력]
         │
         ▼
   [감사 CSV row append (E-8)]
```

---

## Backward Compatibility 보장

본 data-model 의 신규 entity 는 모두 spec 013 / spec 016 의 기존 데이터 단위에 추가되는 형태이며, 기존 entity (channel_metadata, video_metadata, processing_status, quality_results, comparison_results, IngestResult) 의 필드 / 시그니처 / 컬럼 셋은 변경되지 않는다 (Cross-Spec Boundary B-4 + B-7 보존).

기존 분리 명령 (`collect takeout`, `collect transcripts`, `collect fingerprint`, etc.) 호출 시에는 본 spec 의 신규 entity (UnifiedIngestSummary, RetryManifest, etc.) 가 생성되지 않으며, 기존 행동을 그대로 유지한다.
