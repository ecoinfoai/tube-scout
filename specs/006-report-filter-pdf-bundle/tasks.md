# Tasks: 보고서 필터링 및 PDF 종합 출력

**Input**: Design documents from `/specs/006-report-filter-pdf-bundle/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-interface.md

**Tests**: TDD mandatory (CLAUDE.md). 테스트 먼저 작성 → 실패 확인 → 구현.

**Organization**: Tasks are grouped by user story. 기존 코드 80% 재사용 — 신규 파일 생성 없이 기존 5개 파일 확장.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: 기존 테스트가 모두 통과하는 baseline 확인

- [ ] T001 Run full test suite `uv run pytest --tb=short -q` and verify 1220+ passed baseline
- [ ] T002 Verify weasyprint availability: `python -c "from weasyprint import HTML"` — 가용 여부 확인 (설치 불필요, 폴백 지원)

---

## Phase 2: Foundational (date_asc 정렬 추가)

**Purpose**: 모든 User Story가 의존하는 date_asc 정렬 옵션 추가

**⚠️ CRITICAL**: US1~US4가 이 정렬 옵션에 의존

### Tests

- [ ] T003 [P] Write test for date_asc sort in tests/unit/test_video_filter_service.py — 영상 목록이 게시일 오름차순으로 정렬되는지 검증

### Implementation

- [ ] T004 Add `"date_asc"` sort option to `VideoFilterService.sort_videos()` in src/tube_scout/services/video_filter_service.py — 기존 `"date"` 로직에서 `reverse=False`로 분기

**Checkpoint**: `uv run pytest tests/unit/test_video_filter_service.py -x` — all pass

---

## Phase 3: User Story 1 — 조건별 영상 필터링 (Priority: P1) 🎯 MVP

**Goal**: 키워드/기간 필터로 영상을 선별하고, 결과가 0건이면 안내 메시지 표시

**Independent Test**: `--keyword "감염미생물학"` 필터 시 해당 영상만 반환, 0건 시 메시지 출력

### Tests

- [ ] T005 [P] [US1] Write test: keyword filter returns only matching videos in tests/unit/test_report_cli_filter.py
- [ ] T006 [P] [US1] Write test: date range filter returns only videos in range in tests/unit/test_report_cli_filter.py
- [ ] T007 [P] [US1] Write test: combined keyword + date filter (AND logic) in tests/unit/test_report_cli_filter.py
- [ ] T008 [P] [US1] Write test: empty filter result shows message and exits in tests/unit/test_report_cli_filter.py

### Implementation

- [ ] T009 [US1] Update report_bundle_command in src/tube_scout/cli/report.py — 필터 결과 0건 시 Rich 안내 메시지 출력 + exit(0). 기존 VideoFilterService.filter_videos() + sort_videos(sort="date_asc") 호출

**Checkpoint**: `uv run pytest tests/unit/test_report_cli_filter.py -x` — US1 tests pass

---

## Phase 4: User Story 2 — 필터 결과 미리보기 (Priority: P2)

**Goal**: 필터 결과를 테이블로 미리보기하고, 사용자가 확인/취소 선택

**Independent Test**: 미리보기 테이블에 제목/게시일/조회수가 표시되고, confirm→생성, cancel→종료

### Tests

- [ ] T010 [P] [US2] Write test: preview table displays title, published_at, view_count in tests/unit/test_report_cli_filter.py
- [ ] T011 [P] [US2] Write test: --no-confirm skips interactive confirmation in tests/unit/test_report_cli_filter.py
- [ ] T012 [P] [US2] Write test: --dry-run shows preview only, no generation in tests/unit/test_report_cli_filter.py

### Implementation

- [ ] T013 [US2] Add --no-confirm option to report_bundle_command in src/tube_scout/cli/report.py
- [ ] T014 [US2] Enhance _print_dry_run_table() to include view_count column and total duration summary in src/tube_scout/cli/report.py
- [ ] T015 [US2] Implement interactive confirmation flow: preview → typer.confirm() → generate or exit in src/tube_scout/cli/report.py

**Checkpoint**: `uv run pytest tests/unit/test_report_cli_filter.py -x` — US1+US2 tests pass

---

## Phase 5: User Story 3 — PDF 종합 보고서 생성 (Priority: P1)

**Goal**: 표지, 목차(페이지번호), 페이지번호, 영상별 페이지 구분이 포함된 단일 PDF 생성

**Independent Test**: 10개 영상 필터 후 PDF 생성 → 표지/목차/페이지번호 존재, 영상 간 페이지 구분

### Tests

- [ ] T016 [P] [US3] Write test: cover page contains channel name, filter conditions, video count, total duration, date in tests/unit/test_bundle_report.py
- [ ] T017 [P] [US3] Write test: channel summary page contains professor distribution and course list in tests/unit/test_bundle_report.py
- [ ] T018 [P] [US3] Write test: TOC entries exist for each video in tests/unit/test_bundle_report.py
- [ ] T019 [P] [US3] Write test: page number format "p. N / Total" in CSS in tests/unit/test_bundle_report.py
- [ ] T020 [P] [US3] Write test: each video section has page-break-before in tests/unit/test_bundle_report.py
- [ ] T021 [P] [US3] Write test: render_pdf returns None when weasyprint unavailable in tests/unit/test_bundle_report.py
- [ ] T022 [P] [US3] Write test: --format html skips PDF rendering in tests/unit/test_report_cli_filter.py

### Implementation

- [ ] T023 [US3] Load channel_meta.json for channel name in BundleReportGenerator.generate() in src/tube_scout/reporting/bundle_report.py
- [ ] T024 [US3] Implement channel summary computation (professor distribution, course list) using ParsedTitle data in src/tube_scout/reporting/bundle_report.py
- [ ] T025 [US3] Update bundle_report.html template — enhanced cover page with channel name, total duration in src/tube_scout/reporting/templates/bundle_report.html
- [ ] T026 [US3] Add channel summary page section to bundle_report.html template in src/tube_scout/reporting/templates/bundle_report.html
- [ ] T027 [US3] Add CSS target-counter() for TOC page numbers and -weasy-bookmark-level for PDF bookmarks in src/tube_scout/reporting/templates/bundle_report.html
- [ ] T028 [US3] Add page-break-inside:avoid to chart containers in template CSS in src/tube_scout/reporting/templates/bundle_report.html
- [ ] T029 [US3] Apply same template changes to bundle_from_html.html in src/tube_scout/reporting/templates/bundle_from_html.html
- [ ] T030 [US3] Add --format option (pdf|html) to report_bundle_command in src/tube_scout/cli/report.py
- [ ] T031 [US3] Implement HTML fallback with clear error message when weasyprint unavailable (FR-015/016) in src/tube_scout/cli/report.py

**Checkpoint**: `uv run pytest tests/unit/test_bundle_report.py tests/unit/test_report_cli_filter.py -x` — US3 tests pass

---

## Phase 6: User Story 4 — 정렬 옵션 (Priority: P3)

**Goal**: 게시일순, 교과목→주차순, 조회수순 중 선택 가능

**Independent Test**: 같은 필터 결과에 3가지 정렬 적용 시 순서가 달라짐

### Tests

- [ ] T032 [P] [US4] Write test: --sort date_asc produces chronological order in tests/unit/test_report_cli_filter.py
- [ ] T033 [P] [US4] Write test: --sort course produces subject→week order in tests/unit/test_report_cli_filter.py
- [ ] T034 [P] [US4] Write test: --sort views produces view count descending order in tests/unit/test_report_cli_filter.py

### Implementation

- [ ] T035 [US4] Wire --sort option through report_bundle_command to VideoFilterService.sort_videos() in src/tube_scout/cli/report.py — default 변경: date → date_asc

**Checkpoint**: `uv run pytest tests/unit/test_report_cli_filter.py -k "sort" -x` — US4 tests pass

---

## Phase 7: User Story 5 — 표지 및 채널 요약 (Priority: P2)

**Goal**: PDF 표지에 공식 문서 체계, 채널 요약 페이지 포함

**Independent Test**: PDF 첫 페이지=표지(필터 조건 명시), 두 번째 페이지=채널 개요

> Note: US5의 실제 구현은 US3(Phase 5)에서 이미 완료됨 (T023~T029). 이 Phase는 검증과 edge case 보강.

### Tests

- [ ] T036 [P] [US5] Write test: cover shows filter_description string in tests/unit/test_bundle_report.py
- [ ] T037 [P] [US5] Write test: channel summary with 0 parsed titles still renders in tests/unit/test_bundle_report.py

### Implementation

- [ ] T038 [US5] Generate filter_description string from VideoFilter fields in src/tube_scout/reporting/bundle_report.py — "키워드: X, 기간: Y ~ Z" 형식

**Checkpoint**: `uv run pytest tests/unit/test_bundle_report.py -x` — US5 tests pass

---

## Phase 8: Edge Cases & Graceful Degradation

**Purpose**: 데이터 부재, 대용량, 도구 미설치 edge cases

### Tests

- [ ] T039 [P] Write test: report with no retention data omits retention section in tests/unit/test_bundle_report.py
- [ ] T040 [P] Write test: report with no comments omits comments section in tests/unit/test_bundle_report.py
- [ ] T041 [P] Write test: report with no transcripts omits EQS/segment section in tests/unit/test_bundle_report.py
- [ ] T042 [P] Write test: 100+ videos bundle generates without memory error in tests/integration/test_bundle_flow.py

### Implementation

- [ ] T043 Verify all conditional template blocks ({% if %}) handle missing data in src/tube_scout/reporting/templates/bundle_report.html
- [ ] T044 Verify all conditional blocks in bundle_from_html.html in src/tube_scout/reporting/templates/bundle_from_html.html

**Checkpoint**: `uv run pytest tests/unit/test_bundle_report.py tests/integration/test_bundle_flow.py -x` — all pass

---

## Phase 9: Polish & Integration

**Purpose**: 전체 통합 테스트, ruff, 최종 검증

- [ ] T045 Write E2E test: filter → preview → confirm → PDF output in tests/integration/test_bundle_flow.py
- [ ] T046 Run full test suite `uv run pytest --tb=short -q` — all 1220+ existing tests still pass
- [ ] T047 Run `uv run ruff check src/ && uv run ruff format --check src/` — 0 violations
- [ ] T048 Run quickstart.md validation — verify documented commands work

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies
- **Phase 2 (Foundational)**: Depends on Phase 1
- **Phase 3 (US1)**: Depends on Phase 2
- **Phase 4 (US2)**: Depends on Phase 3 (uses filter result)
- **Phase 5 (US3)**: Depends on Phase 3 (uses filter result for PDF)
- **Phase 6 (US4)**: Depends on Phase 2 (date_asc sort)
- **Phase 7 (US5)**: Depends on Phase 5 (cover/summary in template)
- **Phase 8 (Edge Cases)**: Depends on Phase 5
- **Phase 9 (Polish)**: Depends on all

### Parallel Opportunities

- Phase 4 (US2) and Phase 5 (US3) can run in parallel after Phase 3
- Phase 6 (US4) can run in parallel with Phase 4/5 after Phase 2
- All test tasks within each Phase marked [P] can run in parallel

### Within Each User Story

- Tests FIRST (RED) → Implementation (GREEN) → Verify (REFACTOR)
- 기존 코드 확장이므로 모델 생성 태스크 없음

---

## Implementation Strategy

### MVP First (US1 + US3)

1. Phase 1-2: Setup + date_asc
2. Phase 3: US1 (필터링)
3. Phase 5: US3 (PDF 생성)
4. **STOP and VALIDATE**: 필터→PDF 워크플로우 동작 확인

### Incremental Delivery

1. + Phase 4: US2 (미리보기 확인)
2. + Phase 6: US4 (정렬 옵션)
3. + Phase 7: US5 (표지 검증)
4. + Phase 8-9: Edge cases + Polish

---

## Notes

- 기존 코드 80% 재사용 — 신규 파일 생성 없이 5개 파일 수정
- TDD mandatory: 테스트 먼저 작성 (T003~T042) → 실패 확인 → 구현
- weasyprint 선택적 의존성 — ImportError 시 HTML 폴백
- 총 48 tasks (tests 26 + implementation 22)
