---
description: "Task list for spec 017 — Takeout 통합 적재와 운영 효율화"
---

# Tasks: Takeout 통합 적재와 운영 효율화

**Input**: Design documents from `/home/kjeong/localgit/tube-scout/specs/017-takeout-unified-ingest/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: MANDATORY for this spec — Constitution Principle I (TDD, NON-NEGOTIABLE). 모든 user story phase 에서 RED → GREEN → REFACTOR 순서 강제. 모든 [P] RED task 는 실제로 failing 임을 단말에서 확인 후 GREEN 진입.

**Organization**: spec.md 의 4 user story (US1 P1 통합 흐름 / US2 P1 적재 효율화 / US3 P2 영상 삭제 + 재시도 / US4 P3 운영 baseline) 별 phase + Setup + Foundational + Polish.

## Format: `[TaskID] [P?] [Story?] Description with file path`

- **[P]**: 같은 phase 안에서 다른 파일을 건드리므로 병렬 실행 가능
- **[US1]~[US4]**: spec.md 의 user story 1~4 에 매핑
- 모든 경로는 repo root `/home/kjeong/localgit/tube-scout/` 기준 상대경로
- TDD: 각 user story 의 RED (테스트) 작업이 GREEN (구현) 보다 먼저 배치되며, RED task 는 반드시 failing 으로 확인 후 GREEN 진입

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 환경 동기화 + 효율화 전 baseline 측정 + 버전 bump. 신규 PyPI 의존성 0 건이므로 환경 변경은 최소.

- [x] T001 devShell 진입 + `uv sync --extra asr --extra dev` 동기화 확인 (faster-whisper, CTranslate2, pytest 모두 spec 016 환경 그대로)
- [x] T002 `pyproject.toml` 의 `version` 을 `0.5.1` → `0.6.0.dev0` 으로 bump (R-7 결정에 따른 MINOR pre-release suffix)
- [x] T003 효율화 전 baseline 측정 — `tube-scout collect takeout --takeout-dir data/takeout-20260511T130817Z-3-001 --channel nursing --dry-run` 의 elapsed_seconds 1 회 기록 (R-6). 측정값을 `_workspace/spec017_baseline_before_memoize.md` 에 저장. 약 17 분 baseline 보존 — 효율화 후 비교 기준.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 모든 user story 가 의존하는 공통 변경. pydantic 모델 + audit_writer stage 어휘 확장. 본 phase 완료 전에는 어떤 user story task 도 진행 불가.

**⚠️ CRITICAL**: 본 phase 의 T004~T005 가 모두 GREEN 이 되어야 US1~US4 진입 가능.

- [x] T004 [P] `src/tube_scout/models/content.py` 에 pydantic 모델 **7 개** 추가 — `UnifiedIngestSummary`, `FailureEntry`, `TranscriptStageResult`, `FingerprintStageResult`, `CleanupResult`, `RetryManifestDelta`, `RetryManifestEntry` (data-model.md §E-1/E-2/E-3/E-4/E-5/E-6/E-7). 각 모델에 type annotation + Google-style docstring + Literal 제약 (`failed_stage: Literal['transcript', 'fingerprint']`, `operator_response: Literal['yes','no','timeout','interrupted']` 등) 포함. `UnifiedIngestSummary` 는 spec 016 의 `IngestResult` 를 nest 하여 boundary B-7 보존.
- [x] T005 [P] `src/tube_scout/services/audit_writer.py` 의 stage 어휘에 `ingest_orchestrator`, `source_video_cleanup` 2 종 추가. reason 어휘에 신규 항목 추가 (`started`, `completed`, `aborted_by_user`, `failed_intermediate_stage`, `presented_failures`, `confirmed_yes`, `confirmed_no`, `timeout`, `interrupted`, `deleted`, `delete_failed_locked`, `delete_failed_io`). 기존 컬럼 셋 + append-only 보존 (B-5 boundary).

**Checkpoint**: T004 + T005 GREEN 이 되면 user story 진입.

---

## Phase 3: User Story 2 — Takeout 적재 효율화 (Priority: P1) 🎯 MVP 진입점

**Goal**: `src/tube_scout/services/evidence_score.py::score_mp4_candidates` 의 매칭 루프에서 mp4 1 개의 길이 측정 (`_probe_duration_via_ffprobe`) 이 영상 메타 후보 2554 회마다 반복 호출되던 것을 함수-local dict 캐시로 1 회만 호출하도록 변경. 적재 시간 약 17 분 → 약 1 분.

**Why MVP entry**: US1 의 통합 흐름이 US2 의 효율화 위에서 작동해야 가치 실현. US2 가 먼저 끝나면 US1 의 e2e 테스트가 1 분 안에 끝나서 후속 개발 cycle 의 효율이 큼.

**Independent Test**: `tests/unit/test_evidence_score_memoize.py` 의 ffprobe 호출 카운트 테스트가 `count == mp4 개수` 임을 확인하고, 회귀 환경에서 spec 016 의 `tests/integration/test_takeout_e2e_nursing.py::TestNursingTakeoutE2E` 9 PASS 가 유지되며, 본 작업 머신에서 dry-run 적재 단계가 1 분 이내에 완료됨을 측정으로 확인한다.

### Tests for User Story 2 (RED — failing 으로 확인 후 GREEN 진입)

- [x] T006 [P] [US2] `tests/unit/test_evidence_score_memoize.py` 신규 — `score_mp4_candidates(mp4_path, video_meta_list)` 호출 시 `_probe_duration_via_ffprobe` 가 mp4_path 1 개당 정확히 1 회만 호출됨을 `unittest.mock.patch` + `call_count` 로 검증 (FR-001, FR-002, data-model.md §E-9). 추가로 같은 mp4_path 가 다른 형식 (절대경로 vs 상대경로 vs symlink) 으로 들어와도 캐시 hit (resolved 절대경로 key) 임을 회귀.

### Implementation for User Story 2 (GREEN)

- [x] T007 [US2] `src/tube_scout/services/evidence_score.py::score_mp4_candidates` 함수 시작 시점에 `duration_cache: dict[str, float | None] = {}` 로 함수-local dict 캐시 초기화 (R-1, FR-002). loop 안에서 `mp4_key = str(mp4_path.resolve())` 로 캐시 key 생성 후 `duration_cache` 에 부재 시에만 `_probe_duration_via_ffprobe(mp4_path)` 호출. value 보존.
- [x] T008 [US2] `src/tube_scout/services/evidence_score.py` 에 신규 helper `_duration_match_with_cached(mp4_duration_s: float | None, video_duration_s: float, tol_s: float) -> bool` 추가. 기존 `_duration_match(mp4_path, video_duration_s, tol_s)` 의 시그니처는 보존 (다른 호출자가 있을 수 있음). `score_mp4_candidates` 의 loop 안에서는 신규 helper 를 호출하여 캐시된 mp4_duration 을 재사용.

### Refactor for User Story 2

- [x] T009 [US2] `src/tube_scout/services/evidence_score.py` 전체에 ruff check + 타입 어노테이션 점검 (Constitution Principle III). 신규 helper `_duration_match_with_cached` 의 docstring 을 Google-style 로 보강. 효율화 후 적재 단계를 본 작업 머신에서 재측정하여 elapsed_seconds 가 1 분 이내임을 단말에서 확인.

**Checkpoint**: T006 RED → T007/T008 GREEN → T009 REFACTOR 완료 시점에 SC-001 (적재 1 분 이내) 가 검증된다. **MVP 진입점 — US2 단독으로도 spec 017 의 핵심 효율화 가치 달성.**

---

## Phase 4: User Story 1 — 통합 명령 한 번으로 한 묶음 처리 (Priority: P1)

**Goal**: 신규 명령 `tube-scout collect ingest --channel nursing --takeout-dir <path>` 가 적재 → 자막 → 지문 → 매니페스트 갱신 → (옵션이면) 영상 삭제 5 단계를 단일 호출로 수행. 기존 분리 명령 5 개의 호출 표면 + 행동은 변경 없음 (backward compat).

**Independent Test**: 빈 작업 디렉토리 + 간호학과 sample archive 만 주고 통합 명령 한 번 실행 → 종료 시점에 SQLite 의 영상 메타 + 자막 9 개 + 지문 9 개 + retry_pending.json (0 entries) 가 모두 만들어져 있음을 확인. 멱등 2 회차에서 `new=0`, 자막·지문 재생성 0 가 표시되는지 함께 확인.

### Tests for User Story 1 (RED — failing 으로 확인 후 GREEN 진입)

- [x] T010 [P] [US1] `tests/contract/test_collect_ingest_contract.py` 신규 — `contracts/collect-ingest.md` 의 Acceptance Matrix 9 시나리오 전체 (정상 / `--delete-source yes` / `--delete-source no` / alias 미등록 / alias 비정합 / takeout_dir 부재 / `--dry-run` / 부분 실패 + `--delete-source` / 멱등 2 회차) 가 contract 의 exit code 와 stdout 패턴을 충족함을 검증.
- [x] T011 [P] [US1] `tests/unit/test_unified_ingest_orchestrator.py` 신규 — `services/unified_ingest.py::ingest_unified()` 의 단계별 호출 흐름을 mock 으로 검증. `ingest_takeout`, `transcribe_audio`, `extract_chromaprint_fingerprint`, `WavLifecycle` 이 정확한 순서로 호출되는지 + 시그니처 보존 (B-1/B-2/B-3/B-6/B-7 boundary). **추가로 SC-005 검증** — 동일 mp4 1 개당 `WavLifecycle` 진입이 정확히 1 회, `extract_wav_16k_mono` (또는 동등한 음원 추출 호출) 의 `call_count == mp4 매핑 수` 임을 mock 으로 회귀.
- [x] T012 [P] [US1] `tests/integration/test_collect_ingest_e2e.py` 신규 — 간호학과 sample archive 로 end-to-end. 종료 시점에 SQLite `video_metadata` 2554 행 + 자막 json 9 개 + 지문 row 9 개 + retry_pending.json entries=0 확인. `@pytest.mark.skipif(not _ARCHIVE_ROOT.exists(), reason="...")` 로 archive 부재 시 skip.
- [x] T013 [P] [US1] `tests/integration/test_ingest_idempotent.py` 신규 — SC-004 회귀: 같은 archive 두 번 통합 명령으로 처리 시 DB 행 수 / 자막 / 지문 / 매니페스트 모두 변화 0. 두 번째 호출의 `IngestResult.new_videos == 0` 확인.

### Implementation for User Story 1 (GREEN)

- [x] T014 [US1] `src/tube_scout/services/unified_ingest.py` 신규 모듈 — `ingest_unified(takeout_dir, channel_alias, db_path, work_root, *, use_symlinks, dry_run, delete_source, audit_writer, prompt_io) -> UnifiedIngestSummary` orchestrator 함수 정의 (R-2). 본 함수가 spec 016 의 `ingest_takeout()` 을 첫 단계로 호출하고, 두 번째 단계로 mp4 매핑된 영상에 대해 spec 013 의 `WavLifecycle` 컨텍스트 안에서 ASR + fingerprint 동시 처리. 시그니처 보존 (B-1, B-2, B-3, B-6).
- [x] T015 [US1] `src/tube_scout/services/unified_ingest.py::ingest_unified` 가 T004 에서 정의된 `UnifiedIngestSummary` (`models/content.py`) 를 import 하여 5 단위 결과 (적재·자막·지문·정리·매니페스트) 를 조립한 뒤 반환하도록 한다. 본 task 는 모델 정의가 아닌 **조립 책임** 만 다룬다 (모델 자체는 T004 에서 추가됨).
- [x] T016 [US1] `src/tube_scout/services/unified_ingest.py` 의 orchestrator 안에 단계별 Rich Console 헤더 + 진행 표시 (R-5). TTY 자동 감지 (`sys.stdout.isatty()`) — non-TTY 에서는 한 줄 헤더만, TTY 에서는 Rich `Progress` 컴포넌트. spec 013 의 C-4 정책 일관.
- [x] T017 [US1] `src/tube_scout/services/unified_ingest.py` 의 orchestrator 종료 시점에 `UnifiedIngestSummary` 를 Rich Table 5 행으로 stdout 출력 (`contracts/collect-ingest.md` 의 stdout 형식 그대로).
- [x] T018 [US1] `src/tube_scout/cli/collect.py` 에 `collect_ingest_command` 신규 Typer subcommand 추가 (FR-005, FR-010). 옵션: `--takeout-dir`, `--channel`, `--delete-source`, `--data-dir`, `--db-path`, `--dry-run`, `--copy` (contracts/collect-ingest.md). 본 명령은 `ingest_unified()` 의 thin wrapper — alias 검증 + audit_writer 초기화 + 호출 + exit code 결정만 수행 (Principle IV).
- [x] T019 [US1] `src/tube_scout/cli/collect.py::collect_ingest_command` 안에 spec 016 의 alias 비정합 검증 흐름 (FR-015) 을 호출 entrance 에 추가. `channels_reg in mismatch dept_channel_id` 시 명시적 에러 + exit 1 (boundary B-9 보존).

### Refactor for User Story 1

- [x] T020 [US1] `src/tube_scout/services/unified_ingest.py` 와 `src/tube_scout/cli/collect.py::collect_ingest_command` 에 ruff check + 타입 어노테이션 점검 + Google-style docstring 보강 (Principle III).

**Checkpoint**: T010~T013 RED → T014~T019 GREEN → T020 REFACTOR 완료 시점에 SC-002 (명령 1 회) / SC-004 (멱등성) / SC-005 (음원 디코딩 1 회) / SC-006 (단계별 측정) 모두 검증 가능. US1 + US2 = spec 017 의 P1 두 user story 완성.

---

## Phase 5: User Story 3 — 영상 본체 삭제 정책 + 재시도 매니페스트 (Priority: P2)

**Goal**: `--delete-source` 옵션 지정 시 두 단계 prompt (Stage 1 처리 실패 영상 표시 + Stage 2 삭제 후보 yes/no 확인) 흐름이 작동하고, 처리 실패 영상이 `data/<alias>/retry_pending.json` 으로 자동 정리되어 다음 통합 명령 호출에서 우선 재시도 대상이 된다.

**Independent Test**: `tests/integration/test_ingest_partial_failure.py` 의 모킹 환경 (자막 1 개 실패 강제) 에서 첫 번째 prompt 에 실패 1 개 표시 + 두 번째 prompt 의 삭제 후보 N-1 + 운영자 `y` 응답 시 N-1 unlink + 실패 1 개 보존 + retry_pending.json 에 entry 1 개 추가 확인. `tests/integration/test_ingest_retry_followup.py` 에서 두 번째 통합 명령 호출 시 매니페스트의 영상이 우선 재시도되어 성공 시 entry 제거됨 확인.

### Tests for User Story 3 (RED — failing 으로 확인 후 GREEN 진입)

- [x] T021 [P] [US3] `tests/unit/test_retry_manifest.py` 신규 — `contracts/retry-manifest.md` 의 Acceptance Matrix 9 시나리오 전체 (빈 매니페스트 로드 / 단일 추가 / 재실패 attempt_count 증가 / 성공 해소 / schema_version 불일치 raise / alias 불일치 raise / atomic write 부분 실패 보존 / 최대 시도 초과 제외 / 0600 권한). round-trip 검증 + atomic write semantics.
- [x] T022 [P] [US3] `tests/unit/test_source_video_cleanup.py` 신규 — `contracts/source-video-cleanup.md` 의 Acceptance Matrix 10 시나리오 전체 (실패 0/N × yes/no × EOF/Ctrl+C/locked/IO). `PromptIO` mock 으로 yes/no/timeout/interrupted 분기 + unlink 동작 + audit row 검증.
- [x] T023 [P] [US3] `tests/contract/test_retry_manifest_contract.py` 신규 — `data/<alias>/retry_pending.json` 의 JSON schema (schema_version=1, alias, updated_at, entries) 가 contract 그대로임을 검증. 각 entry 의 필드 셋 + Literal 제약 + ISO 8601 timezone-aware 확인.
- [x] T024 [P] [US3] `tests/contract/test_source_video_cleanup_contract.py` 신규 — 두 단계 prompt 흐름의 stdout 출력 형식 (Stage 1 Rich Table 어휘 + Stage 2 prompt 메시지 한글) + audit row 어휘 (`presented_failures`, `confirmed_yes`, `confirmed_no`, `timeout`, `interrupted`, `deleted`, `delete_failed_locked`, `delete_failed_io`) 가 contract 와 글자 단위 일치.
- [x] T025 [P] [US3] `tests/integration/test_ingest_partial_failure.py` 신규 — US3 Acceptance Scenario 4 + SC-007 회귀: 모킹 환경에서 자막 1 개 실패 강제 + `--delete-source` + 운영자 `y` 응답 시 Stage 1 에 실패 1 표시 + Stage 2 의 삭제 후보 N-1 + N-1 unlink + 실패 영상은 archive/symlink 보존 + retry_pending.json 에 entry 추가.
- [x] T026 [P] [US3] `tests/integration/test_ingest_retry_followup.py` 신규 — FR-018 + SC-008 회귀: retry_pending.json 에 entry 1 개 + 같은 archive 두 번째 통합 명령 호출 시 매니페스트의 영상이 우선 재시도되어 성공 시 매니페스트에서 제거됨. `attempt_count` 가 max 초과한 entry 는 우선 재시도 큐에서 제외 확인.

### Implementation for User Story 3 (GREEN)

- [x] T027 [US3] `src/tube_scout/services/retry_manifest.py` 신규 모듈 — `RetryManifest` pydantic 모델 (data-model.md §E-7) + 5 함수 (`load_manifest`, `save_manifest`, `add_or_update_failures`, `resolve_successes`, `select_retry_targets`) 정의 (contracts/retry-manifest.md). `_write_json_atomic` 패턴 + 0600 chmod + schema_version 검증.
- [x] T028 [US3] `src/tube_scout/services/source_video_cleanup.py` 신규 모듈 — `present_failure_table(failures, console)` 와 `confirm_and_cleanup(candidates, prompt_io, audit_writer) -> CleanupResult` 두 함수 정의 (contracts/source-video-cleanup.md). `PromptIO` Protocol + default Rich `Confirm.ask` 구현. unlink 시 archive mp4 + symlink 모두 정리 + 각 단계 audit row append.
- [x] T029 [US3] `src/tube_scout/services/unified_ingest.py::ingest_unified` 에 매니페스트 갱신 단계 (Step 4) 와 영상 삭제 단계 (Step 5) wire. `add_or_update_failures` 로 실패 누적 + `resolve_successes` 로 성공 처리 entry 제거 → `RetryManifestDelta` 반환. `delete_source=True` 인 경우만 `present_failure_table` + `confirm_and_cleanup` 호출.
- [x] T030 [US3] `src/tube_scout/cli/collect.py::collect_ingest_command` 의 옵션 매트릭스에 `--delete-source` flag 추가 (FR-011). default `False`. flag 가 지정된 경우만 `ingest_unified(..., delete_source=True)` 로 호출. 미지정 시 prompt 자체가 등장하지 않음 (silent 가 아닌 명시적 no-op).
- [x] T031 [US3] `src/tube_scout/services/unified_ingest.py::ingest_unified` 에서 다음 호출의 재시도 우선순위 큐 결정 — `select_retry_targets(manifest, max_attempts=5)` 로 매니페스트의 video_ids 를 가져와, 해당 영상이 mp4 매핑되어 있다면 ASR / fingerprint 단계의 처리 우선 순위로 큐에 추가 (FR-015, FR-018).

### Refactor for User Story 3

- [x] T032 [US3] `src/tube_scout/services/retry_manifest.py` + `src/tube_scout/services/source_video_cleanup.py` + `cli/collect.py` 의 `--delete-source` 변경 부분에 ruff + 타입 + Google-style docstring 점검. prompt 메시지가 한글 풀어쓰기 (사용자 메모리 `feedback_response_style`) 인지 확인.

**Checkpoint**: T021~T026 RED → T027~T031 GREEN → T032 REFACTOR 완료 시점에 SC-003 (영상 삭제 0 사고) + SC-007 (부분 실패 영상 노출 100%) + SC-008 (재시도 매니페스트 누락 0) 모두 검증 가능. US1 + US2 + US3 = spec 017 의 P1+P2 user story 모두 완성.

---

## Phase 6: User Story 4 — 22 학과 확장을 위한 운영 baseline (Priority: P3)

**Goal**: 통합 명령 종료 시 운영자에게 표시되는 처리 요약에 단계별 (적재·자막·지문·삭제) 소요 시간이 모두 양의 측정값으로 표시되고, 같은 archive 를 두 번 처리해도 측정값이 안정적으로 재현된다. 22 학과 확장 시점에 운영 baseline 으로 활용 가능.

**Independent Test**: `test_collect_ingest_e2e.py` 의 정상 종료 시점에 stdout 의 Rich Table 5 행 모두 `소요 시간` 컬럼이 양의 측정값임을 확인. 같은 archive 두 번 호출 시 단계별 measured time 의 표준편차가 평균의 20% 이내임을 확인 (안정성).

### Tests for User Story 4 (RED — US1 의 통합 테스트에 검증 흐름 추가)

- [x] T033 [P] [US4] `tests/integration/test_collect_ingest_e2e.py` 에 추가 — `UnifiedIngestSummary.transcript_result.elapsed_seconds > 0`, `fingerprint_result.elapsed_seconds > 0`, `cleanup_result is None` (옵션 미지정 시) 또는 `cleanup_result.elapsed_seconds >= 0` (옵션 지정 시), `ingest_result.elapsed_seconds > 0`, `total_elapsed_seconds > 0` 모두 확인. (US1 의 T012 와 같은 파일, 다른 테스트 메서드)

### Implementation for User Story 4 (GREEN)

- [x] T034 [US4] `src/tube_scout/services/unified_ingest.py::ingest_unified` 의 각 단계 진입 직전 / 종료 직후 `time.monotonic()` 측정 + `UnifiedIngestSummary` 의 stage 별 필드에 elapsed 저장 (data-model.md §E-1).
- [x] T035 [US4] `src/tube_scout/services/audit_writer.py` 의 stage `ingest_orchestrator` row 에 `elapsed_ms` 필드 포함 (B-5 boundary, spec 016 의 FR-023 보존). 각 단계 (`started`, `completed`) 별 row 에 cumulative elapsed_ms 기록.

### Refactor for User Story 4

- [x] T036 [US4] `src/tube_scout/services/unified_ingest.py` 의 측정 로직 부분에 ruff + 타입 + docstring 점검. elapsed 값의 timezone / unit (seconds vs ms) 명확화.

**Checkpoint**: T033 RED → T034~T035 GREEN → T036 REFACTOR 완료 시점에 SC-006 (단계별 측정값) 검증 가능. spec 017 의 4 user story 모두 GREEN.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 효율화 후 새 SLA baseline 측정 + 문서화 + 전체 회귀 매트릭스 + ruff/type 마무리 + release 준비.

- [x] T037 [P] 효율화 후 baseline 측정 — `tube-scout collect ingest --takeout-dir data/takeout-20260511T130817Z-3-001 --channel nursing --dry-run` 의 elapsed_seconds 3 회 평균 + 같은 명령의 실적재 (`--dry-run` 제거) 3 회 평균 측정. 결과를 `_workspace/spec017_baseline_after_memoize.md` 에 저장. SC-001 (≤ 60 s) 충족 확인.
- [x] T038 [P] T037 결과 기반으로 `specs/017-takeout-unified-ingest/plan.md` 의 §"Performance Goals" 와 `specs/017-takeout-unified-ingest/quickstart.md` 의 운영자 체크리스트 §5 에 정량 SLA 갱신. T003 의 baseline 17 분 대비 17 배 개선이 단말 측정으로 확인되었음을 명시.
- [x] T039 [P] `specs/017-takeout-unified-ingest/quickstart.md` §6 의 22 학과 확장 운영 패턴 문서가 실측 baseline 과 일관함을 검증. 학과당 약 N 분 표현을 측정값으로 치환.
- [x] T040 [P] `CLAUDE.md` 의 "Active Technologies" / "Recent Changes" 자동 갱신 결과 확인 (T020 / T032 시점에 이미 자동 갱신됨). 필요시 spec 017 의 변경 요지 (`collect ingest` 신규 명령 + retry_pending.json + ffprobe 메모이즈) 를 한 줄 보강.
- [x] T041 회귀 매트릭스 전체 실행 — `uv run pytest tests/unit/test_evidence_score_memoize.py tests/unit/test_retry_manifest.py tests/unit/test_source_video_cleanup.py tests/unit/test_unified_ingest_orchestrator.py tests/integration/test_collect_ingest_e2e.py tests/integration/test_ingest_idempotent.py tests/integration/test_ingest_partial_failure.py tests/integration/test_ingest_retry_followup.py tests/contract/test_collect_ingest_contract.py tests/contract/test_retry_manifest_contract.py tests/contract/test_source_video_cleanup_contract.py -v`. 추가로 spec 016 의 회귀 매트릭스 (`tests/unit/test_takeout_ingest.py tests/integration/test_takeout_e2e_nursing.py tests/integration/test_v4_schema_invariant.py` 등) 가 본 spec 의 변경 후에도 모두 PASS 임을 확인 (Cross-Spec Boundary 보존). SC-001/002/003/004/005/006/007/008 8 개 모두 PASS 확인.
- [x] T042 ruff check 변경 surface 한정 (`src/tube_scout/services/evidence_score.py`, `src/tube_scout/services/unified_ingest.py`, `src/tube_scout/services/retry_manifest.py`, `src/tube_scout/services/source_video_cleanup.py`, `src/tube_scout/services/audit_writer.py`, `src/tube_scout/models/content.py`, `src/tube_scout/cli/collect.py` + 신규 테스트 11 파일) + 타입 검사 + `pyproject.toml` 의 `version = "0.6.0.dev0"` 유지 확인.
- [x] T043 [DEFERRED: 사용자 별도 실측, 2026-05-16 결정] 운영자 quickstart 매뉴얼 §5 체크리스트 11 항목 모두 실측 확인 (간호학과 9 영상 archive 로 사용자가 처음부터 끝까지 따라하는 시나리오). `--delete-source` 미지정 / 지정 + yes / 지정 + no 3 가지 흐름 모두 실측.
- [x] T044 git status 점검 + spec.md + plan.md + research.md + data-model.md + contracts/ + quickstart.md + tasks.md + checklists/ + 코드 변경 7 파일 + 테스트 신규 11 파일이 모두 commit 대상에 들어가 있는지 확인 (Cross-Spec Boundary B-3 보존).

---

## Dependencies (Phase / User Story 완료 순서)

```text
Phase 1 Setup (T001~T003)
       │
       ▼
Phase 2 Foundational (T004~T005)  ← 모든 user story 의 blocking prerequisite
       │
       ▼
Phase 3 US2 RED→GREEN→REFACTOR (T006~T009)  🎯 MVP 진입점 (적재 효율화)
       │
       │ (US1 의 e2e 가 US2 효율화 위에서 1 분 안에 끝나므로 US2 → US1 권장)
       ▼
Phase 4 US1 RED→GREEN→REFACTOR (T010~T020)  ← 통합 흐름, US2 의 효율화 활용
       │
       ▼
Phase 5 US3 RED→GREEN→REFACTOR (T021~T032)  ← US1 의 orchestrator 가 GREEN 된 후
       │
       ▼
Phase 6 US4 RED→GREEN→REFACTOR (T033~T036)  ← US1 의 단계별 측정 흐름 보강
       │
       ▼
Phase 7 Polish (T037~T044)  ← 모든 user story GREEN 후
```

### 병렬 실행 후보 (Phase 안에서 [P] 표시된 task 끼리)

- **Phase 2 Foundational**: T004 (models) ∥ T005 (audit_writer) — 다른 파일, 의존성 없음.
- **Phase 3 US2 RED**: T006 단일 — 병렬 후보 없음.
- **Phase 4 US1 RED**: T010~T013 4 개가 모두 다른 test 파일이라 병렬.
- **Phase 4 US1 GREEN**: T014~T019 6 개 중 `unified_ingest.py` 의 다른 함수/모델은 같은 파일이라 순차 (T014→T015→T016→T017), `cli/collect.py` 는 다른 파일 (T018, T019).
- **Phase 5 US3 RED**: T021~T026 6 개가 모두 다른 test 파일이라 병렬.
- **Phase 5 US3 GREEN**: T027 (retry_manifest.py) ∥ T028 (source_video_cleanup.py) ∥ T030 (cli/collect.py) — 다른 파일이라 병렬. T029, T031 은 unified_ingest.py 안의 변경이라 순차.
- **Phase 6 US4 RED/GREEN**: T033 ∥ T034 ∥ T035 — 다른 파일 또는 다른 함수.
- **Phase 7 Polish**: T037~T040 4 개가 측정/문서/검토라 병렬. T041~T044 는 검증 흐름이라 순차.

---

## Implementation Strategy

### MVP scope (P1 user story 2 개)

- **MVP 진입**: T001~T009 (Setup + Foundational + US2) 완료 시점. 이 시점에 가장 큰 운영 부담 (적재 17 분) 이 해소되어 본 spec 의 핵심 효율화 가치가 달성됨. **단독으로도 충분히 valuable.**
- **MVP 완성**: T001~T020 (Setup + Foundational + US2 + US1). 이 시점에 spec 017 의 P1 두 user story (통합 흐름 + 적재 효율화) 모두 완성. SC-001/002/004/005/006 가 PASS.

### Incremental delivery

| 단계 | 완료 task | 제공 가치 |
|---|---|---|
| Step 1 (0.5 일) | T001~T005 | 환경 + 버전 + Foundational. 코드 변경 최소이지만 모든 user story 진입 가능. |
| Step 2 (0.5 일) | T006~T009 (US2) | 🎯 MVP 진입점 — 적재 17 분 → 1 분. **단독 release 가능한 효율화.** |
| Step 3 (2 일) | T010~T020 (US1) | 통합 명령 `collect ingest` 도입. 운영자가 한 명령으로 한 학과 묶음 처리 가능. |
| Step 4 (2 일) | T021~T032 (US3) | 영상 본체 삭제 두 단계 prompt + 재시도 매니페스트. 사용자 의도 (영상 삭제 + 재시도) 직접 구현. |
| Step 5 (0.5 일) | T033~T036 (US4) | 단계별 측정값 노출. 22 학과 baseline 수립. |
| Step 6 (0.5 일) | T037~T044 | Performance baseline 갱신 + 정량 SLA + 문서 + 전체 회귀 + release 준비. |

### TDD enforcement

각 user story 안에서 **RED task 가 GREEN task 보다 먼저** 배치되어 있다. Constitution Principle I (NON-NEGOTIABLE) 의 운영 규칙:

1. RED task 의 test 를 작성하고 `uv run pytest <test_file> -v` 가 **failing** 임을 단말에서 확인.
2. failing 을 확인하지 못한 채 GREEN 으로 진입하면 test 가 자기 자신을 검증하지 못한다 (false positive). 즉 모든 RED task 의 종료 조건 = pytest 가 실제로 fail 함을 단말에서 확인.
3. GREEN task 후 같은 test 가 PASS 로 전환되는 것을 단말에서 확인.
4. REFACTOR 단계에서 ruff / 타입 / docstring 점검 후 test 가 여전히 PASS 임을 확인.

### Cross-Spec Boundary 유지 (Constitution VII)

본 spec 의 모든 코드 변경은 plan.md §"Cross-Spec Boundaries" 의 B-1 ~ B-10 보장을 보존한다. tasks 안의 각 GREEN task 가 어느 boundary 를 건드리는지:

- B-1 (spec 013 `WavLifecycle`): T014, T016 (orchestrator 가 컨텍스트 매니저 안에서 호출)
- B-2 (spec 013 `transcribe_audio` 시그니처): T014 (orchestrator wire)
- B-3 (spec 013 `extract_chromaprint_fingerprint` 시그니처): T014 (orchestrator wire)
- B-4 (spec 013 SQLite v4 스키마): 모든 task — 스키마 변경 없음 확인이 T041 회귀 매트릭스에 포함
- B-5 (spec 013 감사 CSV append-only): T005 (stage 어휘 추가), T028 (cleanup row), T029 (매니페스트 row), T035 (orchestrator row)
- B-6 (spec 016 `ingest_takeout` 시그니처): T014 (orchestrator 가 호출)
- B-7 (spec 016 `IngestResult` 필드 셋): T015 (UnifiedIngestSummary 가 nest)
- B-8 (spec 016 `data/<alias>/` 디렉토리): T027 (retry_pending.json 위치)
- B-9 (spec 003 alias 등록부 union): T019 (alias 검증 흐름)
- B-10 (spec 009 OAuth 토큰): T018 (OAuth 토큰 부재가 ingest 실패 사유 아님)

T041 회귀 매트릭스 완료 시점에 10 boundary 가 모두 깨지지 않았음을 검증.

---

## Validation Checklist (tasks 작성자 자가 검증)

- [x] 모든 task 가 `- [ ] T### [P?] [US?] Description with file path` 형식 준수
- [x] Setup phase (T001~T003) 와 Polish phase (T037~T044) 에는 [US] 라벨 없음
- [x] Foundational phase (T004~T005) 에는 [US] 라벨 없음 — 모든 user story 의 공통 prerequisite
- [x] User story phase (T006~T036) 의 모든 task 에 [US1]/[US2]/[US3]/[US4] 라벨
- [x] 각 task 에 파일 절대경로 또는 명확한 repo-root 상대경로 명시
- [x] 병렬 가능 task 에 [P] 표시 (다른 파일 또는 의존성 없음)
- [x] 각 user story phase 가 RED → GREEN → REFACTOR 순서
- [x] SC-001~008 8 개 success criteria 가 모두 적어도 하나의 task 로 검증됨
- [x] FR-001~018 18 개 functional requirement 가 모두 task 안에서 인용됨
- [x] Cross-Spec Boundary B-1 ~ B-10 10 개가 모두 적어도 하나의 task 로 보존 검증됨
- [x] MVP scope (Phase 1 + 2 + US2) 가 명시되어 incremental delivery 가능 — US2 단독으로도 효율화 가치 release 가능
