# Tasks: 보고서 필터링 및 PDF 종합 출력

**Input**: Design documents from `/specs/004-report-filter-pdf-bundle/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: TDD mandatory per CLAUDE.md — test tasks included for each user story.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1–US6)
- Exact file paths included in descriptions

---

## Phase 1: Setup

**Purpose**: 시스템 의존성 확보 및 신규 모듈 초기화

- [ ] T001 flake.nix devShell에 weasyprint 시스템 라이브러리 추가 (pango, glib, gobject-introspection, harfbuzz, fontconfig)
- [ ] T002 `python -c "from weasyprint import HTML"` 정상 동작 검증
- [ ] T003 [P] VideoFilter 모델 파일 생성 in src/tube_scout/models/video_filter.py (빈 모듈 + __init__ export)
- [ ] T004 [P] BundleReportGenerator 파일 생성 in src/tube_scout/reporting/bundle_report.py (빈 클래스)
- [ ] T005 [P] VideoFilterService 파일 생성 in src/tube_scout/services/video_filter_service.py (빈 클래스)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 모든 User Story가 의존하는 VideoFilter 모델 구현

**CRITICAL**: US1~US6 모두 필터링에 의존하므로 이 Phase 완료 필수

- [ ] T006 VideoFilter pydantic 모델 구현 in src/tube_scout/models/video_filter.py — keyword, published_after, published_before, video_ids 필드, 최소 1개 조건 validator
- [ ] T007 Unit test for VideoFilter 모델 validation in tests/unit/test_video_filter.py — 빈 필터 거부, 날짜 범위 검증, 정상 생성
- [ ] T008 VideoFilterService.filter_videos() 구현 in src/tube_scout/services/video_filter_service.py — videos_meta.json 로드 후 VideoFilter 조건으로 필터링
- [ ] T009 Unit test for VideoFilterService in tests/unit/test_video_filter_service.py — 키워드 매칭, 기간 필터, AND 조합, 0건 결과, video_ids 직접 지정

**Checkpoint**: VideoFilter 모델 + 서비스 독립 테스트 통과

---

## Phase 3: User Story 1 — 키워드/기간으로 영상 필터링 후 보고서 생성 (Priority: P1) MVP

**Goal**: `report video` 명령에 --keyword, --published-after, --published-before, --video-ids 필터 옵션 추가

**Independent Test**: `tube-scout report video --keyword "인체구조와기능"` 실행 시 해당 교과목 영상만 HTML 보고서 생성

### Tests for User Story 1

- [ ] T010 [P] [US1] Unit test for report video 필터 옵션 파싱 in tests/unit/test_report_cli_filter.py — keyword/published-after/published-before/video-ids 옵션 파싱 검증
- [ ] T011 [P] [US1] Integration test for 필터링된 report video in tests/integration/test_filtered_report.py — 키워드 필터로 대상 영상만 보고서 생성 확인

### Implementation for User Story 1

- [ ] T012 [US1] report video 명령에 필터 옵션 추가 in src/tube_scout/cli/report.py — --keyword, --published-after, --published-before, --video-ids 옵션 정의
- [ ] T013 [US1] report_video_command 내부에서 VideoFilterService 호출하여 영상 목록 필터링 in src/tube_scout/cli/report.py
- [ ] T014 [US1] 필터 결과 0개일 때 안내 메시지 + exit code 1 처리 in src/tube_scout/cli/report.py

**Checkpoint**: `report video --keyword "감염미생물학"` 정상 동작, 필터된 영상만 HTML 생성

---

## Phase 4: User Story 2 — PDF 종합 보고서 출력 (Priority: P1) MVP

**Goal**: `report bundle` 명령으로 필터링된 영상들의 분석 결과를 표지+목차+페이지번호가 포함된 단일 PDF 출력

**Independent Test**: `tube-scout report bundle --keyword "감염미생물학" --output test.pdf` 실행 시 PDF 생성, 표지/목차/페이지번호 확인

### Tests for User Story 2

- [ ] T015 [P] [US2] Unit test for BundleReportGenerator in tests/unit/test_bundle_report.py — 표지 데이터 생성, 목차 생성, 영상별 섹션 렌더링
- [ ] T016 [P] [US2] Integration test for bundle PDF 생성 in tests/integration/test_bundle_flow.py — 필터→렌더→PDF 전체 플로우 (weasyprint mock 또는 실제)

### Implementation for User Story 2

- [ ] T017 [P] [US2] bundle_report.html Jinja2 템플릿 생성 in src/tube_scout/reporting/templates/bundle_report.html — 표지 + 목차 + 영상 반복 구조, CSS @page (페이지번호 "p. N / Total", page-break-before)
- [ ] T018 [US2] BundleReportGenerator.generate() 구현 in src/tube_scout/reporting/bundle_report.py — VideoFilter로 영상 선택 → 각 영상의 분석 데이터 로드 → Jinja2 렌더링 → 단일 HTML 생성
- [ ] T019 [US2] BundleReportGenerator._render_pdf() 구현 in src/tube_scout/reporting/bundle_report.py — weasyprint로 HTML→PDF 변환
- [ ] T020 [US2] 분석 데이터 없는 영상의 섹션 graceful 생략 처리 in src/tube_scout/reporting/bundle_report.py — retention/segments/eqs 없을 때 해당 블록 숨김
- [ ] T021 [US2] report bundle CLI 명령 등록 in src/tube_scout/cli/report.py — report_bundle_command 함수 정의 (--keyword, --published-after, --published-before, --video-ids, --output, --title, --sort, --data-dir)
- [ ] T022 [US2] report bundle 명령을 main.py에 등록 in src/tube_scout/cli/main.py — report_app.command(name="bundle")

**Checkpoint**: `report bundle --keyword "감염미생물학" --output test.pdf` 실행 시 표지+목차+영상 포함 PDF 생성

---

## Phase 5: User Story 3 — 필터 결과 미리보기 (Priority: P2)

**Goal**: --dry-run 옵션으로 보고서 생성 전 대상 영상 목록만 미리 확인

**Independent Test**: `tube-scout report video --keyword "인체구조와기능" --dry-run` 실행 시 테이블 출력, 보고서 미생성

### Tests for User Story 3

- [ ] T023 [P] [US3] Unit test for dry-run 모드 in tests/unit/test_report_cli_filter.py — dry-run 시 보고서 생성 안 됨, 영상 목록 출력 확인

### Implementation for User Story 3

- [ ] T024 [US3] report video에 --dry-run 옵션 추가 + Rich table 출력 in src/tube_scout/cli/report.py — Video ID, Title, Published 컬럼 표시 후 조기 종료
- [ ] T025 [US3] report bundle에 --dry-run 옵션 추가 in src/tube_scout/cli/report.py — 동일 미리보기 + PDF 생성 건너뜀

**Checkpoint**: dry-run 모드에서 보고서 미생성, 대상 목록만 표시

---

## Phase 6: User Story 6 — 기존 HTML 보고서 수거 → PDF 병합 (Priority: P2)

**Goal**: --from-html 옵션으로 기존 HTML 파일들을 body 추출하여 PDF 종합 보고서 생성

**Independent Test**: `tube-scout report bundle --from-html data/reports/video/ --keyword "감염미생물학" --output test.pdf` 실행 시 기존 HTML에서 PDF 생성

### Tests for User Story 6

- [ ] T026 [P] [US6] Unit test for HTML body 추출 in tests/unit/test_bundle_report.py — 완전한 HTML에서 body 내용만 추출
- [ ] T027 [P] [US6] Unit test for --from-html 필터링 in tests/unit/test_bundle_report.py — video_id.html 파일명 매칭 + 메타데이터 기반 필터

### Implementation for User Story 6

- [ ] T028 [US6] BundleReportGenerator._extract_html_body() 구현 in src/tube_scout/reporting/bundle_report.py — html.parser로 body 내용 추출
- [ ] T029 [US6] BundleReportGenerator.generate_from_html() 구현 in src/tube_scout/reporting/bundle_report.py — HTML 디렉터리 스캔 → 필터 매칭 → body 추출 → bundle 템플릿에 삽입 → PDF
- [ ] T030 [US6] report bundle에 --from-html 옵션 추가 in src/tube_scout/cli/report.py — from_html 경로 지정 시 generate_from_html() 호출
- [ ] T031 [US6] HTML 누락/파싱 불가 시 경고 + 건너뛰기 처리 in src/tube_scout/reporting/bundle_report.py

> Note: FR-012(데이터 없는 섹션 생략)는 --from-html 모드에서 자동 충족 — 원본 HTML이 이미 video_report 템플릿에서 적절히 처리된 상태이므로 추가 처리 불필요.

**Checkpoint**: 기존 214개 HTML에서 필터링된 영상의 PDF가 데이터 재분석 없이 생성

---

## Phase 7: User Story 4 — 영상 정렬 옵션 (Priority: P3)

**Goal**: --sort 옵션으로 종합 보고서 내 영상 순서 변경

**Independent Test**: 동일 필터로 --sort date vs --sort views 실행 시 영상 순서가 다름

### Tests for User Story 4

- [ ] T032 [P] [US4] Unit test for 정렬 로직 in tests/unit/test_video_filter_service.py — date/course/views 정렬 결과 검증

### Implementation for User Story 4

- [ ] T033 [US4] VideoFilterService.sort_videos() 구현 in src/tube_scout/services/video_filter_service.py — date(역순), course(교과목→주차→차시), views(내림차순)
- [ ] T034 [US4] BundleReportGenerator에 sort_by 적용 in src/tube_scout/reporting/bundle_report.py — generate()/generate_from_html()에서 정렬 후 렌더링

**Checkpoint**: --sort 옵션에 따라 PDF 내 영상 순서 변경됨

---

## Phase 8: User Story 5 — 종합 보고서에 채널 요약 포함 (Priority: P3)

**Goal**: bundle 보고서에 필터 대상 영상의 통계 요약 섹션 포함

**Independent Test**: bundle PDF에서 표지 다음에 영상 수, 총 재생시간, 평균 조회수 표시

### Tests for User Story 5

- [ ] T035 [P] [US5] Unit test for 통계 요약 계산 in tests/unit/test_bundle_report.py — 영상 수, 총 재생시간, 평균 조회수 계산 검증

### Implementation for User Story 5

- [ ] T036 [US5] BundleReportGenerator._compute_summary() 구현 in src/tube_scout/reporting/bundle_report.py — 필터된 영상의 총 수, 총 재생시간, 평균 조회수, 총 좋아요 집계
- [ ] T037 [US5] bundle_report.html 템플릿에 summary 섹션 추가 in src/tube_scout/reporting/templates/bundle_report.html — 표지 다음, 목차 전에 통계 요약 블록

**Checkpoint**: PDF에 통계 요약 섹션이 정확한 수치로 표시

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 전체 기능 안정성 및 엣지 케이스 처리

- [ ] T038 200개 초과 영상 필터 시 경고 메시지 + 진행 확인 in src/tube_scout/cli/report.py
- [ ] T039 필터 결과 1개일 때 목차 생략 처리 in src/tube_scout/reporting/bundle_report.py
- [ ] T040 [P] plotly 차트 정적 이미지 변환 (PDF용) in src/tube_scout/reporting/bundle_report.py — plotly.io.to_image() 또는 SVG fallback
- [ ] T041 [P] 키워드 특수문자 (괄호, 따옴표) 안전 처리 검증 in tests/unit/test_video_filter_service.py
- [ ] T042 quickstart.md 시나리오 수동 검증 실행

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1 필터링)**: Depends on Phase 2
- **Phase 4 (US2 PDF)**: Depends on Phase 2 (can parallelize with US1, but US1 먼저 권장)
- **Phase 5 (US3 dry-run)**: Depends on Phase 3 (US1 필터링 옵션 필요)
- **Phase 6 (US6 HTML 수거)**: Depends on Phase 4 (US2 BundleReportGenerator 필요)
- **Phase 7 (US4 정렬)**: Depends on Phase 4 (US2 bundle 필요)
- **Phase 8 (US5 요약)**: Depends on Phase 4 (US2 bundle 필요)
- **Phase 9 (Polish)**: Depends on all desired user stories

### User Story Dependencies

- **US1 (필터링)**: Phase 2 완료 후 즉시 시작 가능
- **US2 (PDF)**: Phase 2 완료 후 시작 가능 (US1과 병렬 가능하나 순차 권장)
- **US3 (dry-run)**: US1 완료 필요
- **US6 (HTML 수거)**: US2 완료 필요
- **US4 (정렬)**: US2 완료 필요
- **US5 (요약)**: US2 완료 필요

### Parallel Opportunities

- T003, T004, T005 (Phase 1 모듈 초기화)
- T010, T011 (US1 테스트)
- T015, T016 (US2 테스트)
- T026, T027 (US6 테스트)
- US4, US5, US6은 US2 완료 후 모두 병렬 가능

---

## Parallel Example: User Story 2

```bash
# Launch tests together:
Task: "Unit test for BundleReportGenerator in tests/unit/test_bundle_report.py"
Task: "Integration test for bundle PDF in tests/integration/test_bundle_flow.py"

# After tests fail, launch template + generator in parallel:
Task: "bundle_report.html 템플릿 in src/tube_scout/reporting/templates/bundle_report.html"
Task: "BundleReportGenerator.generate() in src/tube_scout/reporting/bundle_report.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Phase 1: Setup (weasyprint 시스템 라이브러리)
2. Phase 2: Foundational (VideoFilter 모델 + 서비스)
3. Phase 3: US1 (report video 필터 옵션)
4. Phase 4: US2 (report bundle PDF 생성)
5. **STOP and VALIDATE**: 키워드 필터 + PDF 출력 독립 검증
6. 이후 US3→US6→US4→US5 순으로 증분 추가

### Incremental Delivery

1. Setup + Foundational → 필터링 인프라 준비
2. US1 → `report video --keyword` 동작 → 검증
3. US2 → `report bundle --output .pdf` 동작 → 검증 (MVP!)
4. US3 → `--dry-run` 추가 → 검증
5. US6 → `--from-html` 추가 → 검증
6. US4 + US5 → 정렬/요약 → 검증
7. Polish → 엣지 케이스 처리

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to user story for FR traceability
- TDD: 테스트 먼저 작성 후 FAIL 확인 → 구현 → PASS
- weasyprint는 NixOS flake.nix 수정 필수 (T001)
- plotly 차트 PDF 렌더링은 Polish 단계에서 처리 (T040)
