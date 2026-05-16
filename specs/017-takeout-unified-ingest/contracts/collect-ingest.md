# Contract: `tube-scout collect ingest`

**Spec**: [spec.md](../spec.md) — FR-005, FR-006, FR-008, FR-009, FR-010, FR-016
**Plan**: [plan.md](../plan.md) — boundary B-6, B-7, B-9

본 contract 는 신규 통합 명령 `collect ingest` 의 입력·출력·종료 코드 매트릭스를 정의한다. 본 명령은 spec 016 의 `collect takeout` + spec 013 의 자막·지문 흐름을 단일 호출로 묶고, `--delete-source` 옵션 지정 시에만 영상 본체 삭제 단계로 진입한다.

## CLI 시그니처

```
tube-scout collect ingest
    --takeout-dir PATH
    --channel ALIAS
    [--delete-source]
    [--data-dir PATH]
    [--db-path PATH]
    [--dry-run]
    [--copy]
```

### 옵션

| 옵션 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `--takeout-dir` | path | required | Takeout 압축 해제 루트 (archive root 또는 `Takeout/` 폴더 자체. spec 016 FR-001 후반부의 자동 탐색 흐름 그대로) |
| `--channel` | str | required | 학과 alias (`channels.json` 또는 `departments.json` 에 등록된 상태여야 함) |
| `--delete-source` | flag | False | 분석 단계 종료 후 영상 본체 삭제 단계로 진입할지 여부 (FR-011) |
| `--data-dir` | path | `./data` | 학과 작업 디렉토리의 루트 |
| `--db-path` | path | `<data-dir>/content_reuse.db` | SQLite v4 데이터베이스 경로 |
| `--dry-run` | flag | False | 적재 단계만 측정 모드로 실행 (DB write 금지, 자막+지문+삭제 모두 skip) |
| `--copy` | flag | False | mp4 본체를 symlink 가 아닌 복사로 처리 (spec 016 의 기존 옵션 보존) |

## 동작 흐름

```
[입력 검증]
   ├─ alias 가 등록부 union 에 없으면 → exit 1
   ├─ alias 가 두 등록부 비정합 (FR-015 spec 016) → exit 1
   ├─ takeout_dir 부재 → exit 1
   └─ db_path 부모 디렉토리 자동 생성

[Step 1: 적재] services/takeout_ingest.py::ingest_takeout()
   ├─ csv 파싱 + SQLite 적재 + mp4 symlink/copy + audit row 누적
   └─ 결과: IngestResult (boundary B-7 보존)

[Step 2: --dry-run 인 경우 즉시 종료]
   ├─ UnifiedIngestSummary 부분 출력
   └─ exit 0

[Step 3: 자막 + 지문] services/unified_ingest.py 의 WavLifecycle 루프
   ├─ mp4 본체가 매핑된 영상 (high/medium) 만 대상
   ├─ 각 mp4 → 임시 WAV 1회 추출 → 자막 + 지문 동시 처리 → WAV 자동 삭제
   ├─ 실패 영상 → FailureEntry 누적
   └─ 결과: TranscriptStageResult + FingerprintStageResult

[Step 4: 재시도 매니페스트 갱신] services/retry_manifest.py
   ├─ 누적된 FailureEntry → retry_pending.json append/update
   ├─ 이번 호출에서 성공 처리된 기존 entry 는 제거
   └─ 결과: RetryManifestDelta

[Step 5: --delete-source 인 경우만]
   ├─ services/source_video_cleanup.py::present_failure_table(failures)
   │     └─ 처리 실패 영상 표를 Rich Table 로 출력 (응답 받지 않음)
   ├─ services/source_video_cleanup.py::confirm_and_cleanup(candidates)
   │     ├─ 두 번째 prompt: "Delete N source mp4 files? (y/N)"
   │     └─ yes → unlink, no/timeout/interrupted → 보존
   └─ 결과: CleanupResult

[최종 출력]
   ├─ Rich Table: 단계별 (적재·자막·지문·삭제·매니페스트) 소요 시간 + 카운트
   └─ exit 0
```

## 종료 코드 매트릭스

| 종료 코드 | 의미 | 발생 조건 |
|---|---|---|
| `0` | 성공 | 통합 명령이 정상 종료. 부분 실패 (자막/지문 일부 실패) 가 있어도 exit 0 (FailureEntry 와 retry 매니페스트로 처리) |
| `1` | 입력 오류 / 적재 실패 | alias 미등록, alias 비정합, takeout_dir 부재, csv 헤더 오류, SQLite 마이그레이션 실패 등 |
| `2` | (예약) Deprecation | 본 spec 에서는 사용하지 않음. spec 016 의 `--source youtube` deprecation 흐름과 어휘 일관 유지 위해 예약 |

## 출력 형식

### stdout (정상 종료 시)

```
▶ Step 1/5: Takeout 적재
  → 영상 2554, mp4 매핑 9 high, 소요 17s

▶ Step 2/5: 자막 생성 (faster-whisper)
  → 성공 9, 실패 0, mp4 부재 skip 2545, 소요 N분 N초

▶ Step 3/5: 음원 지문 추출 (chromaprint)
  → 성공 9, 실패 0, mp4 부재 skip 2545, 소요 N분 N초

▶ Step 4/5: 재시도 매니페스트 갱신
  → 신규 추가 0, 해소 0, 잔여 0

▶ Step 5/5: 영상 본체 정리 (--delete-source 미지정으로 skip)

┌────────────────────┬───────────┬──────────┬──────────┐
│ 단계               │ 성공      │ 실패     │ 소요 시간 │
├────────────────────┼───────────┼──────────┼──────────┤
│ 적재               │ 2554      │ 0        │ 17s      │
│ 자막 생성          │ 9         │ 0        │ N분 N초   │
│ 음원 지문          │ 9         │ 0        │ N분 N초   │
│ 매니페스트 갱신    │ 0 추가    │ 0 해소   │ <1s      │
│ 영상 정리          │ skip      │ -        │ -        │
└────────────────────┴───────────┴──────────┴──────────┘

✓ 통합 명령 완료 (alias=nursing, 총 소요 N분 N초)
```

### stdout (`--delete-source` 지정 + 부분 실패 시)

```
... (Step 1~4 동일)

▶ Step 5/5: 영상 본체 정리

[처리 실패 영상 — 자동 보존됨]
┌──────────────┬─────────────────────────┬──────────┬─────────────────────────┐
│ video_id     │ 영상 제목                │ 실패 단계 │ 실패 사유                │
├──────────────┼─────────────────────────┼──────────┼─────────────────────────┤
│ abc123       │ 5-1 임경민 간호연구...    │ asr      │ model_loading_failed    │
└──────────────┴─────────────────────────┴──────────┴─────────────────────────┘

[삭제 후보 — 모든 분석 단계 성공한 영상]
- archive 의 mp4 본체: 8 개 (총 8.9 GB)
- data/nursing/동영상/ 의 symlink: 8 개

Delete 8 source mp4 files? (y/N): _
```

운영자 응답 후:

```
✓ 영상 삭제 완료: 8 개 (회수 용량 8.9 GB)
  - archive mp4 unlink 8
  - symlink 정리 8
  - 처리 실패 1 개는 보존 + retry_pending.json 에 정리
```

### stderr

운영자 노출 한글 메시지는 stdout. 디버깅 / 오류는 stderr 로 분리하여 (Constitution Principle II) Korean 한 줄 + English 한 줄 형식 검토. 단 본 spec 은 새 stderr 어휘를 도입하지 않으며 spec 016 의 어휘를 따른다.

## Acceptance Matrix

| 시나리오 | 입력 | 기대 출력 | 기대 종료 코드 |
|---|---|---|---|
| 정상 통합 명령 | `--channel nursing --takeout-dir <간호학과 archive>` | 5 단계 표 출력, 매니페스트 갱신, exit 0 | 0 |
| `--delete-source` 정상 yes | `--channel nursing ... --delete-source` + 운영자 `y` | 두 단계 prompt 후 unlink + CleanupResult | 0 |
| `--delete-source` no | `--channel nursing ... --delete-source` + 운영자 `n` | 두 단계 prompt 후 영상 보존 + audit `confirmed_no` | 0 |
| alias 미등록 | `--channel unknown_dept ...` | stderr 명시 메시지 + exit 1 | 1 |
| alias 비정합 (channels.json vs departments.json) | spec 016 의 mismatch 시나리오 | stderr `alias mismatch` 메시지 + exit 1 | 1 |
| takeout_dir 부재 | `--takeout-dir /nonexistent` | stderr 명시 메시지 + exit 1 | 1 |
| `--dry-run` | `--channel nursing ... --dry-run` | 적재 단계만 측정 + Rich Table 출력 + exit 0 (DB write 0건) | 0 |
| 부분 실패 + `--delete-source` | 자막 1개 실패 + 운영자 `y` | 첫 번째 prompt 에 실패 1개 표시, 두 번째 prompt 의 삭제 후보 N-1 | 0 |
| 멱등 2회차 | 같은 archive 두 번째 호출 | `new=0`, 자막/지문 재생성 0, 매니페스트 변화 0, exit 0 | 0 |

## 기존 명령과의 관계 (Backward Compat)

본 명령은 기존 분리 명령 (`collect takeout`, `collect process-audio`, `collect transcripts`, `collect fingerprint`) 의 호출 표면과 행동을 변경하지 않는다. 운영자가 기존 명령을 그대로 호출하면 spec 013 / spec 016 시점의 행동을 그대로 받는다. quickstart 의 권장 흐름만 본 통합 명령으로 일원화된다.
