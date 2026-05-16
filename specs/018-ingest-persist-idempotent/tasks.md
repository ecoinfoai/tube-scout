---
description: "Task list for spec 018 — unified_ingest 영구화 + 멱등 가드 (spec 017 PATCH)"
---

# Tasks: unified_ingest 영구화 + 멱등 가드 (spec 017 PATCH)

**Branch**: `018-ingest-persist-idempotent` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**Tests**: 본 PATCH 는 Constitution Principle I (Test-First — NON-NEGOTIABLE) 에 따라 모든 RED → GREEN → REFACTOR 사이클을 강제. 각 user story 의 implementation task 진입 전에 failing test 가 작성되고 RED 확인되어야 한다.

**Organization**: tasks 는 user story 별 phase 로 묶이며, 각 phase 종료 시점에 해당 story 가 독립적으로 테스트 가능해야 한다.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 병렬 실행 가능 (다른 파일, 미완 task 의존성 없음)
- **[Story]**: [US1], [US2], [US3] — spec.md 의 user story 매핑
- 모든 description 에 정확한 파일 경로 포함

## Path Conventions

단일 프로젝트 구조 (plan.md §Project Structure):

- 소스: `src/tube_scout/{models,services,storage,cli}/`
- 테스트: `tests/{unit,integration,contract}/`
- fixture: `tests/fixtures/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 본 PATCH 는 기존 spec 017 코드베이스 안에서 surgical fix — 신규 프로젝트 init 없음, 신규 의존성 없음. Setup 은 환경 검증과 fixture 준비로 한정.

- [ ] T001 환경 검증 — `uv run python -c "from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint; from tube_scout.services.asr import transcribe_audio, detect_quality_flags; from tube_scout.services.audio_extract import WavLifecycle, cleanup_wav; print('OK')"` 한 줄로 spec 017 의 핵심 surface 4 개 import 가능함을 검증 (resolved imports → working state).
- [ ] T002 [P] fixture archive 준비 — `tests/fixtures/spec018_mini_archive/` 아래에 3 mp4 짜리 mini Takeout archive 생성. 구체 요구: (a) 실 mp4 파일 3 개, 각 길이 ≤ 1 분 (faster-whisper 단 ≤ 10 초 처리 가능), 16 kHz mono opus/aac 오디오 트랙 포함, (b) Takeout 구조 — `YouTube and YouTube Music/videos/<title>.mp4` + `YouTube and YouTube Music/history/watch-history.json` 메타 (3 mp4 + 약간의 metadata-only 엔트리), (c) README.md 1 파일에 origin (간호학과 archive 의 가장 짧은 3 개 추출 등) 과 총 size 명시. CI 비용 절감을 위해 git LFS 또는 별도 다운로드 스크립트 사용.
- [ ] T003 [P] ruff baseline 캡처 — `uv run ruff check src/tube_scout/services/unified_ingest.py src/tube_scout/cli/collect.py > _workspace/spec018_ruff_baseline.log` 로 본 PATCH 진입 시점의 lint 상태 저장. 본 PATCH 종료 시점에 동일 명령 결과가 baseline 보다 악화되지 않음을 확인 (T044 에서 검증).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 모든 user story 가 의존하는 공통 기반 — 데이터 모델 확장, audit reason 어휘 추가, helper 시그니처 정의. 이 phase 종료까지 어떤 user story 도 진입하지 않음.

**⚠️ CRITICAL**: 본 phase 완료 전 어떤 user story 의 implementation 도 시작하지 않는다.

- [ ] T004 `TranscriptStageResult` / `FingerprintStageResult` 에 `skip_count: int = 0` 필드 추가 in `src/tube_scout/models/content.py` (data-model.md §2.2/§2.3). pydantic v2 BaseModel default 값 0 으로 backward compat 유지.
- [ ] T005 [P] `IdempotencyGuardResult` frozen dataclass 신규 정의 in `src/tube_scout/services/unified_ingest.py` (또는 별 helper module). 필드: `video_id: str, transcript_skip: bool, fingerprint_skip: bool, wav_decode_skip: bool` (data-model.md §2.1).
- [ ] T006 [P] audit_writer reason 어휘 확장 — `src/tube_scout/services/audit_writer.py` 의 `ingest_orchestrator` stage 에 reason 상수 `already_transcribed`, `already_fingerprinted`, `already_transcribed_and_fingerprinted` 등록 (data-model.md §5 / contract `idempotency-guard.md` §8). 만약 audit_writer 가 enum 기반이면 추가, free-text 면 docstring 에 어휘 명시.
- [ ] T007 `insert_audio_fingerprint` 의 SQL 패턴 확인 in `src/tube_scout/storage/content_db.py` — 현재 `INSERT INTO` 인지 `INSERT OR REPLACE INTO` 인지 grep 으로 확인. `INSERT OR REPLACE` 가 아니면 본 task 에서 변경 (FR-018B + research.md §1.2). 변경 시 분리 명령 `collect fingerprint --force` 의 회귀가 발생하지 않도록 `test_collect_fingerprint.py` 등 기존 테스트 GREEN 확인.
- [ ] T008 `_persist_transcript()` 함수 시그니처 stub 작성 in `src/tube_scout/services/unified_ingest.py` — 구현은 비우고 `raise NotImplementedError`, 단 type annotation 과 Google docstring 만 완성. 시그니처: `def _persist_transcript(transcript_dir: Path, video_id: str, asr_result: TranscribeResult, ts: str) -> Path` (반환은 atomic write 된 json 의 absolute path).
- [ ] T009 `_check_already_processed()` 함수 시그니처 stub 작성 in `src/tube_scout/services/unified_ingest.py` — 같은 방식으로 stub 만. 시그니처: `def _check_already_processed(video_id: str, transcript_dir: Path, db_conn: sqlite3.Connection, *, force: bool = False) -> IdempotencyGuardResult` (contract `idempotency-guard.md` §1.1).

**Checkpoint**: Foundational phase 완료. 모든 user story 가 stub 호출 + import 가능 상태.

---

## Phase 3: User Story 1 - 첫 호출에서 자막·지문이 영구 저장된다 (Priority: P1) 🎯 MVP

**Goal**: 통합 명령이 분리 명령과 schema-for-schema 동치인 자막 transcript json (top-level 7 키 + asr_quality_flags 6 종) 과 audio_fingerprint DB row 를 영구화한다. 본 story 만 완성되어도 spec 011 의 재사용 탐지가 분리/통합 산출물 양쪽을 분기 없이 소비 가능.

**Independent Test**: 3 mp4 fixture archive 에 대해 `tube-scout collect ingest --takeout-dir <fixture> --alias test1` 호출 후 (a) `data/test1/02_analyze/transcripts/*.json` 3 개 존재 + 7 키 + `.tmp` 0 개, (b) `audio_fingerprint` 테이블 row 3 개 (PK 단일성) — 둘 다 만족하면 PASS.

### Tests for User Story 1 (RED 단계 — Constitution Principle I)

⚠️ 본 4 개 test 모두 작성 후 RED 확인 → 그 다음 implementation 진입.

- [ ] T010 [P] [US1] Unit test 작성 in `tests/unit/test_unified_ingest_persist.py` — `_persist_transcript()` 가 (a) atomic write (tempfile + replace 호출 추적), (b) 7 키 모두 포함하는 json 생성, (c) `*.tmp` 잔재 0 개, (d) 동일 video_id 두 번 호출 시 두 번째 mtime 갱신 (force semantics 부재 시점의 raw helper 동작), (e) **transcript_dir 권한 부족 → PermissionError fail-fast** — `transcript_dir.chmod(0o555)` 시점에 atomic write 시도 시 명시적 PermissionError raise 되고 부분 작성 잔재 0 (Principle II Fail-Fast, spec.md Edge case). RED 확인.
- [ ] T011 [P] [US1] Unit test 작성 in `tests/unit/test_unified_ingest_fingerprint_persist.py` — `_run_transcript_and_fingerprint` 처리 후 `audio_fingerprint` 테이블의 row count = mp4 매핑 수, 동일 video_id 두 번 처리 시 (force 가정) row count 가 정확히 1 (PK 단일성). RED 확인.
- [ ] T012 [P] [US1] Contract test 작성 in `tests/contract/test_transcript_artifact_contract.py` — contract `transcript-artifact.md` §4.1 의 `test_transcript_artifact_schema_equivalence` 패턴. 분리 명령 산출물 vs 통합 명령 산출물의 키 집합 + asr_quality_flags 6 종 + segment 객체 키 = 동치 (FR-018H, SC-018-5). RED 확인.
- [ ] T013 [P] [US1] Integration test 작성 in `tests/integration/test_ingest_persist_first_call.py` — fixture archive (3 mp4) 에 첫 호출 시 (a) transcript json 3 개 atomic write, (b) DB row 3 개, (c) WAV cleanup 검증, (d) Rich Table 의 자막/지문 행에 처리 3 표시. RED 확인.

### Implementation for User Story 1 (GREEN 단계)

- [ ] T014 [US1] `_persist_transcript()` 구현 in `src/tube_scout/services/unified_ingest.py` (T008 stub 채우기) — `tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")` + `os.fdopen` + `json.dump` + `os.replace`. cli/collect.py:2268-2281 의 분리 명령 패턴 동일 copy (research.md §1.1). `transcript = {"video_id": video_id, "source": asr_result.caption_source_detail, "language": asr_result.language_detected, "duration": asr_result.duration, "segments": asr_result.segments, "asr_quality_flags": asr_result.asr_quality_flags.model_dump(), "fetched_at": ts}` 직렬화.
- [ ] T015 [US1] `_run_transcript_and_fingerprint` 의 ASR 결과 처리 보강 in `src/tube_scout/services/unified_ingest.py:100` — `transcribe_audio` 반환값을 변수로 받아 `_persist_transcript(transcript_dir, video_id, asr_result, ts)` 호출. 기존 try/except 블록 안에서 작업하되 영속화 실패 시 transcript_failures 에 등재 (FR-018A + 결함 A 해소).
- [ ] T016 [US1] `_run_transcript_and_fingerprint` 의 지문 결과 처리 보강 in `src/tube_scout/services/unified_ingest.py:113` — `extract_chromaprint_fingerprint(wav_path)` 의 반환값 `(fp_bytes, duration)` 을 받아 `insert_audio_fingerprint(db_path, video_id, fp_bytes, duration, ts)` 호출. 기존 try/except 안에서 작업, 영속화 실패 시 fingerprint_failures 에 등재 (FR-018B + 결함 B 해소).
- [ ] T017 [US1] `transcript_dir` 생성 의무 — `_run_transcript_and_fingerprint` 진입 시점에 `transcript_dir = work_root / channel_alias / "02_analyze" / "transcripts"; transcript_dir.mkdir(parents=True, exist_ok=True)` 실행. 멱등 mkdir.
- [ ] T018 [US1] `_run_transcript_and_fingerprint` 의 signature 에 `db_path: Path` 추가 + `ingest_unified` 의 호출부 (services/unified_ingest.py:367-372) 도 같이 갱신. DB connection 은 본 helper 안에서 열고 닫는다 (또는 호출자에게 위임). T015/T016/T019 가 의존.
- [ ] T019 [US1] Rich Table 표 형식 보강 in `src/tube_scout/services/unified_ingest.py::_print_summary_table` — spec 017 의 기존 **5-row 구조** (적재 / 자막 생성 / 음원 지문 / 매니페스트 갱신 / 영상 정리) 를 보존하면서 열을 4 → **5 로 확장**: 신규 컬럼 셋 = (단계 / 처리 / **skip** / 실패 / 소요 시간) (FR-018F, SC-018-6). `table.add_column("skip", justify="right")` 를 "처리" 와 "실패" 사이에 삽입. 자막 생성 행과 음원 지문 행은 skip 열에 정수 카운트 (`tr.skip_count` / `fr.skip_count`) 표시, 다른 행 (적재 / 매니페스트 / 영상 정리) 의 skip 열은 `-` 표시.
- [ ] T020 [US1] audit_writer call 보강 — 각 video×stage 처리 직후 `audit_writer.append_row("ingest_orchestrator", {video_id, result, reason, channel_alias, elapsed_ms, timestamp})` 호출. result = `success`/`fail`, reason 어휘는 분리 명령의 `asr_transcribed`/`captured` 와 일관.
- [ ] T021 [US1] T010~T013 4 개 test 모두 GREEN 확인 — 한 번에 `uv run pytest tests/unit/test_unified_ingest_persist.py tests/unit/test_unified_ingest_fingerprint_persist.py tests/contract/test_transcript_artifact_contract.py tests/integration/test_ingest_persist_first_call.py -v`.

**Checkpoint**: User Story 1 의 모든 acceptance scenario (spec.md §USR1 1~3) 가 통과. fresh archive 첫 호출 시 transcript json + DB row 둘 다 영속. spec 011 reader 가 통합 명령 산출물을 분기 없이 소비 가능. **MVP 출하 가능 시점.**

---

## Phase 4: User Story 2 - 두 번째 호출은 즉시 끝난다 (Priority: P1)

**Goal**: 같은 archive 에 대한 두 번째 호출 wall clock ≤ 2 초 + 자막/지문 단계 "skip 9 / 처리 0 / 실패 0" + faster-whisper 모델 로드 0 + WAV 디코딩 0. SC-004 회복.

**Independent Test**: T013 의 fixture archive 에 첫 호출 후 두 번째 호출 시 (a) `time` 출력 real ≤ 2 초, (b) WAV 임시 파일 0 개 (호출 동안에도 생성 안 됨), (c) GPU 메모리 점유 0 (`nvidia-smi` 로 검증 가능 환경에서), (d) Rich Table 의 skip 열 = 3 (mini fixture 기준). 모두 만족하면 PASS.

### Tests for User Story 2 (RED 단계)

- [ ] T022 [P] [US2] Unit test 작성 in `tests/unit/test_unified_ingest_idempotent.py` — `_check_already_processed()` 의 4 경우 매트릭스 검증 (contract `idempotency-guard.md` §3 + §9 GS-1~GS-5). transcript_skip / fingerprint_skip 의 독립 평가, wav_decode_skip 의 AND 결합. RED 확인.
- [ ] T023 [P] [US2] Unit test 작성 in `tests/unit/test_unified_ingest_skip_count.py` — 영상 루프 종료 시점에 `TranscriptStageResult.skip_count` 와 `FingerprintStageResult.skip_count` 가 멱등 가드 skip 영상 수와 정확히 일치 (FR-018F). RED 확인.
- [ ] T024 [P] [US2] Contract test 작성 in `tests/contract/test_idempotency_guard_contract.py` — contract `idempotency-guard.md` §4 의 SQL pattern (`SELECT 1 FROM audio_fingerprint WHERE video_id=? LIMIT 1`), §5 의 file existence pattern, §6 의 wav_decode_skip semantics. 추가로 **Edge case "DB schema 호환 검사 실패"** 1 case: 빈 SQLite DB (테이블 부재) 에서 `_check_already_processed` 호출 시 명시적 `sqlite3.OperationalError` (또는 actionable RuntimeError) 가 raise 되며 자동 테이블 생성이 일어나지 않음을 검증 (Principle II Fail-Fast). RED 확인.
- [ ] T025 [P] [US2] Integration test 작성 in `tests/integration/test_ingest_idempotent.py` — **기존 spec 017 의 mock-only 테스트를 real archive fixture 로 보강** (FR-018F, T013 인계). (a) fixture archive 첫 호출 후 두 번째 호출 wall clock ≤ 2 초 (`time.monotonic()` 측정), (b) `data/<alias>/tmp_wav/*.wav` 호출 동안 0 개, (c) transcript json mtime 변화 0, (d) DB row count 변화 0. RED 확인 (현재 unified_ingest.py 는 멱등 가드가 없으므로 wall clock 14m+ 로 실패).
- [ ] T026 [P] [US2] Integration test 작성 in `tests/integration/test_ingest_model_load_skip.py` — 두 번째 호출 동안 `faster_whisper.WhisperModel.__init__` 이 호출되지 않음을 monkeypatch + spy 로 검증 (Q4 결정, FR-018E). 첫 호출에는 호출됨을 확인하여 patch 자체가 false-positive 가 아님을 검증. RED 확인.

### Implementation for User Story 2 (GREEN 단계)

- [ ] T027 [US2] `_check_already_processed()` 구현 in `src/tube_scout/services/unified_ingest.py` (T009 stub 채우기) — `force=True` 분기에서 `(False, False, False)` 반환, `force=False` 분기에서 `Path.exists()` + SQLite SELECT. sqlite3.Connection 은 caller 가 전달 (또는 함수 내부에서 open/close — implementation 선택, 후자가 단일 책임 분명).
- [ ] T028 [US2] `_run_transcript_and_fingerprint` 의 영상 루프 시작 시점에 멱등 가드 호출 + skip 분기 in `src/tube_scout/services/unified_ingest.py:72` 주변. `guard = _check_already_processed(video_id, transcript_dir, db_conn, force=force)` → `if guard.wav_decode_skip: audit_writer.append_row(...skip 2 rows...); transcript_skip_count += 1; fingerprint_skip_count += 1; continue`. contract `idempotency-guard.md` §6 패턴.
- [ ] T029 [US2] 단계별 skip 분기 — `with WavLifecycle(...) as wav_path:` 안에서 `if not guard.transcript_skip: transcribe_audio(...) + _persist_transcript(...)` / `if not guard.fingerprint_skip: extract_chromaprint_fingerprint(...) + insert_audio_fingerprint(...)`. 부분 영구화 영상에 대한 한 단계 처리.
- [ ] T030 [US2] `TranscriptStageResult.skip_count` / `FingerprintStageResult.skip_count` 채우기 — `_run_transcript_and_fingerprint` 의 return 시점에 skip 카운트를 두 모델에 전달.
- [ ] T031 [US2] Rich Table 의 자막 생성 / 음원 지문 두 행에 skip 카운트 값 채우기 in `_print_summary_table` — T019 의 5-row × 5-col 구조 활용. `tr.skip_count` 와 `fr.skip_count` 를 두 행의 "skip" 열에 정수 출력. 다른 행 (적재 / 매니페스트 / 영상 정리) 의 skip 열은 T019 에서 이미 `-` 로 채워진 상태 그대로 유지.
- [ ] T032 [US2] audit reason 어휘 적용 — skip 시 reason = `already_transcribed` / `already_fingerprinted` / `already_transcribed_and_fingerprinted` (T006 에서 등록한 어휘 사용). reason 별 row 수가 contract `collect-ingest-force.md` §5 의 매트릭스와 일치. 추가 명시: **transcribe_audio 가 성공 반환했으나 `asr_quality_flags` 의 일부 flag 가 true 인 영상도 reason = `asr_transcribed` 로 기록**한다 (분리 명령 동작 인계, spec.md Edge case 결정). quality flag 는 transcript json 의 `asr_quality_flags` 키로 노출되며 audit reason 자체는 quality 기준으로 분기하지 않는다. 본 분기 부재를 unit test 1 case (`tests/unit/test_unified_ingest_skip_count.py` 의 보조 case 또는 신규 1 줄) 로 검증.
- [ ] T033 [US2] T022~T026 5 개 test GREEN 확인 — `uv run pytest tests/unit/test_unified_ingest_idempotent.py tests/unit/test_unified_ingest_skip_count.py tests/contract/test_idempotency_guard_contract.py tests/integration/test_ingest_idempotent.py tests/integration/test_ingest_model_load_skip.py -v`.

**Checkpoint**: User Story 2 acceptance scenario (spec.md §USR2 1~5) 모두 통과. 같은 archive 두 번째 호출 ≤ 2 초. SC-018-1 / SC-018-4 (환산) 달성.

---

## Phase 5: User Story 3 - 강제 재처리 옵션 (Priority: P2)

**Goal**: `--force` 옵션이 멱등 가드를 우회하여 archive 내 전체 영상을 재처리 + retry_pending.json 자동 갱신 (성공 시 제거, 실패 시 추가/유지). spec 013 `collect fingerprint --force` 와 시그니처·의미 일관.

**Independent Test**: US1/US2 산출물 (transcripts 9 + DB row 9) 이 존재하는 archive 에 `--force` 호출 후 (a) wall clock fresh 처리 범위, (b) transcripts json mtime 모두 갱신, (c) DB row 수 변화 0 (PK 단일성), (d) `--force` 가 retry_pending entries 도 함께 시도. 모두 만족 PASS.

### Tests for User Story 3 (RED 단계)

- [ ] T034 [P] [US3] Unit test 작성 in `tests/unit/test_unified_ingest_force.py` — `_check_already_processed(force=True)` 가 `(False, False, False)` 반환 + `_run_transcript_and_fingerprint(force=True)` 호출 시 모든 영상에 대해 transcribe_audio 와 extract_chromaprint_fingerprint 가 호출됨. RED 확인.
- [ ] T035 [P] [US3] Contract test 작성 in `tests/contract/test_collect_ingest_force_contract.py` — contract `collect-ingest-force.md` §1~§4. (a) `tube-scout collect ingest --help` 출력에 `--force` 명시, (b) `--force` 의 Typer type = bool default False, (c) `--force` 없이 호출 시 기존 동작. RED 확인.
- [ ] T036 [P] [US3] Integration test 작성 in `tests/integration/test_ingest_force_full_cycle.py` — fixture archive (US1/US2 완료 상태) + retry_pending.json 에 2 개 실패 entry 시드 → `--force` 호출 → (a) wall clock fresh 처리 범위 (mini 3 mp4 기준 5-10 분), (b) 모든 mtime 갱신, (c) DB row count = 3 유지 (PK 단일성), (d) retry_pending.json 신규 결과로 전체 갱신 (성공 시 entry 제거, 실패 시 추가). RED 확인.

### Implementation for User Story 3 (GREEN 단계)

- [ ] T037 [US3] `collect_ingest_command` 에 `--force` Typer 옵션 추가 in `src/tube_scout/cli/collect.py`. signature: `force: bool = typer.Option(False, "--force", help="멱등 가드 우회 — archive 내 모든 영상의 자막·지문을 강제 재처리. retry_pending.json 은 새 결과로 갱신됨.")`. spec 013 `collect_fingerprint_command` 의 `--force` (cli/collect.py:1990-1994) 시그니처 동일.
- [ ] T038 [US3] `force: bool` 파라미터를 `ingest_unified()` → `_run_transcript_and_fingerprint()` → `_check_already_processed()` 까지 plumb. 각 함수 signature 에 `force: bool = False` (kw-only) 추가.
- [ ] T039 [US3] retry_pending 자동 해소 — `--force` 호출에서 retry_pending 의 모든 entries 가 자동으로 재시도 모집단에 포함되도록 `services/retry_manifest.py` 의 `select_retry_targets` 호출 결과 + 일반 모집단을 합집합 처리 (FR-018D 의 "전체 영상" 의미). 의사코드: `retry_target_ids = set(_rm.select_retry_targets(manifest, max_attempts=5)); raw_ids = set(raw_mp4_map.values()); targets = retry_target_ids | raw_ids` — set union 으로 중복 제거, video_id 순서는 `_retry_mp4` 우선 + 나머지로 retry 우선 처리 유지 (services/unified_ingest.py:362-365 의 기존 sort 패턴 보존). 성공한 영상은 `resolve_successes` 에 의해 자동 제거, 새 실패는 `add_or_update_failures` 에 의해 갱신.
- [ ] T040 [US3] `--force` 호출 시 audit reason `forced_reprocess` 1 row 기록 (contract `collect-ingest-force.md` §5) — `ingest_orchestrator` stage 의 호출 시작 시점 row 에 `reason = "forced_reprocess"` 추가.
- [ ] T041 [US3] T034~T036 3 개 test GREEN 확인 — `uv run pytest tests/unit/test_unified_ingest_force.py tests/contract/test_collect_ingest_force_contract.py tests/integration/test_ingest_force_full_cycle.py -v`.

**Checkpoint**: User Story 3 acceptance scenario (spec.md §USR3 1~3) 모두 통과. SC-018-3 달성. 운영자가 ASR 모델 / chromaprint 옵션 변경 후 명시적 재처리 가능.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: spec 017 quickstart 갱신, 회귀 매트릭스 전수 검증, 22 학과 환산 측정, lint 청결.

- [x] T042 [P] spec 017 quickstart §5 KNOWN LIMITATION 갱신 in `specs/017-takeout-unified-ingest/quickstart.md` — RESOLVED note 추가 완료 (commit 85c2ebd).
- [x] T043 [P] spec 018 quickstart §7 troubleshooting — retry_pending mp4 부재 edge case 1 행 추가. SC-018-6 Rich Table 5×5 구조 코드 검증 (`unified_ingest.py:416-468`), 5 cols (단계/처리/skip/실패/소요 시간), 자막/지문 행 skip 열 정수, 나머지 `-`. walkthrough log → `_workspace/spec018_quickstart_walkthrough.log`.
- [x] T044 [P] ruff 회귀 검증 — 0 violations. 결과 → `_workspace/spec018_ruff_post.log`.
- [x] T045 spec 017 회귀 매트릭스 — 66 passed, 1 pre-existing 실패 (`fingerprint_path` 컬럼 부재, spec 018 regression 없음). 결과 → `_workspace/spec018_regression_spec017.log`.
- [x] T046 spec 016 회귀 매트릭스 — 49 passed, 1 pre-existing 실패 (symlink escape guard, spec 018 regression 없음). 결과 → `_workspace/spec018_regression_spec016.log`.
- [x] T047 spec 011 reader 통합 검증 — `baseline_corpus.py` `data.get()` 패턴으로 분기 없이 소비 가능 (FR-018H PASS). 검증 → `_workspace/spec018_spec011_reader_check.md`.
- [x] T048 fixture 3 mp4 기반 3 회차 walkthrough — integration test 13 passed (first_call + idempotent + force). SC-018-1/2/3 PASS. 간호학과 9 mp4 GPU 실측은 별도 운영 task 이연 → `_workspace/spec018_walkthrough.md`.
- [ ] T049 pyproject 버전 정책 적용 — 현재 `0.6.0.dev0` 유지. 사용자 판단 대기.
- [x] T050 closure note → `_workspace/spec018_closure.md`. idea 시드에 ✅ 완료 마커 추가.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup, T001~T003)**: 의존성 없음. T002/T003 [P] 병렬 가능.
- **Phase 2 (Foundational, T004~T009)**: Phase 1 완료 후 진입. T005/T006 [P] 병렬 가능. T007 은 storage 변경 가능성 있음 → 단독 수행 권장.
- **Phase 3 (US1, T010~T021)**: Phase 2 완료 후 진입. **MVP boundary**.
- **Phase 4 (US2, T022~T033)**: Phase 3 완료 후 진입 (US2 가 US1 의 영구화 산출물에 의존).
- **Phase 5 (US3, T034~T041)**: Phase 4 완료 후 진입 (US3 의 --force semantics 가 US2 의 가드 우회).
- **Phase 6 (Polish, T042~T050)**: Phase 5 완료 후 진입. T042~T044 [P] 병렬 가능.

### User Story Dependencies

- **US1 (P1)**: 독립. Phase 2 만 충족하면 진입 가능. **MVP 산출 가능 — 본 story 만 완성해도 영구화 결함 (결함 A/B) 해소 + spec 011 reader 가 통합 산출물 소비 가능.**
- **US2 (P1)**: **US1 의존** — 영구화가 없으면 가드 평가 자체가 무의미. US1 GREEN 후 진입.
- **US3 (P2)**: **US2 의존** — 가드 우회 로직이 가드 자체에 의존. US2 GREEN 후 진입.

### Within Each User Story

- Test (RED) → Implementation (GREEN) → Refactor (있는 경우) 순.
- RED 단계의 모든 test 는 reasonable failing 상태에서 commit 후 GREEN 단계 진입.
- Implementation task 안에서는 helper → caller → presentation layer 순으로 (예: `_persist_transcript` → `_run_transcript_and_fingerprint` 호출부 → Rich Table layer).

### Parallel Opportunities

- **Phase 1**: T002, T003 [P] — fixture 준비와 ruff baseline 캡처는 독립.
- **Phase 2**: T005, T006 [P] — IdempotencyGuardResult 정의와 audit_writer 어휘 추가는 다른 파일.
- **Phase 3 (US1) RED**: T010, T011, T012, T013 [P] — 4 개 test 파일 모두 다른 파일.
- **Phase 4 (US2) RED**: T022, T023, T024, T025, T026 [P] — 5 개 test 파일 모두 독립.
- **Phase 5 (US3) RED**: T034, T035, T036 [P] — 3 개 test 파일 독립.
- **Phase 6 Polish**: T042, T043, T044 [P] — 다른 파일/명령 셋.

---

## Parallel Example: User Story 1 RED 단계

```bash
# 4 개 failing test 를 병렬로 작성 (서로 다른 파일):
Task: "Unit test in tests/unit/test_unified_ingest_persist.py"
Task: "Unit test in tests/unit/test_unified_ingest_fingerprint_persist.py"
Task: "Contract test in tests/contract/test_transcript_artifact_contract.py"
Task: "Integration test in tests/integration/test_ingest_persist_first_call.py"

# 모두 RED 확인 후 implementation 단계 진입:
uv run pytest tests/unit/test_unified_ingest_persist.py \
              tests/unit/test_unified_ingest_fingerprint_persist.py \
              tests/contract/test_transcript_artifact_contract.py \
              tests/integration/test_ingest_persist_first_call.py -v
# → 4 failing 확인 → T014 ~ T021 진입
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 + Phase 2 완료 (T001 ~ T009).
2. Phase 3 (US1) 완료 (T010 ~ T021) — fresh archive 첫 호출 시 transcript json + DB row 영구화.
3. **STOP and VALIDATE**: T013 + T012 의 fixture 기반 integration test 로 acceptance scenario USR1 1~3 검증.
4. spec 011 reader 가 통합 명령 산출물을 분기 없이 소비 가능함 별도 확인.
5. **MVP 출하 가능 시점** — 본 시점까지만 완료해도 spec 017 의 결함 A/B 해소 + 분리/통합 schema 동치성 확보.

### Incremental Delivery

1. MVP (US1) 출하 → integration 검증 → demo.
2. US2 추가 (T022 ~ T033) → 두 번째 호출 ≤ 2 초 달성 → demo (SC-004 회복 완료).
3. US3 추가 (T034 ~ T041) → 운영자 escape hatch 완비.
4. Polish (T042 ~ T050) → spec 017 quickstart 갱신 + 회귀 매트릭스 + 22 학과 환산 측정 + 최종 closure.

### Parallel Team Strategy (만약 dev-squad 다중 에이전트 운영 시)

- Lead (developer): Phase 2 → US1 main path (T014 ~ T021)
- Test agent: Phase 3/4/5 의 RED 단계 test 작성 (T010~T013 + T022~T026 + T034~T036) — 다른 파일이므로 충돌 없음
- Verification agent (pair-programmer): 각 phase GREEN 확인 시점에 acceptance scenario 매핑 검증 (FR ↔ task ↔ test traceability)
- Adversary agent: Edge case (spec.md §Edge Cases) 가 모든 phase 의 test 매트릭스에 반영되었는지 점검

dev-squad 운영 시에도 본 PATCH 는 surgical scope 라 한 명의 lead 가 순차 진행해도 5-8 시간 안에 완료 가능 (한 학과 실측 walkthrough T048 의 ASR 비용 제외).

---

## Notes

- **TDD non-negotiable (Constitution I)**: 모든 implementation task 진입 전에 그 phase 의 RED 단계 모든 test 가 작성되고 failing 상태에서 commit 되어야 한다. 본 PATCH 의 task ordering 은 이를 강제한다.
- **신규 의존성 0**: 본 PATCH 진행 중 `pyproject.toml` 의 dependency 목록 변경 없음 (T049 의 version bump 결정 외).
- **schema migration 0**: SQLite v4 schema 변경 없음 — T007 의 `INSERT OR REPLACE` 확인은 SQL pattern 변경이며 column 변경이 아님.
- **commits**: 각 task 별 또는 phase boundary 별 conventional commit. 예: `feat(spec018): T014 _persist_transcript atomic write 구현`. T045/T046 의 회귀 매트릭스 commit 분리 권장 (bisect 추적성).
- **회귀 안전**: spec 017 의 SC-001/SC-005/C-1 + spec 016 의 SC-001~SC-009 모두 보존 (SC-018-7). T045 / T046 가 회귀 매트릭스 전수 GREEN 확인.
- **22 학과 측정 부담**: SC-018-4 는 1 학과 측정 + 선형 환산으로 충족 (Assumption 명시). T048 의 실측은 간호학과 1 회만 의무, 나머지 학과 측정은 운영 단계에서 별도 진행.
