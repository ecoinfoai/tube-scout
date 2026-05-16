# Phase 0 Research: unified_ingest 영구화 + 멱등 가드

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-05-16

## 0. Unknowns 점검

본 PATCH 는 spec 017 의 명확한 결함 3 건 (line 100/113/72) 에 대한 surgical fix 이고, `/speckit.clarify` 단계에서 5 개의 결정 (Q1~Q5) 이 모두 명시적 답으로 해소되었다. **NEEDS CLARIFICATION 항목 = 0**. 본 research 는 결정의 근거를 정리하는 deltadocument 다.

| Q | 결정 | 출처 |
|---|---|---|
| Q1 | `INSERT OR REPLACE` upsert | spec.md Clarifications, plan.md B-2 |
| Q2 | `--force` 는 전체 재처리 + retry_pending 자동 해소 | spec.md FR-018D, plan.md B-4 |
| Q3 | Rich Table — spec 017 의 5-row 표 보존 + 열 4 → 5 확장 (단계 / 처리 / skip / 실패 / 소요 시간), 자막 생성·음원 지문 행에 skip 정수, 다른 행은 `-` | spec.md FR-018F, SC-018-6 |
| Q4 | 처리 대상 0 개면 faster-whisper 모델 로딩 skip | spec.md FR-018E, SC-018-1 |
| Q5 | 점검 fail 영상은 영구화 + retry_pending 미등재 (분리 명령 동작 인계) | spec.md Edge cases, Assumptions |

## 1. 결정 — 표준 영구화 패턴 인용

### 1.1 자막 영구화 (FR-018A)

**Decision**: `tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")` + `_os.replace(tmp, dst)` 의 atomic write.

**Rationale**: spec 013 의 분리 명령 `collect transcripts` 가 동일 패턴을 `cli/collect.py:2268-2281` 에서 이미 사용 중. 부분 작성 흔적 (.tmp 잔재) 이 종료 시점에 남지 않음이 검증된 패턴이며 POSIX `rename(2)` 의 atomicity 보장에 의존한다. transcript json 의 schema (video_id / source / language / duration / segments / asr_quality_flags / fetched_at) 는 같은 위치의 코드에 정의되어 있고 본 PATCH 가 그대로 차용한다.

**Alternatives considered**:
- 단순 `open + write + close` 직접 쓰기 → 부분 작성 잔재 발생 가능, FR-018A 의 .tmp 0 개 조건 위반
- `pathlib.Path.write_text(json.dumps(...))` → atomicity 미보장, 동일한 부분 작성 위험
- SQLite 에 transcript text 영속 → schema migration 수반 + FR-018H schema 동치성 위반

### 1.2 지문 영구화 (FR-018B)

**Decision**: `INSERT OR REPLACE INTO audio_fingerprint(video_id, fingerprint, duration_seconds, fetched_at) VALUES (?, ?, ?, ?)` 단일 statement.

**Rationale**: `storage/content_db.py:insert_audio_fingerprint()` 가 이미 이 패턴으로 구현되어 있을 가능성이 높음 (`grep -rn "INSERT INTO audio_fingerprint\|INSERT OR REPLACE INTO audio_fingerprint"` 으로 implementation 확인 단계에서 검증). video_id PK 의 유일성을 SQL 수준에서 자동 보장하며 `--force` 재처리 시에도 별도 분기 없이 row 가 1 개로 유지된다 (SC-018-3 의 "row 수 정확히 1 개" 충족).

**Alternatives considered**:
- `UPDATE WHERE video_id=?` (없으면 INSERT) → 두 단계 SQL, 첫 호출에서 UPDATE 가 0 row affected 시 분기 처리 필요. 단일 SQL 패턴 대비 복잡도 증가.
- `DELETE WHERE video_id=?` + `INSERT` → 두 statement, transaction 경계 명시 필요. PK 의 ON CONFLICT REPLACE 와 의미상 동치이나 SQL 노이즈 증가.
- append-only (동일 video_id 의 multi-row 허용) → spec 013 의 PK 단일성 가정 위반, spec 011 reader 의 가정도 깨짐.

### 1.3 멱등 가드 (FR-018C)

**Decision**: 영상별·단계별 두 개의 독립 가드 — 자막: `(transcript_dir / f"{video_id}.json").exists()`, 지문: `SELECT 1 FROM audio_fingerprint WHERE video_id = ?`.

**Rationale**: spec 013 의 `collect_fingerprint_command` 가 cli/collect.py:1931-1952 에서 정확히 같은 SQL 가드를 사용. 자막 가드는 본 PATCH 의 신규 패턴이지만 transcript json 의 atomic write 가 부분 작성 잔재를 남기지 않으므로 단순 `Path.exists()` 만으로 충분하다 (.tmp 는 fnmatch 가 다르므로 자연스럽게 제외됨). 두 가드의 독립 평가는 부분 영구화 상태 (자막 있고 지문 없음 등) 를 자연스럽게 처리 (Edge case 명시).

**Alternatives considered**:
- 단일 결합 가드 (자막·지문 모두 영구화된 영상만 skip) → 부분 영구화 시 두 단계 모두 재처리하여 비효율, Edge case 의 "독립 평가" 결정과 충돌
- DB 의 별도 `processing_status` 컬럼으로 가드 → spec 013 schema 의 의도 (각 컬럼은 특정 처리 결과를 표현) 와 충돌, schema 변경 수반

### 1.4 `--force` 의미 (FR-018D)

**Decision**: `collect_ingest_command` 에 `--force` Typer 옵션 추가, 멱등 가드 두 개 모두 우회하고 archive 내 전체 영상 (이미 성공 + retry_pending 등재 실패) 재처리.

**Rationale**: spec 013 `collect_fingerprint_command` 의 `--force` 옵션 (cli/collect.py:1990-1994) 과 시그니처·의미 일관. retry_pending 자동 해소는 `services/retry_manifest.py` 의 기존 `resolve_successes` / `add_or_update_failures` 동작이 그대로 동작하므로 신규 코드 0.

### 1.5 처리 대상 사전 평가 + 모델 로드 skip (FR-018E)

**Decision**: 영상 루프 진입 전에 멱등 가드를 batch 평가 (자막 skip 대상 list + 지문 skip 대상 list 산출), 자막 처리 대상 = 0 일 때 `transcribe_audio` 가 호출되지 않으므로 `_load_model` (faster-whisper WhisperModel) 도 lazy load 로 자동 회피.

**Rationale**: `services/asr.py:62` 의 `_load_model` 이 `functools.lru_cache` 기반 lazy singleton — 첫 `transcribe_audio` 호출 시점에만 로드된다. 따라서 별도 분기 코드 없이 "transcribe_audio 자체를 0 번 호출" 만 보장하면 모델 로딩이 자연스럽게 skip 된다. SC-018-1 의 ≤ 2 초 목표는 (a) DB SELECT 1 회 × 영상 수 + (b) 파일 존재 체크 1 회 × 영상 수 + (c) Rich Table 출력 — 의 합으로 충족 가능 (9 영상 기준 약 50-200 ms 예상).

**Alternatives considered**:
- eager model load + 0 영상 시 unload → unload 자체가 GPU 메모리 해제로 수십 ms 추가, 의미 없음
- 모델 로드를 별도 함수로 wrap + 사전 평가 결과로 명시적 분기 → lazy lru_cache 가 이미 같은 효과 제공, 코드 추가만 발생

### 1.6 Rich Table 형식 (FR-018F) — spec 017 5-row 보존 + skip 열 추가

**Decision**: spec 017 의 기존 **5-row Rich Table** (적재 / 자막 생성 / 음원 지문 / 매니페스트 갱신 / 영상 정리) 를 **보존**하면서 열을 4 → **5 로 확장**: 신규 컬럼 셋 = (단계 / 처리 / **skip** / 실패 / 소요 시간). 자막 생성 행과 음원 지문 행의 skip 셀에는 정수 카운트 (`tr.skip_count` / `fr.skip_count`) 가 표시되고, 다른 세 행 (적재 / 매니페스트 갱신 / 영상 정리) 의 skip 셀은 의미가 없으므로 `-` 로 채워진다.

**Rationale**: spec 017 운영자가 익숙한 표 구조를 유지하면서 멱등 시각 신호 (skip 열) 만 surgical 하게 추가. archive 크기와 무관하게 표 행 수는 항상 5 — 자막 생성·음원 지문 행이 항상 존재하므로 운영자가 두 행의 skip 열만 보고 멱등 동작 여부를 인지 가능. spec 017 5-row 표를 폐기하고 별도 2-row 표를 새로 도입하는 안 (Phase 0 초기 검토안) 은 운영자 학습 비용과 출력 길이 증가를 발생시키므로 reject.

**Alternatives considered**:
- 별도 2-row 표 도입 (행 = 자막/지문) → spec 017 5-row 표와 병존 시 출력 길이 증가, 폐기 시 운영자 재학습 비용. reject.
- 행=영상 단위 → archive 크기에 표 크기가 비례 증가, 1 학과 9 영상 OK 이지만 22 학과 200+ 영상 시 가독성 폭락. reject.
- summary 텍스트 라인 2 개 → 시각적 align 안 됨, 정량 비교 어려움. reject.

## 2. 결정 — 신규 로직 0 (이미 존재하는 surface 인용)

### 2.1 ASR 정상성 점검 (`detect_quality_flags`)

**Discovery (Cross-Spec Boundary B-6 의 기반)**: `services/asr.py:173-197` 의 `detect_quality_flags()` 가 이미 6 종 flag (hallucination_repeat / vad_over_truncated / language_mismatch / short_segments_excess / silence_hallucination / compression_ratio_violations) 를 산출하고 있다. `transcribe_audio` 의 반환값 `TranscribeResult.asr_quality_flags` 안에 포함되어 호출자에게 노출.

**Decision**: 본 PATCH 는 신규 점검 로직을 추가하지 않는다. FR-018A 가 `transcribe_audio` 반환값을 transcript json 으로 영구화하는 시점에 `asr_quality_flags` 가 자동으로 함께 영속된다. 점검 fail 영상의 자동 재시도 도입도 본 PATCH 범위 밖 (분리 명령 동작 그대로 인계).

### 2.2 WAV 임시 파일 정리 (`WavLifecycle`)

**Discovery**: `services/audio_extract.py:72-104` 의 `WavLifecycle` context manager 가 `__exit__` 에서 무조건 `cleanup_wav` 호출. 결과 정상성과 무관하게 정리 보장.

**Decision**: 본 PATCH 는 `WavLifecycle` 자체를 손대지 않는다. 멱등 가드 도입 (FR-018E) 으로 자막·지문 둘 다 skip 인 영상은 `with WavLifecycle(...)` 진입 자체를 회피 → WAV 디코딩 0 회 (SC-005 강화). 디코딩이 발생한 영상은 기존 정리 동작 그대로 유지 (C-1 / SC-018-7).

### 2.3 영상 본체 (mp4) 정리 (`--delete-source`)

**Discovery**: `services/source_video_cleanup.py:confirm_and_cleanup` 와 `unified_ingest.py:416-437` 의 두 단계 prompt 흐름이 spec 017 에서 완성. 사용자 결정 (2026-05-16): "spec 017 에서 완성되어 있다면 spec 018 에서 다룰 필요 없음".

**Decision**: 본 PATCH 는 mp4 cleanup 흐름을 변경하지 않는다. 멱등 가드가 자막·지문 단계를 skip 해도 `--delete-source` 가 명시되면 영상 본체 정리는 그대로 발동된다 (이미 처리 완료된 영상이 삭제 대상으로 자연스럽게 합류).

## 3. 결정 — 회귀 안정성 (SC-018-7)

### 3.1 mock-only → real archive fixture (FR-018F)

**Discovery (spec 017 T013)**: 기존 `tests/integration/test_ingest_idempotent.py` 가 mock 환경 기반으로 작성되어 실제 transcript json 파일 mtime / DB row count 검증이 부재. 이로 인해 spec 017 의 SC-004 멱등 위반이 회귀 매트릭스에서 잡히지 않았다.

**Decision**: 본 PATCH 의 핵심 회귀 테스트 `test_ingest_idempotent.py` 를 (i) 1 학과 fixture archive (간호학과의 mini 버전 — 3 mp4) 를 `tests/fixtures/` 아래에 두고 (ii) 첫 호출 후 자막 json 파일 9 개의 mtime 기록 + DB row count = 9 검증 (iii) 두 번째 호출 후 wall clock ≤ 2 초 + mtime 변경 0 + DB row count = 9 유지 — 의 3 단계로 강화. mock 환경의 빠른 unit 회귀 (test_unified_ingest_*) 와 real archive 의 느린 integration 회귀를 분리.

**Alternatives considered**:
- 9 mp4 fixture 그대로 사용 → 매 CI run 마다 ASR ~14 분 소요, CI 비용 과다. 3 mp4 mini 로 축소.
- mock 만 유지 → 본 PATCH 의 동기인 SC-004 회귀를 잡지 못함. 명백히 reject.

### 3.2 spec 017 의 SC-001 / SC-005 / C-1 보존

**Decision**: 본 PATCH 는 ffprobe 메모이즈 (spec 017 FR-001/FR-002), 영상당 디코딩 1 회 (SC-005), 임시 WAV 즉시 정리 (C-1) 흐름을 모두 보존. 회귀는 spec 017 의 기존 integration 테스트 (`test_collect_ingest_e2e.py`, `test_ingest_partial_failure.py`, `test_ingest_retry_followup.py`) 가 그대로 GREEN 인지 검증 (SC-018-7).

## 4. 결정 — 운영자 quickstart 갱신 (FR-018G)

**Decision**: spec 017 의 `specs/017-takeout-unified-ingest/quickstart.md` §5 KNOWN LIMITATION 항목 (멱등 부분 실패 — 자막·지문 재처리) 을 본 PATCH 완료 시점에 spec 018 의 quickstart §X 에서 "RESOLVED in spec 018" 로 표기 + 새 운영자가 "두 번째 호출 ≤ 2 초" 를 직접 검증할 수 있는 walkthrough 1 단락 추가.

**Rationale**: FR-018G 의 acceptance 조건 — 신 운영자가 quickstart 만 읽고 멱등 동작을 인지. spec 017 quickstart §5 자체는 historical 기록으로 유지하되 본 PATCH 의 quickstart 가 보강·정정 책임을 진다.

## 5. 결정 — 22 학과 환산 검증 (SC-018-4)

**Decision**: 한 학과 (간호학과 9 mp4) 측정 + 선형 환산으로 충분. 22 학과 모두에 대한 실측을 본 PATCH 의 acceptance 조건으로 강제하지 않음 (Assumption 명시).

**Rationale**: 사용자 결정 (2026-05-16 clarify Q5 기본값). 22 학과 운영 자체는 별도의 운영 가이드 (`_workspace/` 아래 운영 절차 문서) 의 영역이며, 본 PATCH 의 acceptance 는 단일 학과 실측으로 SC-018-1/-2/-3 을 충족하면 SC-018-4 (환산 결과) 도 함께 만족하는 구조다.

## 6. 표준 패턴 인용 (참조 위치)

본 PATCH 의 모든 신규 코드는 기존 코드의 표준 패턴 인용으로 구성. 코드 위치 인용은 plan.md 의 Cross-Spec Boundaries 표 + 본 research 의 §1 에 모두 명시되어 있으므로 본 단락은 quick reference 만 둔다.

- 자막 영구화 패턴: `src/tube_scout/cli/collect.py:2249-2300` (process-audio 통합 모드의 ASR + atomic write)
- 지문 영구화 + 멱등 가드: `src/tube_scout/cli/collect.py:1931-1979` (collect_fingerprint_command)
- WAV context: `src/tube_scout/services/audio_extract.py:72-104` (`WavLifecycle`)
- ASR 정상성 평가: `src/tube_scout/services/asr.py:173-197` (`detect_quality_flags`)
- DB upsert helper: `src/tube_scout/storage/content_db.py` (`insert_audio_fingerprint`)
- retry_manifest: `src/tube_scout/services/retry_manifest.py` (`add_or_update_failures` / `resolve_successes` / `select_retry_targets`)

## 결론

NEEDS CLARIFICATION 항목 0 개. 신규 의존성 0 건. 신규 모듈 0 건. 신규 로직 = `services/unified_ingest.py` 내부 helper 2 개 (`_persist_transcript` / `_check_already_processed`) + CLI 옵션 1 개 (`--force`). 모든 표준 패턴이 spec 013 의 분리 명령에서 이미 검증된 코드 인용. Phase 1 (data-model + contracts + quickstart) 진입 가능.
