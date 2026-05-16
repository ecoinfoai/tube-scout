---
description: "Task list for spec 016 — Takeout 적재 모듈 재작성 및 운영자 등록 흐름 정합화"
---

# Tasks: Takeout 적재 모듈 재작성 및 운영자 등록 흐름 정합화

**Input**: Design documents from `/home/kjeong/localgit/tube-scout/specs/016-takeout-ingest-rebuild/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: MANDATORY for this spec — Constitution I (TDD, NON-NEGOTIABLE) + SC-008 (결함 8개 회귀 테스트 의무). 모든 user story phase 에서 RED → GREEN → REFACTOR 순서 강제.

**Organization**: spec.md 의 4 user story (US1 P1 적재 / US2 P1 admin / US3 P2 멱등 / US4 P2 ASR 단일) 별 phase + Setup + Foundational + Polish.

## Format: `[TaskID] [P?] [Story?] Description with file path`

- **[P]**: 같은 phase 안에서 다른 파일을 건드리므로 병렬 실행 가능
- **[US1]~[US4]**: spec.md 의 user story 1~4 에 매핑
- 모든 경로는 repo root `/home/kjeong/localgit/tube-scout/` 기준 상대경로
- TDD: 각 user story 의 RED (테스트) 작업이 GREEN (구현) 보다 먼저 배치되며, RED task 는 반드시 failing 으로 확인 후 GREEN 진입

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 환경 동기화 + 회귀 RED baseline 확인. PATCH 범위라 신규 모듈/디렉토리 0건.

- [x] T001 devShell 진입 + `uv sync --extra asr --extra dev` 동기화 확인 (faster-whisper 1.2.1 + CTranslate2 4.7.1 + pytest 동시 설치 확인)
- [x] T002 현재 master(v0.5.0) 상태의 결함 차단 지점 baseline 확인 — `tube-scout collect takeout --takeout-dir data/takeout-20260511T130817Z-3-001 --channel nursing --dry-run` 실행 후 `Missing columns in 채널.csv: {'채널 이름'}` 메시지로 첫 1초 안에 exit 1 차단되는지 확인 (회귀 RED 시작 신호)
- [x] T003 [P] `pyproject.toml` 의 `version = "0.5.1.dev0"` 유지 확인 (이미 spec 016 진입 시 변경됨, 본 task 는 회귀 방지 확인)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 모든 user story 가 의존하는 공통 변경. Audit 어휘 + privacy 매핑 + 모델 validator 강화. 본 phase 완료 전에는 어떤 user story task 도 진행 불가.

**⚠️ CRITICAL**: 본 phase 의 T004~T007 이 모두 GREEN 이 되어야 US1~US4 진입 가능.

- [x] T004 [P] `src/tube_scout/services/audit_writer.py` 의 row 컬럼 셋에 `raw_value`, `elapsed_ms` 2 컬럼 추가 (FR-023, Cross-Spec Boundary B-5). 기존 8 컬럼은 보존, append-only 보장 유지.
- [x] T005 [P] `src/tube_scout/services/takeout_ingest.py` 모듈 상단에 `_PRIVACY_MAPPING: dict[str, Literal['public','unlisted','private']] = {'공개':'public', '일부 공개':'unlisted', '비공개':'private'}` 상수 추가 (R-4, FR-005). 추후 GREEN task 에서 호출.
- [x] T006 [P] `src/tube_scout/models/content.py` 의 `ChannelMetadata` 모델에 `title` 필수화 validator + `privacy_status` enum 제약 (`Literal['public','unlisted','private'] | None`) 추가 (FR-006).
- [x] T007 [P] `src/tube_scout/models/content.py` 의 `VideoMetadata` 모델에 `title` 필수화 validator + `privacy_status` enum 제약 + `duration_seconds` 음수 거부 추가 (FR-006, data-model.md §VideoMetadata).

**Checkpoint**: 4 task 모두 GREEN 이 되면 user story 진입.

---

## Phase 3: User Story 1 — Takeout archive 적재 (Priority: P1) 🎯 MVP

**Goal**: `tube-scout collect takeout --takeout-dir <path> --channel <alias>` 이 간호학과 9 영상 + 채널 전체 2554 메타 archive 를 처음부터 끝까지 0 exit code 로 적재. mp4 부재 영상 2545 개는 audit `no_mp4_in_archive` 로 기록.

**Independent Test**: Integration test `tests/integration/test_takeout_e2e_nursing.py` 실행 후 (1) SQLite `video_metadata` 행 = 2554, (2) `privacy_status` NULL/한글 행 = 0, (3) audit row 9 success + 2545 skip(no_mp4) + 26 skip(ignored_csv) 분포 확인.

### Tests for User Story 1 (RED — 모두 failing 으로 확인 후 GREEN 진입)

- [x] T008 [P] [US1] `tests/unit/test_takeout_ingest.py` 신규 — 결함 3 + 결함 12 회귀: `채널.csv` 의 실측 헤더 (`채널 ID, 채널 국가, 채널 태그 1, 채널 제목(원본), 채널 공개 상태`) 로 ChannelMetadata 생성 시 `title='부산보건대 간호학과'`, `country='KR'` 가 채워지는지 검증 (FR-001). **추가로** — 같은 archive 에 대해 `--takeout-dir` 가 archive root (`Takeout/` 부모) 와 `Takeout/` 폴더 자체 둘 다일 때 모두 정상 파싱되는지 회귀 (결함 12, FR-001 후반부).
- [x] T009 [P] [US1] `tests/unit/test_takeout_ingest.py` 추가 — 결함 4 회귀: `동영상.csv` 의 실측 헤더 11 컬럼으로 VideoMetadata 2554 행 생성 시 `title` 은 `동영상 제목(원본)` 컬럼에서, `language` 는 `동영상 오디오 언어` 컬럼에서, `category` 는 `동영상 카테고리` 컬럼에서 가져옴을 확인 + `동영상 URL` 컬럼 부재가 raise 를 일으키지 않음 (FR-003)
- [x] T010 [P] [US1] `tests/unit/test_takeout_ingest.py` 추가 — 결함 6 회귀: `채널.csv` 에 `채널 제목(원본)` 컬럼이 부재한 가짜 csv 로 `_parse_channel_csv()` 호출 시 명시적 `ValueError` raise (silent None 금지) (FR-006)
- [x] T011 [P] [US1] `tests/unit/test_privacy_mapping.py` 신규 — 결함 7 회귀: `_PRIVACY_MAPPING` 으로 `비공개→private`, `일부 공개→unlisted`, `공개→public` 매핑 + 알 수 없는 한글 값(예: `예약 공개`) 한 행 만나면 그 row 만 skip + audit `reason=unknown_privacy_value, raw_value=예약 공개` 기록 + 다른 영상은 적재 계속 (FR-005, R-4)
- [x] T012 [P] [US1] `tests/unit/test_takeout_ingest.py` 추가 — 결함 8 회귀: `동영상 메타데이터/` 폴더에 `동영상.csv` + `동영상(1).csv` + `동영상 녹화.csv` + `동영상 텍스트.csv` 4 파일이 있을 때 적재 함수가 첫 2 파일만 영상 메타로 인식 + 뒤 2 파일은 audit `result=skip, reason=ignored_by_policy` 로 기록 (FR-002, FR-011)
- [x] T013 [P] [US1] `tests/unit/test_takeout_ingest.py` 추가 — multi-line quoted 영상 제목 (쉼표·줄바꿈·따옴표 포함) 정확 파싱 회귀: 임의 20 행 표본의 DB `title` 필드 값이 원본 csv 의 `동영상 제목(원본)` 값과 글자 단위 일치 (FR-010, SC-007)
- [x] T014 [P] [US1] `tests/unit/test_takeout_ingest.py` 추가 — FR-022 회귀: IngestResult 에 `mp4_present_count`, `mp4_absent_count`, `elapsed_seconds` 3 필드가 양수로 출력 + 합산이 `total_videos` 와 일치
- [x] T015 [P] [US1] `tests/contract/test_collect_takeout_contract.py` 신규 — `contracts/collect-takeout.md` 의 8 에러 케이스 전체 (alias 미등록, takeout_dir 부재, 채널.csv 부재, 동영상*.csv 0개, 필수 컬럼 부재, alias 비정합) 가 정확한 stderr 메시지 + exit code 1 로 종료
- [x] T016 [US1] `tests/integration/test_takeout_e2e_nursing.py` 신규 — SC-001/002/007 cross-stack 검증: 간호학과 archive 적재 후 SQLite `video_metadata` 행 = 2554, `privacy_status` NULL/한글 행 = 0, mp4 매칭 9 success, audit row 분포 (9+2545+26+0) 확인. **Depends on**: T008~T015 (RED 작성 완료, failing 확인) + T017~T028 (GREEN 완료, passing 전환). 즉 본 task 는 phase 3 의 가장 마지막 RED→PASS 게이트로, T029 (REFACTOR) 진입 전 마지막 검증.

### Implementation for User Story 1 (GREEN)

- [x] T017 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `_parse_channel_csv()` 재작성 — `_CHANNEL_CSV_REQUIRED` 를 `{"채널 ID", "채널 제목(원본)"}` 으로 갱신, `title=row["채널 제목(원본)"]`, `country=row.get("채널 국가","")` 로 변경 (T008, T010 GREEN). **추가로** — `parse_takeout_csv_metadata()` 시작부에 `yt_dir` 자동 탐색 로직 추가: `yt_dir = takeout_dir / "Takeout" / "YouTube 및 YouTube Music"`, `if not yt_dir.exists(): yt_dir = takeout_dir / "YouTube 및 YouTube Music"`, `if not yt_dir.exists(): raise FileNotFoundError(f"Neither '<takeout_dir>/Takeout/YouTube 및 YouTube Music/' nor '<takeout_dir>/YouTube 및 YouTube Music/' exists")` (결함 12, FR-001 후반부).
- [x] T018 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `_VIDEO_CSV_REQUIRED` 상수를 실측 11 컬럼 헤더 기준으로 갱신 — `{"동영상 ID", "동영상 제목(원본)", "근사치 길이(밀리초)", "채널 ID", "개인 정보 보호", "동영상 생성 타임스탬프"}` 정도의 최소 셋 (T009 GREEN)
- [x] T019 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `parse_takeout_csv_metadata()` 내부 row→VideoMetadata 매핑 로직 재작성 — `title=row["동영상 제목(원본)"]`, `language=row["동영상 오디오 언어"]`, `category=row["동영상 카테고리"]`, `privacy_status=_PRIVACY_MAPPING.get(row["개인 정보 보호"].strip())`, `created_at=row["동영상 생성 타임스탬프"]` (T009, T011 GREEN)
- [x] T020 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `parse_takeout_csv_metadata()` 에서 알 수 없는 한글 privacy 값 만나면 그 row 만 skip + `_pending_unknown_privacy_rows: list[dict]` 에 (video_id, raw_value) 누적 (audit 는 ingest_takeout() 단계에서 한 번에 기록) (T011 GREEN)
- [x] T021 [US1] `src/tube_scout/services/takeout_ingest.py` 의 meta glob 패턴을 `meta_dir.glob("동영상.csv")` + `meta_dir.glob("동영상(*).csv")` 두 union 으로 변경 (T012 GREEN, R-3)
- [x] T022 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `ingest_takeout()` 에서 `_is_ignored()` 적용 범위를 메타 디렉토리 내부 파일까지 확장 — 무시된 csv 한 개당 audit `result=skip, reason=ignored_by_policy` 한 행 (T012 GREEN, FR-011)
- [x] T023 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `ingest_takeout()` 에서 `_pending_unknown_privacy_rows` 를 순회하며 audit `result=skip, reason=unknown_privacy_value, raw_value=<원본>` 기록 (T011 GREEN, FR-005)
- [x] T024 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `IngestResult` 모델 (pydantic) 에 `mp4_present_count: int = 0`, `mp4_absent_count: int = 0`, `elapsed_seconds: float = 0.0` 3 필드를 **Pydantic 기본값 명시** 로 추가 (T014 GREEN, FR-022, B-3). backward compat — 기존 caller (예: spec 008 web UI 의 admin job runner) 가 새 필드를 enumerate 안 해도 정상 작동.
- [x] T025 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `ingest_takeout()` 시작 시 `_t_start = time.monotonic()`, 종료 시 `elapsed_seconds = time.monotonic() - _t_start` 측정하여 IngestResult 에 채움 (T014 GREEN, FR-022, R-10)
- [x] T026 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `ingest_takeout()` 의 mp4 매칭 루프 후 메타 영상 중 mp4 부재 영상 (`video_id ∉ mp4_video_id_map.values()`) 에 대해 audit `result=skip, reason=no_mp4_in_archive` 기록 + `mp4_absent_count` 증가 (T014, T016 GREEN, FR-008)
- [x] T027 [US1] `src/tube_scout/services/takeout_ingest.py` 의 `csv.DictReader` 호출이 `newline=""` 명시 (Python `csv` 모듈 multi-line quoted 지원 보장) — 기존 코드 확인 + 필요시 보강 (T013 GREEN, FR-010)
- [x] T028 [US1] `src/tube_scout/services/takeout_ingest.py` 의 모든 audit row 호출에 `elapsed_ms` 인자 전달 (T014 GREEN, FR-023, B-5)

### Refactor for User Story 1

- [x] T029 [US1] `src/tube_scout/services/takeout_ingest.py` 전체에 ruff check + 타입 어노테이션 점검 (Constitution III). `_parse_channel_csv()` 와 `parse_takeout_csv_metadata()` 의 docstring 을 Google-style 로 보강. 모든 public 함수에 `: <return-type>` 어노테이션 확인.

**Checkpoint**: T008~T015 RED → T017~T028 GREEN → T029 REFACTOR 완료 시점에 SC-001/002/005/007/009 검증 가능. **MVP 완성** — 이 시점에 spec 016 의 가장 차단되어 있던 흐름이 풀린다.

---

## Phase 4: User Story 2 — Takeout 단독 신규 학과 등록 (Priority: P1)

**Goal**: `tube-scout admin add-department --alias nursing2 --display "테스트학과"` 만으로 OAuth env 없이 학과 등록 + `admin list` 가 양쪽 등록부 union 출력 + 비정합 alias 감지.

**Independent Test**: 환경변수 `TUBE_SCOUT_*` 모두 미설정 상태에서 `admin add-department` exit 0 + departments.json 에 OAuth env 3 필드 null 로 atomic 저장 + `admin list` 가 새 alias 표시.

### Tests for User Story 2 (RED)

- [x] T030 [P] [US2] `tests/unit/test_admin_add_department.py` 신규 — 결함 2/11 회귀: 환경변수 미설정 상태에서 `--alias nursing2 --display 테스트학과` 만 명시했을 때 exit 0 + departments.json 의 새 row 의 OAuth env 3 필드가 모두 null (FR-012, contracts/admin-add-department.md 조합 A)
- [x] T031 [P] [US2] `tests/unit/test_admin_add_department.py` 추가 — FR-013 회귀: 옵션 일부만 명시 (`--channel-id-env` 만) 시 exit 1 + stderr `"OAuth env 옵션은 3개 모두 명시되거나 모두 생략되어야 합니다"` (조합 C)
- [x] T032 [P] [US2] `tests/unit/test_admin_add_department.py` 추가 — spec 003 호환 회귀: 3 env 모두 명시 + 모두 정의 시 기존 OAuth consent 흐름 작동 + 토큰 파일 0600 발급 (조합 B)
- [x] T033 [P] [US2] `tests/unit/test_admin_add_department.py` 추가 — FR-016 회귀: alias 가 다른 등록부에 이미 다른 channel_id 로 있는 상태에서 add-department 실행 시 `DuplicateAliasError` 또는 동등한 실패로 종료
- [x] T034 [P] [US2] `tests/unit/test_admin_list_union.py` 신규 — 결함 1 회귀: channels.json 에 nursing 만, departments.json 에 nursing2 만 있을 때 `admin list` 가 2 행 모두 출력 + source 컬럼 정확 (FR-014, contracts/admin-list.md)
- [x] T035 [P] [US2] `tests/unit/test_admin_list_union.py` 추가 — FR-015 회귀: 같은 alias 가 두 등록부에 다른 channel_id 로 있을 때 `consistency=mismatch` 표시 + stderr `WARNING: alias 'nursing' mismatch (...)` 라인 + `--json` 출력의 `consistency` 필드 + `admin list` 자체는 exit 0
- [x] T036 [P] [US2] `tests/unit/test_admin_list_union.py` 추가 — FR-015 후반부 회귀: 비정합 alias 가 collect/analyze/report 등 분석 명령에 사용되면 exit 1 + 명시적 stderr 메시지
- [x] T037 [P] [US2] `tests/contract/test_admin_add_department_contract.py` 신규 — contracts/admin-add-department.md 의 입력/출력/exit code 매트릭스 전체 검증
- [x] T038 [P] [US2] `tests/contract/test_admin_list_contract.py` 신규 — contracts/admin-list.md 의 Rich table + JSON 출력 형식 + stderr WARNING 흐름 검증

### Implementation for User Story 2 (GREEN)

- [x] T039 [US2] `src/tube_scout/cli/admin.py` 의 `add_department()` 시그니처 변경 — `--channel-id-env`, `--client-secret-env`, `--api-key-env` 3 옵션을 `typer.Option(None, ...)` 로 optional 화 (T030, T031, T032 GREEN, FR-012)
- [x] T040 [US2] `src/tube_scout/cli/admin.py` 의 `add_department()` 함수 내부 — 3 env 옵션의 명시 여부를 카운트하여 (a) 3 개 모두 None: OAuth consent skip, (b) 3 개 모두 비-None: 기존 흐름 (검증 + consent), (c) 일부만 비-None: 명시적 에러로 종료 + audit `result=failure, detail=partial-oauth-envs` (T031 GREEN, FR-013)
- [x] T041 [US2] `src/tube_scout/cli/admin.py` 의 `add_department()` 함수 — alias 가 channels.json 또는 다른 departments.json entry 에 이미 다른 channel_id 로 있으면 `DuplicateAliasError` 와 동등한 에러로 종료 (T033 GREEN, FR-016)
- [x] T042 [US2] `src/tube_scout/web/models.py` (또는 `web/repo/`) 의 `Department` 모델의 `channel_id_env`, `client_secret_env`, `api_key_env` 3 필드를 `str | None` 으로 변경 + all-or-nothing model_validator 추가 (T031 GREEN, FR-013, data-model.md §Department)
- [x] T043 [US2] `src/tube_scout/cli/admin.py` 의 `list_departments()` 재작성 — channels.json 과 departments.json 두 등록부 union 을 계산하여 RegistryUnionRow list 생성, Rich table 에 `alias / display_name / channel_id / source / consistency` 5 컬럼 출력 (T034 GREEN, FR-014, data-model.md §RegistryUnionRow)
- [x] T044 [US2] `src/tube_scout/cli/admin.py` 의 `list_departments()` 의 consistency 판별 로직 — source=both 인 alias 에 대해 channels.json 의 channel_id 와 departments.json 의 channel_id_env 가 가리키는 환경변수 값을 비교 (둘 중 하나라도 빈 값이거나 불일치면 mismatch) (T035 GREEN, FR-015, contracts/admin-list.md §"Consistency 판별 로직")
- [x] T045 [US2] `src/tube_scout/cli/admin.py` 의 `list_departments()` 가 비정합 alias 발견 시 stderr 에 `WARNING: alias '<X>' mismatch (channels.json=<id1>, departments.json=<id2>)` 라인 출력 + `--json` 출력의 각 row 에 `"consistency"` 필드 포함 + 명령 자체는 exit 0 (T035 GREEN, FR-015)
- [x] T046 [US2] `src/tube_scout/cli/admin.py` 의 `list_departments()` 에 `--json` 옵션 추가 (`typer.Option(False, "--json", ...)`) — Rich table 대신 stdout 에 RegistryUnionRow list 의 JSON 배열 직렬화 (T037, T038 GREEN, contracts/admin-list.md)
- [x] T047 [US2] `src/tube_scout/cli/collect.py` 또는 `src/tube_scout/cli/analyze.py` 또는 공통 alias 검증 헬퍼에 — 분석 명령(`collect`, `analyze`, `report`) 진입 시 alias 비정합 검사 + mismatch 시 exit 1 + stderr `ERROR: alias '<X>' mismatch between channels.json and departments.json — analysis commands blocked. Run 'tube-scout admin list --json' to inspect.` (T036 GREEN, FR-015 후반부)

### Refactor for User Story 2

- [x] T048 [US2] `src/tube_scout/cli/admin.py` 와 `src/tube_scout/web/models.py` 의 변경 부분에 ruff + 타입 + Google-style docstring 점검 (Constitution III).

**Checkpoint**: T030~T038 RED → T039~T047 GREEN → T048 REFACTOR 완료 시점에 SC-003/004 검증 가능. US1 + US2 = spec 016 의 P1 두 user story 모두 완성.

---

## Phase 5: User Story 3 — 다중 archive part 누적 적재 (Priority: P2)

**Goal**: 한 학과의 여러 archive part 를 순서대로 풀어서 같은 alias 에 적재 시 멱등성 보장 + 새 mp4 본체만 symlink 추가.

**Independent Test**: 같은 archive 를 두 디렉토리에 풀고 두 번 `collect takeout` 실행 시 두 번째 `new_videos=0`, mp4 symlink 변화 없음, SQLite 행 수 변화 없음. audit CSV 는 append-only 로 두 실행분 누적.

### Tests for User Story 3 (RED)

- [x] T049 [P] [US3] `tests/integration/test_idempotent_part_load.py` 신규 — SC-005 회귀: 같은 archive 두 번 적재 시 두 번째 IngestResult.new_videos=0, mp4_added=0, SQLite `video_metadata` 행 수 변화 없음 (FR-009)
- [x] T050 [P] [US3] `tests/integration/test_idempotent_part_load.py` 추가 — part 1 적재 후 part 2 에 동일 video_id + 다른 title 인 가짜 archive 로 두 번째 적재 시 DB 의 title 이 part 1 의 값으로 유지 (first-write-wins, R-8) + audit 에 별도 conflict row 없음
- [x] T051 [P] [US3] `tests/integration/test_idempotent_part_load.py` 추가 — part 1 적재 후 part 2 에 part 1 에 없던 video_id 가 추가된 가짜 archive 적재 시 `new_videos > 0`, 새 video_id 의 mp4 symlink 만 추가 (FR-020)

### Implementation for User Story 3 (GREEN)

- [x] T052 [US3] `src/tube_scout/services/takeout_ingest.py` 의 `_persist_metadata()` 가 `INSERT OR IGNORE` 사용 + UPSERT 절이 channel_metadata 의 `takeout_root_hint` 와 `ingested_at` 만 갱신함을 확인 (T049, T050 GREEN, R-8). 필요시 video_metadata 의 INSERT OR IGNORE 흐름이 first-write-wins 임을 코드 주석으로 명시. (코드 변경 최소 — 기존 spec 013 흐름이 이미 first-write-wins 이므로 검증 위주)
- [x] T053 [US3] `src/tube_scout/services/takeout_ingest.py` 의 `assemble_channel_work_dir()` 가 `dest.exists() or dest.is_symlink()` 분기로 멱등 보장하는지 확인 (T051 GREEN, FR-020). 새 mp4 만 symlink 추가 + 기존 symlink 유지.

### Refactor for User Story 3

- [x] T054 [US3] `services/takeout_ingest.py` 의 멱등성 주석 명확화 — `_persist_metadata()` 와 `assemble_channel_work_dir()` 의 docstring 에 first-write-wins 정책 + 멱등 보장 한 줄 추가.

**Checkpoint**: T049~T051 RED → T052~T053 GREEN → T054 REFACTOR 완료 시점에 US3 완성. spec 013 의 멱등성을 spec 016 의 명시적 회귀로 보강.

---

## Phase 6: User Story 4 — 자막 부재 영상의 ASR 단일 경로 (Priority: P2)

**Goal**: `tube-scout collect transcripts --channel nursing` 이 옵션 없이 ASR 단일 경로로 동작 + `--source youtube` exit 2 + 명확한 deprecation 메시지.

**Independent Test**: 9 mp4 symlink 가 있는 상태에서 `collect transcripts --channel nursing` 옵션 없이 호출 시 9 영상 ASR + `--source youtube` 호출 시 exit 2 + stderr "YouTube 자막 source 는 2026-05-12 결정으로 폐기" 메시지.

### Tests for User Story 4 (RED)

- [x] T055 [P] [US4] `tests/integration/test_asr_single_source.py` 신규 — FR-017 회귀: `--source` 옵션 미명시 시 ASR 자동 선택, 9 mp4 ASR 완료 (mock 또는 medium 모델 짧은 mp4)
- [x] T056 [P] [US4] `tests/integration/test_asr_single_source.py` 추가 — FR-018 회귀: `--source youtube` 명시 시 exit 2 + stderr 메시지 "2026-05-12 결정으로 폐기" 포함 + ASR 자체가 invoke 되지 않음
- [x] T057 [P] [US4] `tests/integration/test_asr_single_source.py` 추가 — FR-019 회귀: mp4 부재 영상에 대해 ASR skip + audit `result=skip, reason=no_mp4_in_archive` 기록
- [x] T058 [P] [US4] `tests/contract/test_collect_transcripts_contract.py` 신규 — contracts/collect-transcripts.md 의 exit code 매트릭스 (0/1/2) + source 옵션 분기 전체 검증

### Implementation for User Story 4 (GREEN)

- [x] T059 [US4] `src/tube_scout/cli/collect.py` 의 `transcripts` 명령 시그니처 변경 — `--source` 옵션의 default value 를 `asr` 로 명시 (이미 그럴 수 있으나 회귀 방지를 위해 확인) (T055 GREEN, FR-017)
- [x] T060 [US4] `src/tube_scout/cli/collect.py` 의 `transcripts` 명령 본문에 `--source youtube` deprecation 분기 추가 — 명시 시 stderr `ERROR: --source youtube 는 2026-05-12 결정으로 폐기되었습니다. Takeout 단독 운영 모델에서는 자막을 faster-whisper ASR 로 직접 생성합니다. --source asr 가 기본값이므로 옵션을 생략하거나 명시적으로 --source asr 를 사용하세요.` 출력 + `raise typer.Exit(code=2)` (T056 GREEN, FR-018)
- [x] T061 [US4] `src/tube_scout/cli/collect.py` 또는 `services/asr.py` 흐름에서 mp4 본체가 부재한 video_id 에 대해 ASR 단계 자체를 invoke 하지 않고 audit `result=skip, reason=no_mp4_in_archive, elapsed_ms=0` 기록 (T057 GREEN, FR-019)

### Refactor for User Story 4

- [x] T062 [US4] `src/tube_scout/cli/collect.py` 의 `transcripts` 분기 코드에 ruff + 타입 + docstring 점검. deprecation 메시지가 Korean prose (사용자 메모리 `feedback_response_style.md`) 인지 확인.

**Checkpoint**: T055~T058 RED → T059~T061 GREEN → T062 REFACTOR 완료 시점에 US4 완성. spec 016 의 4 user story 모두 GREEN.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 측정 baseline + 정량 SLA 추가 + 문서화 + 전체 회귀 매트릭스 + lint/type 마무리.

- [x] T063 [P] Performance baseline 측정 — 본 작업 머신 (RTX 3060 + 표준 PC) 에서 `tube-scout collect takeout --takeout-dir data/takeout-20260511T130817Z-3-001 --channel nursing --dry-run` 의 elapsed_seconds 3 회 평균 측정. 같은 명령의 실적재 (dry-run 제거) 도 3 회 평균 측정. (R-10, SC-009)
- [x] T064 [P] T063 결과 기반으로 `specs/016-takeout-ingest-rebuild/plan.md` 의 §"Performance Goals" 와 `specs/016-takeout-ingest-rebuild/quickstart.md` 의 운영자 체크리스트에 정량 SLA 추가 — 예: "9 mp4 + 2554 메타 archive 의 dry-run 적재가 본 작업 머신에서 N 초 이내" (N = T063 측정값 × 1.5 안전 마진).
- [x] T065 [P] `specs/016-takeout-ingest-rebuild/quickstart.md` §1.2 의 분할 단위 (`동영상.csv` + `동영상(1)~(N).csv` = 200 영상/csv × 13 파일) + §1.3 의 다중 archive part 흐름 문서화 검증 (FR-021).
- [x] T066 [P] `CLAUDE.md` 의 "Active Technologies" / "Recent Changes" 자동 갱신 결과 확인 + 필요시 spec 016 의 변경 요지를 한 줄 보강 (지금까지 자동 갱신만 됨).
- [x] T067 회귀 매트릭스 전체 실행 — `uv run pytest tests/unit/test_takeout_ingest.py tests/unit/test_admin_add_department.py tests/unit/test_admin_list_union.py tests/unit/test_privacy_mapping.py tests/integration/test_takeout_e2e_nursing.py tests/integration/test_idempotent_part_load.py tests/integration/test_asr_single_source.py tests/contract/ -v`. SC-001/002/003/004/005/006/007/008/009 9 개 모두 PASS 확인. 추가로 `tests/integration/test_v4_schema_invariant.py` 신규 — 마이그레이션 후 `PRAGMA user_version=4` + 5 tables (`channel_metadata`, `video_metadata`, `processing_status`, `quality_results`, `comparison_results`) 의 컬럼셋 schema diff 가 master(v0.5.0) 의 sqlite_master 스냅샷과 글자 단위 일치함을 검증 (Cross-Spec Boundary B-4 보존).
- [x] T068 ruff check + 타입 검사 + pyproject.toml `version = "0.5.1.dev0"` 유지 확인.
- [x] T069 운영자 quickstart 매뉴얼 §5 체크리스트 9 개 항목 모두 실측 확인 (간호학과 9 영상 archive 로 사용자가 처음부터 끝까지 따라하는 시나리오).
- [x] T070 git status 점검 + spec.md + plan.md + research.md + data-model.md + contracts/ + quickstart.md + tasks.md + 코드 변경 5 파일 + 테스트 신규 8 파일이 모두 commit 대상에 들어가 있는지 확인 (Cross-Spec Boundary B-3~B-5 보존 유지).

---

## Dependencies (Phase / User Story 완료 순서)

```text
Phase 1 Setup (T001~T003)
       │
       ▼
Phase 2 Foundational (T004~T007)  ← 모든 user story 의 blocking prerequisite
       │
       ▼
Phase 3 US1 RED→GREEN→REFACTOR (T008~T029)  🎯 MVP 진입점
       │
       │ (US2 는 US1 에 독립적이라 병렬 가능, 단 Phase 2 완료가 prerequisite)
       ▼
Phase 4 US2 RED→GREEN→REFACTOR (T030~T048)  ← US1 과 병렬 가능
       │
       ▼
Phase 5 US3 RED→GREEN→REFACTOR (T049~T054)  ← US1 의 ingest_takeout() GREEN 후
       │
       ▼
Phase 6 US4 RED→GREEN→REFACTOR (T055~T062)  ← US1 의 audit/mp4 부재 흐름 GREEN 후
       │
       ▼
Phase 7 Polish (T063~T070)  ← 모든 user story GREEN 후
```

### 병렬 실행 후보 (Phase 안에서 [P] 표시된 task 끼리)

- **Phase 2 Foundational**: T004 (audit_writer) ∥ T005 (privacy mapping 상수) ∥ T006 (ChannelMetadata validator) ∥ T007 (VideoMetadata validator) — 모두 다른 파일 또는 다른 모델, 의존성 없음.
- **Phase 3 US1 RED**: T008~T015 8 개가 모두 다른 test file 또는 다른 test method 이므로 병렬. T016 (integration) 만 unit/contract 가 모두 GREEN 이 된 다음.
- **Phase 3 US1 GREEN**: T017~T028 12 개가 같은 `takeout_ingest.py` 의 다른 함수/상수를 건드림 → **순차 실행 권장** (병렬 시 충돌). 단 T024 (`IngestResult` 모델), T028 (`audit_writer` 호출 인자 추가) 는 다른 파일 또는 다른 module 이라 일부 병렬 가능.
- **Phase 4 US2 RED**: T030~T038 9 개가 모두 다른 test file → 병렬.
- **Phase 4 US2 GREEN**: T039~T047 가 `cli/admin.py` 와 `web/models.py` 두 파일에 분산 → 같은 파일끼리는 순차, 다른 파일은 병렬.
- **Phase 5 US3 RED**: T049~T051 3 개가 같은 test file → 순차 (같은 파일의 다른 method).
- **Phase 6 US4 RED**: T055~T058 4 개가 다른 test file/method → 병렬.
- **Phase 7 Polish**: T063~T066 4 개가 측정/문서/검토라 병렬. T067~T070 는 검증 흐름이라 순차.

---

## Implementation Strategy

### MVP scope (P1 user story 2 개)

- **MVP 진입**: T001~T029 (Setup + Foundational + US1) 완료 시점. 이 시점에 가장 차단되어 있던 적재 흐름 (SC-001/002/005/007/009) 이 풀린다.
- **MVP 완성**: T001~T048 (Setup + Foundational + US1 + US2). 이 시점에 spec 016 의 P1 두 user story (적재 + admin) 모두 완성. SC-001/002/003/004/005/007/009 가 PASS.

### Incremental delivery

| 단계 | 완료 task | 제공 가치 |
|---|---|---|
| Step 1 (1~2 일) | T001~T007 | 환경 동기화 + Foundational. 코드 변경은 없지만 모든 user story 진입 가능. |
| Step 2 (2~3 일) | T008~T029 (US1) | 🎯 MVP — Takeout 적재가 처음부터 끝까지 작동. 사용자가 9 영상 archive 적재 후 SQLite 에 2554 행 확인 가능. |
| Step 3 (1~2 일) | T030~T048 (US2) | 신규 학과 등록이 OAuth 없이 작동 + `admin list` 가 false-negative 없이 union 출력. |
| Step 4 (1 일) | T049~T054 (US3) | 다중 archive part 누적 적재 멱등성 회귀로 검증. |
| Step 5 (1 일) | T055~T062 (US4) | ASR 단일 경로로 분기 단순화. `--source youtube` 차단. |
| Step 6 (0.5 일) | T063~T070 | Performance baseline 측정 + 정량 SLA + 문서 + 전체 회귀 + ruff/type. |

### TDD enforcement

각 user story 안에서 **RED task 가 GREEN task 보다 먼저** 배치되어 있다. 운영 규칙:

1. RED task 에 해당하는 test 를 작성하고 `uv run pytest <test_file> -v` 가 **failing** 임을 확인 (Constitution I).
2. failing 을 확인하지 못한 채 GREEN 으로 진입하면 test 가 자기 자신을 검증하지 못한다 (false positive). 즉 모든 RED task 의 종료 조건 = pytest 가 실제로 fail 함을 단말에서 확인.
3. GREEN task 후 같은 test 가 PASS 로 전환되는 것을 단말에서 확인.
4. REFACTOR 단계에서 ruff / 타입 / docstring 점검 후 test 가 여전히 PASS 임을 확인.

### Cross-Spec Boundary 유지 (Constitution VII)

본 spec 의 모든 코드 변경은 spec.md §"Cross-Spec Boundaries" 의 B-1 ~ B-8 보장을 보존한다. tasks 안의 각 GREEN task 가 어느 boundary 를 건드리는지:

- B-1 (channels.json): T043, T044 (read-only union 소비)
- B-2 (departments.json): T042 (Department 모델 nullable + validator), T043 (union union)
- B-3 (ingest_takeout 시그니처): T024, T025 (IngestResult 필드 추가만, 시그니처 보존)
- B-4 (SQLite v4 스키마): 모든 task — 스키마 변경 없음 확인이 T067 회귀 매트릭스에 포함
- B-5 (audit CSV): T004 (Foundational), T021 (raw_value 컬럼), T028 (elapsed_ms 인자)
- B-6 (`--source` enum): T059, T060 (youtube 차단, asr 기본)
- B-7 (agenix env): T039, T040 (optional 화, 일부 명시 검증)
- B-8 (data/{alias}/ 디렉토리): T053 (멱등 symlink 보장)

T067 회귀 매트릭스 완료 시점에 8 개 boundary 가 모두 깨지지 않았음을 검증.

---

## Validation Checklist (tasks 작성자 자가 검증)

- [x] 모든 task 가 `- [ ] T### [P?] [US?] Description with file path` 형식 준수
- [x] Setup phase (T001~T003) 와 Polish phase (T063~T070) 에는 [US] 라벨 없음
- [x] Foundational phase (T004~T007) 에는 [US] 라벨 없음 — 모든 user story 의 공통 prerequisite
- [x] User story phase (T008~T062) 의 모든 task 에 [US1]/[US2]/[US3]/[US4] 라벨
- [x] 각 task 에 파일 절대경로 또는 명확한 repo-root 상대경로 명시
- [x] 병렬 가능 task 에 [P] 표시 (다른 파일 또는 의존성 없음)
- [x] 각 user story phase 가 RED → GREEN → REFACTOR 순서
- [x] SC-001~009 9 개 success criteria 가 모두 적어도 하나의 task 로 검증됨
- [x] FR-001~023 23 개 functional requirement 가 모두 task 안에서 인용됨
- [x] Cross-Spec Boundary B-1 ~ B-8 8 개가 모두 적어도 하나의 task 로 보존 검증됨
- [x] MVP scope (Phase 1 + 2 + US1) 가 명시되어 incremental delivery 가능

---

## Closure Notes (2026-05-16)

본 spec 의 70 개 task 가 모두 완료되었음을 매뉴얼 검증으로 확인했다.

### 매뉴얼 검증 결과 (T069 quickstart §5)

| 항목 | 결과 |
|---|---|
| SC-001: `collect takeout --dry-run` exit 0 | ✅ dry-run 1회차 17m41s, exit 0 (간호학과 archive) |
| SC-002: SQLite `video_metadata` 행 = 2554 (간호학과) | ✅ 2554 행 (전체 DB 는 다른 test 잔재 1 행 포함하여 2555) |
| SC-002: privacy_status NULL = 0 / 한글 = 0 | ✅ private 2261 + unlisted 294 = 2554 영어 표준값 |
| SC-004: `admin list` union | ✅ channels.json (nursing) + departments.json (dept-a/b, nursing2, nursingt) 5 행 정상 |
| SC-005: 멱등 적재 (`new=0`) | ✅ 2회차 17m48s, new_videos=0, audit append-only +2584 행 |
| SC-006: `--source youtube` exit 2 + 한글 메시지 | ✅ 즉시 차단 |
| SC-006: `--source asr` 기본 동작 | ⚠️ ASR 실측 미수행 — 사용자 결정 (2026-05-16) 으로 스킵, 회귀 매트릭스 `test_asr_single_source.py` 9 PASS 로 갈음 |
| SC-007: 한글 영상 제목 round-trip 정합 | ✅ 회귀 매트릭스 `TestTitleRoundTripFidelity` 5 케이스 PASS |
| SC-008: 회귀 매트릭스 PASS | ✅ 321 passed in 19m22s (`tests/unit + integration + contract`) |
| SC-009: `elapsed_seconds` / `elapsed_ms` 양의 값 | ✅ dry-run 1061s + ingest 1064s 측정값 IngestResult 출력 |

### T068 ruff/타입/버전 sanity

- spec 016 변경 surface 안에서 ruff clean (변경 5 src 파일 + 신규 8 test 파일 모두 통과, 5a05ca4 에서 ruff auto-fix 35 건 처리)
- pyproject.toml version = `0.5.1` (어제 release 시점에 dev0 suffix 제거 완료, uv.lock sync 도 5a05ca4 에 포함)
- `src/tube_scout/cli/collect.py` 의 E501 21 건 + F841 1 건은 git blame 으로 모두 spec 013 (aa29adf1, 9a0eba90, 1efa7d4f 등 2026-05-14) 잔재로 확인 → spec 016 의 surgical scope (CLAUDE.md §3.3) 밖이므로 미수정

### T070 commit 누락 점검

- spec.md / plan.md / research.md / data-model.md / contracts/ / quickstart.md / tasks.md → 8e8c29c + 8193966 + e95eaa9
- CLAUDE.md → 8193966 (T066)
- 코드 5 파일 (audit_writer / takeout_ingest / content / admin / collect) → 4978ee9 / d05adbb / 775d620 / f67e385 / 8abbbac / d96b82e / 1607110 / 2b3826b / 5dc4b85 / a2fa83c
- 테스트 신규 8 파일 → 295ca1e / 6578194 / 8abbbac / 2b3826b / d96b82e / 85db4a0 / 70f5eaf 에 분산 포함
- 누락 0건

### Spec 016 범위 밖으로 확인된 후속 결함 (spec 017 로 이양)

본 spec 의 적재 흐름이 사용자 의도와 정합화되기 위해 추가 작업이 필요한 항목을 closure 시점에 식별:

1. **ffprobe 22,986 회 반복 호출 비효율** — `src/tube_scout/services/evidence_score.py:218` 의 매칭 루프가 mp4 1 개의 duration 을 후보 2554 회마다 ffprobe 로 재측정. mp4 1 회당 1 호출로 메모이즈하면 적재 시간 약 17 분 → 약 1 분. spec 013 시점에 들어온 결함으로 spec 016 의 결함 11 개 목록에 누락. T064 의 정량 SLA (≤ 1770 s) 도 이 비효율을 기준으로 측정되어 있어 spec 017 에서 재측정 필요.
2. **영상 본체 삭제 흐름 부재** — 사용자 의도 "분석 직후 영상 삭제, 학과 자기관리 책임" 이 spec 016 의 FR 어디에도 명시되지 않음. 현재는 mp4 symlink 만 생성하며 Takeout archive 의 원본 영상 (간호학과 9.9 GB) 이 사용자 수동 삭제 전까지 그대로 점유.
3. **적재 → 음원 추출 → 자막 + 지문 통합 흐름 부재** — `collect takeout`, `collect audio-extract`, `collect process-audio`, `collect transcripts`, `collect fingerprint` 가 개별 명령으로 분리되어 매번 ffmpeg 재디코딩 발생. 사용자 의도의 "한 번에 다 처리" 단일 명령 진입점 없음.

이 세 항목은 spec 016 의 "결함 11 개 PATCH" 범위 밖이므로 본 spec 의 closure 를 막지 않으며, **spec 017 (Takeout 통합 적재와 운영 효율화)** 에서 다룬다.

### 본 세션 commit 요약

- 5a05ca4 — `style(tests): ruff auto-fix on spec 016 new test files + uv.lock sync`
- (본 commit) — `chore(spec016): closure notes + bulk tick all tasks after manual validation`
