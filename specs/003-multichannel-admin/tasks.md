# Tasks: Multi-Channel Administration

**Input**: Design documents from `/specs/003-multichannel-admin/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-commands.md

**Tests**: TDD mandatory per project convention. Test tasks included for each user story.

**Organization**: Tasks grouped by user story. Each story independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Add new dependencies and project configuration

- [ ] T001 Add new dependencies (pyyaml, openpyxl, python-Levenshtein, weasyprint) to pyproject.toml
- [ ] T002 Run `uv sync` and verify all existing tests still pass
- [ ] T003 Create sample title fixtures from real 간호학과 data in tests/fixtures/sample_titles.json
- [ ] T004 Create sample search config in tests/fixtures/search_clips_sample.yaml

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared models and output manager that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 [P] Create src/tube_scout/output/__init__.py and OutputManager class (timestamped directory creation, latest symlink) in src/tube_scout/output/manager.py
- [ ] T006 [P] Create ChannelRegistration model in src/tube_scout/models/config.py (alias, channel_id, channel_name, registered_at, last_used_at, token_path)
- [ ] T007 [P] Create ParsedTitle model in src/tube_scout/models/parsed_title.py (video_id, original_title, professor list, course, year, semester, week, session, department, category, parse_error, matched_pattern)
- [ ] T008 [P] Create ValidationFinding model in src/tube_scout/models/validation.py (rule_id, severity, video_ids, professor, description, details)
- [ ] T009 [P] Create SearchFilter, SearchQuery, ExcludeRule models in src/tube_scout/models/search.py
- [ ] T010 [P] Write tests for all new models in tests/unit/test_admin_models.py
- [ ] T011 Write tests for OutputManager in tests/unit/test_output_manager.py
- [ ] T012 Verify all existing tests still pass after model additions

**Checkpoint**: Foundation ready — all models defined, output manager functional, existing tests green

---

## Phase 3: User Story 1 — Multi-Channel Token Management (Priority: P1) MVP

**Goal**: Register, list, and revoke department channels with per-alias token storage

**Independent Test**: Register 2+ channels, list them, revoke one, verify the other still works

### Tests for User Story 1

- [ ] T013 [P] [US1] Write unit tests for multi-channel auth (register, list, revoke, refresh, auto-detect channel ID) in tests/unit/test_auth_multi.py
- [ ] T014 [P] [US1] Write adversary tests for expired tokens, revoked credentials, missing alias in tests/adversary/test_auth_failures.py

### Implementation for User Story 1

- [ ] T015 [US1] Extend auth.py with multi-channel token management: authenticate_channel(alias), register_channel(alias), list_channels(), revoke_channel(alias) in src/tube_scout/services/auth.py
- [ ] T016 [US1] Implement channels.json registry management (load, save, update last_used_at) in src/tube_scout/services/auth.py
- [ ] T017 [US1] Implement auto-detect channel ID via channels.list(mine=True) after OAuth login in src/tube_scout/services/auth.py
- [ ] T018 [US1] Support TUBE_SCOUT_TOKENS_DIR environment variable override in src/tube_scout/services/auth.py
- [ ] T019 [US1] Create auth CLI subcommands (--channel, --list, --revoke) in src/tube_scout/cli/auth_cli.py
- [ ] T020 [US1] Register auth subcommands in src/tube_scout/cli/main.py
- [ ] T021 [US1] Add --channel flag to existing collect commands in src/tube_scout/cli/collect.py

**Checkpoint**: Multiple channels registered, listed, revoked; tokens auto-refresh; --channel flag works on collect

---

## Phase 4: User Story 2 — Title Parsing (Priority: P1)

**Goal**: Parse video titles into structured fields with ≥85% success rate

**Independent Test**: Feed real 간호학과 titles, verify professor/course/year/week/session extraction + parse_error flagging

### Tests for User Story 2

- [ ] T022 [P] [US2] Write unit tests for title parser (5 patterns, fallback, multi-professor, unparseable titles) in tests/unit/test_title_parser.py
- [ ] T023 [P] [US2] Write adversary tests for edge cases (English titles, emoji, no week, "특강", very long titles) in tests/adversary/test_title_edge_cases.py

### Implementation for User Story 2

- [ ] T024 [US2] Create TitlePattern model with 5 priority patterns (standard_kr, semester_explicit, co_teaching, academic_year, numbered_prefix) in src/tube_scout/services/title_parser.py
- [ ] T025 [US2] Implement TitleParser.parse(title) → ParsedTitle with priority pattern matching in src/tube_scout/services/title_parser.py
- [ ] T026 [US2] Implement multi-professor extraction (slash-separated, parenthesized) in src/tube_scout/services/title_parser.py
- [ ] T027 [US2] Implement supplementary video classification (핵심영상, 보완영상, 질문응답, 보충, 특강, OT) in src/tube_scout/services/title_parser.py
- [ ] T028 [US2] Implement fallback parsing (extract individual fields when full pattern fails) in src/tube_scout/services/title_parser.py
- [ ] T029 [US2] Implement TitleParser.parse_batch(videos) → list[ParsedTitle] with summary stats in src/tube_scout/services/title_parser.py
- [ ] T030 [US2] Store parsed results to OutputManager timestamped directory as parsed_titles.json in src/tube_scout/services/title_parser.py
- [ ] T031 [US2] Run parser against real 간호학과 214 titles fixture and verify ≥85% success rate in tests/unit/test_title_parser.py

**Checkpoint**: Title parsing works on real data with ≥85% success rate, structured JSON output saved

---

## Phase 5: User Story 3 — Structured Search (Priority: P2)

**Goal**: YAML-based and CLI-based video filtering with AND/OR/exclude logic

**Independent Test**: Apply search_clips.yaml to parsed data, verify filtered results match expected

### Tests for User Story 3

- [ ] T032 [P] [US3] Write unit tests for search service (single filter, OR queries, exclude, CLI flags, empty results) in tests/unit/test_search_service.py

### Implementation for User Story 3

- [ ] T033 [US3] Implement SearchService.load_config(yaml_path) → SearchQuery in src/tube_scout/services/search_service.py
- [ ] T034 [US3] Implement SearchService.search(parsed_titles, query) → list[ParsedTitle] with AND/OR/exclude logic in src/tube_scout/services/search_service.py
- [ ] T035 [US3] Implement CLI-to-SearchQuery conversion (--professor, --year, etc.) in src/tube_scout/services/search_service.py
- [ ] T036 [US3] Create search CLI subcommand (--config, --channel, CLI flags, --export) in src/tube_scout/cli/search_cli.py
- [ ] T037 [US3] Register search subcommand in src/tube_scout/cli/main.py
- [ ] T037a [US3] Add performance benchmark: search with YAML filters < 5s for synthetic 5000-title dataset in tests/unit/test_search_service.py

**Checkpoint**: YAML and CLI search functional, results displayed and exportable, SC-003 benchmark passing

---

## Phase 6: User Story 4 — Department Report (Priority: P2)

**Goal**: Generate department reports with overview, professor detail, compliance analysis in HTML/Excel

**Independent Test**: Provide parsed data + calendar, verify report sections with correct calculations

### Tests for User Story 4

- [ ] T038 [P] [US4] Write unit tests for department report generation (overview, professor detail, compliance) in tests/unit/test_department_report.py
- [ ] T039 [P] [US4] Write unit tests for Excel export (multi-sheet, conditional formatting) in tests/unit/test_excel_export.py

### Implementation for User Story 4

- [ ] T040 [US4] Create DepartmentReportGenerator with compute_overview() → DepartmentOverview in src/tube_scout/reporting/department_report.py
- [ ] T041 [US4] Implement compute_professor_details() → list[ProfessorDetail] with coverage, completeness, timing in src/tube_scout/reporting/department_report.py
- [ ] T042 [US4] Implement compute_compliance() → ComplianceMatrix using academic calendar in src/tube_scout/reporting/department_report.py
- [ ] T043 [US4] Create HTML template with plotly heatmap (professor × week) and duration distribution in src/tube_scout/reporting/templates/department.html
- [ ] T044 [US4] Implement generate_html(data, output_path) using Jinja2 + plotly and optional generate_pdf(html_path) via weasyprint (graceful skip if not installed) in src/tube_scout/reporting/department_report.py
- [ ] T045 [US4] Create ExcelExporter with multi-sheet output (개요, 교수별 상세, 준수율, 이상 탐지) in src/tube_scout/reporting/excel_export.py
- [ ] T046 [US4] Implement year/semester scoping for reports in src/tube_scout/reporting/department_report.py
- [ ] T047 [US4] Add `report department` CLI subcommand (--channel, --format, --year, --semester) in src/tube_scout/cli/report.py
- [ ] T048 [US4] Save reports to OutputManager timestamped directory
- [ ] T048a [US4] Add performance benchmark: department report generation < 2 min for synthetic 3000-video dataset in tests/integration/test_report_performance.py

**Checkpoint**: HTML and Excel department reports generated with correct data, scoped by year/semester, SC-004 benchmark passing

---

## Phase 7: User Story 5 — Title Validation (Priority: P2)

**Goal**: Detect title errors with 9 rules (V-001~V-009), correct severity classification

**Independent Test**: Inject known errors into data, verify 100% detection with correct rule IDs

### Tests for User Story 5

- [ ] T049 [P] [US5] Write unit tests for each validation rule (V-001 to V-009) in tests/unit/test_validator.py
- [ ] T050 [P] [US5] Write adversary tests for edge cases (all valid data, supplementary only, single video) in tests/adversary/test_validation_edge_cases.py

### Implementation for User Story 5

- [ ] T051 [US5] Implement check_year_mismatch (V-001) in src/tube_scout/services/validator.py
- [ ] T052 [US5] Implement check_duplicates (V-002) in src/tube_scout/services/validator.py
- [ ] T053 [US5] Implement check_invalid_week (V-003) in src/tube_scout/services/validator.py
- [ ] T054 [US5] Implement check_name_inconsistency (V-004) using Levenshtein distance in src/tube_scout/services/validator.py
- [ ] T055 [US5] Implement check_parse_failures (V-005) in src/tube_scout/services/validator.py
- [ ] T056 [US5] Implement check_session_gaps (V-006) in src/tube_scout/services/validator.py
- [ ] T057 [US5] Implement check_duration_outliers (V-007) in src/tube_scout/services/validator.py
- [ ] T058 [US5] Implement check_missing_weeks (V-008) in src/tube_scout/services/validator.py
- [ ] T059 [US5] Implement check_upload_gaps (V-009) in src/tube_scout/services/validator.py
- [ ] T060 [US5] Implement run_all_validations(parsed_titles, videos, calendar) → list[ValidationFinding] in src/tube_scout/services/validator.py
- [ ] T061 [US5] Integrate validation results into department report (section + Excel sheet) in src/tube_scout/reporting/department_report.py
- [ ] T062 [US5] Create validate CLI subcommand (--channel, --year, --semester, --output, --rules) in src/tube_scout/cli/validate_cli.py
- [ ] T063 [US5] Register validate subcommand in src/tube_scout/cli/main.py
- [ ] T064 [US5] Store validation results to OutputManager timestamped directory as JSON

**Checkpoint**: All 9 validation rules detect injected errors with correct severity; results in report and CLI

---

## Phase 8: User Story 6 — Timestamped Output Management (Priority: P3)

**Goal**: All output in timestamped directories, latest symlink, no overwrites

**Independent Test**: Run pipeline twice, verify two directories exist, latest points to newest

### Tests for User Story 6

- [ ] T065 [P] [US6] Write integration tests for output isolation (multiple runs, latest symlink, --output-dir override) in tests/integration/test_output_isolation.py

### Implementation for User Story 6

- [ ] T066 [US6] Integrate OutputManager into all collect/analyze/report commands in src/tube_scout/cli/
- [ ] T067 [US6] Implement --output-dir CLI override across all commands
- [ ] T068 [US6] Write end-to-end integration test: auth → collect → parse → validate → report → verify output structure in tests/integration/test_admin_flow.py

**Checkpoint**: Two independent runs produce separate timestamped directories, latest symlink correct

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Quality, consistency, and regression prevention

- [ ] T069 Run ruff check and fix all lint issues across new files
- [ ] T070 Verify all existing tests still pass (no regressions)
- [ ] T071 Run full test suite including all new tests
- [ ] T072 Verify all CLI commands from contracts/cli-commands.md are registered and respond to --help
- [ ] T073 Validate quickstart.md workflow end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — MVP, start first
- **US2 (Phase 4)**: Depends on Phase 2 — can run parallel with US1
- **US3 (Phase 5)**: Depends on US2 (needs parsed titles)
- **US4 (Phase 6)**: Depends on US2 (needs parsed titles) + optionally US5 (validation in report)
- **US5 (Phase 7)**: Depends on US2 (needs parsed titles)
- **US6 (Phase 8)**: Depends on Phase 2 — can start early but full integration needs US1-US5
- **Polish (Phase 9)**: Depends on all user stories

### User Story Dependencies Graph

```
Phase 2 (Foundational)
  ├── US1 (Multi-Channel Auth) ── independent
  ├── US2 (Title Parsing) ──┬── US3 (Search)
  │                         ├── US4 (Department Report)
  │                         └── US5 (Validation)
  └── US6 (Output Management) ── integrates with all
```

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD)
- Models before services
- Services before CLI commands
- Core implementation before edge case handling

### Parallel Opportunities

**After Phase 2 completes:**
- US1 + US2 can run in parallel (independent)

**After US2 completes:**
- US3 + US4 + US5 can run in parallel (all depend only on US2)

---

## Parallel Example: After Phase 2

```bash
# 2 user stories can start simultaneously:
Agent 1: US1 — Multi-channel auth (T013-T021)
Agent 2: US2 — Title parsing (T022-T031)
```

## Parallel Example: After US2

```bash
# 3 user stories can start simultaneously:
Agent 1: US3 — Search (T032-T037)
Agent 2: US4 — Department report (T038-T048)
Agent 3: US5 — Validation (T049-T064)
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US1 (Multi-channel auth)
4. Complete Phase 4: US2 (Title parsing)
5. **STOP and VALIDATE**: Auth works for multiple channels, titles parsed correctly
6. This alone delivers core value — structured data from any department channel

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 + US2 → Auth + title parsing (MVP)
3. US3 → Search filtering
4. US4 + US5 → Reports + validation (parallel)
5. US6 → Output management integration
6. Each increment adds value without breaking previous work

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- TDD mandatory: write tests first (RED) → implement (GREEN) → refactor
- Commit after each task or logical group
- All error messages in English
- Google docstrings in English on all functions
- Type annotations on all function params and returns
