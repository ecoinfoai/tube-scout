# Tasks: Lecture Video Content Reuse Detection

**Input**: Design documents from `/specs/007-content-reuse-detection/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md

**Tests**: TDD mandatory per CLAUDE.md — tests written FIRST, then implementation.

**Organization**: Tasks grouped by user story for independent implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1-US6)
- Exact file paths included

---

## Phase 1: Setup

**Purpose**: New models, storage infrastructure, OAuth scope change

- [ ] T001 Create Pydantic content models (ProcessingStatus, CaptionFingerprint, ComparisonResult, QualityCheckResult, SuspicionScore) in src/tube_scout/models/content.py
- [ ] T002 [P] Create SQLite storage wrapper with schema init (processing_status, fingerprint_hashes, comparison_results, quality_results tables) in src/tube_scout/storage/content_db.py
- [ ] T003 [P] Create SRT parser utility (SRT text → list of segment dicts with text/start/duration) in src/tube_scout/services/srt_parser.py
- [ ] T004 Update OAuth scope from youtube.readonly to youtube.force-ssl in src/tube_scout/services/auth.py (SCOPES constant)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Captions API client and content CLI group — required by all user stories

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Write tests for Captions API client (list, download, SRT parse, quota tracking, error handling) in tests/unit/test_captions_api.py
- [ ] T006 Implement Captions API client (list caption tracks, download SRT, parse to segments, quota tracking) in src/tube_scout/services/captions_api.py
- [ ] T007 [P] Write tests for content_db CRUD operations (insert/query processing_status, fingerprints, comparisons, quality_results) in tests/unit/test_content_db.py
- [ ] T008 [P] Write tests for SRT parser (valid SRT, empty SRT, malformed timestamps, multi-line text) in tests/unit/test_srt_parser.py
- [ ] T009 [P] Write tests for content models (validation, serialization, enum values) in tests/unit/test_content_models.py
- [ ] T010 Register content command group (tube-scout content) in src/tube_scout/cli/content.py and wire to main app in src/tube_scout/cli/main.py

**Checkpoint**: Foundation ready — CaptionsAPI, SQLite DB, SRT parser, content CLI group all operational

---

## Phase 3: User Story 1 — Caption Collection for Private Videos (Priority: P1) 🎯 MVP

**Goal**: Collect captions from all videos (public + private) with checkpoint resume and incremental processing

**Independent Test**: Run `tube-scout collect transcripts --channel <alias>`, verify public captions collected instantly + private captions collected via Captions API + processing status tracked in SQLite

### Tests for User Story 1

- [ ] T011 [P] [US1] Write tests for enhanced TranscriptService (Captions API fallback when VideoUnplayable, SRT→segment conversion, processing status updates) in tests/unit/test_transcript_enhanced.py
- [ ] T012 [P] [US1] Write integration test for caption collection pipeline (public via transcript-api, private via Captions API, incremental skip, quota limit) in tests/integration/test_caption_collection.py

### Implementation for User Story 1

- [ ] T013 [US1] Enhance TranscriptService with Captions API fallback: try youtube-transcript-api → if VideoUnplayable, use CaptionsAPI client → update processing_status in SQLite, in src/tube_scout/services/transcript.py
- [ ] T014 [US1] Update collect transcripts CLI command: add --private-only and --quota-limit options, integrate SQLite status tracking, show Rich progress per video, in src/tube_scout/cli/collect.py
- [ ] T015 [US1] Write adversary tests (quota exhaustion mid-batch, network error during download, malformed SRT from API, concurrent access to SQLite) in tests/adversary/test_caption_adversary.py

**Checkpoint**: Caption collection works for public + private videos with resume capability

---

## Phase 4: User Story 2 — Multi-Indicator Reuse Detection (Priority: P1)

**Goal**: Generate fingerprints, match comparison pairs, compute 5 indicators and suspicion score

**Independent Test**: Run `tube-scout content fingerprint` then `tube-scout content compare`, verify comparison results with 5 indicators and suspicion grades in SQLite

### Tests for User Story 2

- [ ] T016 [P] [US2] Write tests for fingerprint service (SHA-256 hash, embedding generation mock, Parquet storage) in tests/unit/test_fingerprint.py
- [ ] T017 [P] [US2] Write tests for content comparator (5 indicators calculation, suspicion score formula, grade assignment, pair matching logic) in tests/unit/test_content_comparator.py
- [ ] T018 [P] [US2] Write integration test for fingerprint→compare pipeline (end-to-end with mock captions and parsed titles) in tests/integration/test_content_pipeline.py

### Implementation for User Story 2

- [ ] T019 [P] [US2] Implement fingerprint service (SHA-256 from full text, sentence-transformer embedding, store hash in SQLite + embedding in Parquet) in src/tube_scout/services/fingerprint.py
- [ ] T020 [US2] Implement content comparator (pair matching from ParsedTitle data, 5 indicators: hash match/cosine similarity/change rate/new terms/duration diff, weighted suspicion score, grade assignment) in src/tube_scout/services/content_comparator.py
- [ ] T021 [US2] Implement content fingerprint CLI command (load captions, generate fingerprints, show progress, update processing_status) in src/tube_scout/cli/content.py
- [ ] T022 [US2] Implement content compare CLI command (match pairs, compute indicators, store results, display summary table) in src/tube_scout/cli/content.py
- [ ] T023 [US2] Write adversary tests (empty captions, single-video course with no pair, identical hash pair, cosine similarity edge cases 0.0/1.0) in tests/adversary/test_content_adversary.py

**Checkpoint**: Fingerprint + compare pipeline produces suspicion scores and grades

---

## Phase 5: User Story 3 — Administrator Review Workflow (Priority: P1)

**Goal**: View comparison results by priority, mark review status, persist decisions

**Independent Test**: Run `tube-scout content review --status UNREVIEWED`, see flagged items, mark one as CONFIRMED_DUPLICATE, re-run and verify it no longer appears

### Tests for User Story 3

- [ ] T024 [P] [US3] Write tests for review CLI (list by status/grade, mark status, re-alerting exclusion) in tests/unit/test_content_review.py

### Implementation for User Story 3

- [ ] T025 [US3] Implement content review CLI command (list mode: Rich table sorted by suspicion_score, filter by --status/--grade; mark mode: update review_status by comparison_id) in src/tube_scout/cli/content.py
- [ ] T026 [US3] Update content compare to exclude previously reviewed pairs (CONFIRMED_DUPLICATE/FALSE_POSITIVE) from re-alerting in src/tube_scout/services/content_comparator.py

**Checkpoint**: Full reuse detection workflow operational — collect → fingerprint → compare → review

---

## Phase 6: User Story 4 — Content Quality Checklist (Priority: P2)

**Goal**: Automated Q-001~Q-005 quality checks per video

**Independent Test**: Run `tube-scout content quality --channel <alias>`, verify per-video quality results in SQLite

### Tests for User Story 4

- [ ] T027 [P] [US4] Write tests for quality checker (Q-001 voice presence, Q-002 min duration, Q-003 course relevance, Q-004 silence ratio, Q-005 speech density, pass_count calculation) in tests/unit/test_quality_checker.py

### Implementation for User Story 4

- [ ] T028 [US4] Implement quality checker service (5 rules with configurable thresholds, store results in SQLite) in src/tube_scout/services/quality_checker.py
- [ ] T029 [US4] Implement content quality CLI command (run checks, show Rich results table, filter by pass/fail) in src/tube_scout/cli/content.py

**Checkpoint**: Quality checklist independently functional

---

## Phase 7: User Story 5 — Content Quality Report (Priority: P2)

**Goal**: Generate HTML/Excel/JSON reports with suspicion summary, quality results, review status

**Independent Test**: Run `tube-scout report content --format xlsx`, verify report file with expected sheets and data

### Tests for User Story 5

- [ ] T030 [P] [US5] Write tests for content report generator (HTML structure, Excel sheets, JSON schema, empty data handling) in tests/unit/test_content_report.py

### Implementation for User Story 5

- [ ] T031 [US5] Implement content report generator (suspicion summary by grade, per-professor rates, quality checklist results, review status summary) in src/tube_scout/reporting/content_report.py
- [ ] T032 [US5] Create HTML report template (suspicion table, heatmap placeholder, quality dashboard) in src/tube_scout/reporting/templates/content_quality.html
- [ ] T033 [US5] Implement report content CLI command (--format html|xlsx|json, --year, --semester, --output-dir) in src/tube_scout/cli/report.py

**Checkpoint**: Reports generated in all 3 formats

---

## Phase 8: User Story 6 — Pipeline Scan Command (Priority: P2)

**Goal**: Single command runs fingerprint → compare → quality with checkpoint

**Independent Test**: Run `tube-scout content scan --channel <alias> --year-from 2025 --year-to 2026`, verify all 3 stages complete

### Tests for User Story 6

- [ ] T034 [P] [US6] Write tests for scan pipeline (sequential execution, checkpoint skip, force-refresh) in tests/unit/test_content_scan.py

### Implementation for User Story 6

- [ ] T035 [US6] Implement content scan CLI command (orchestrate fingerprint→compare→quality, checkpoint per stage, Rich progress) in src/tube_scout/cli/content.py

**Checkpoint**: Full pipeline available as single command

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Integration testing, edge cases, security

- [ ] T036 [P] Write end-to-end integration test (collect→fingerprint→compare→quality→review→report full flow) in tests/integration/test_content_e2e.py
- [ ] T037 [P] Add Excel formula injection sanitization to content report (reuse _sanitize_cell pattern) in src/tube_scout/reporting/content_report.py
- [ ] T038 [P] Add LLM rate limiter to llm_adapter.py for change summary calls (P-02 from idea4) in src/tube_scout/services/llm_adapter.py
- [ ] T039 Run quickstart.md validation — verify documented commands work as described

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1 Caption Collection)**: Depends on Phase 2
- **Phase 4 (US2 Reuse Detection)**: Depends on Phase 3 (needs collected captions)
- **Phase 5 (US3 Admin Review)**: Depends on Phase 4 (needs comparison results)
- **Phase 6 (US4 Quality Checklist)**: Depends on Phase 3 only (needs captions, not comparisons)
- **Phase 7 (US5 Reports)**: Depends on Phase 4 + Phase 6 (needs comparisons + quality data)
- **Phase 8 (US6 Scan Pipeline)**: Depends on Phase 4 + Phase 6 (orchestrates existing commands)
- **Phase 9 (Polish)**: Depends on all desired user stories

### Parallel Opportunities

After Phase 3 (caption collection) completes:
- **Phase 4** (reuse detection) and **Phase 6** (quality checklist) can run in parallel
- Phase 5 (review) must wait for Phase 4
- Phase 7 (reports) and Phase 8 (scan) can start after Phases 4+6

### Within Each Phase

- All tasks marked [P] within a phase can run in parallel
- Tests before implementation (TDD)
- Models → Services → CLI (dependency order)

---

## Parallel Example: Phase 4 (User Story 2)

```
# Tests in parallel:
T016: test_fingerprint.py
T017: test_content_comparator.py
T018: test_content_pipeline.py

# After tests fail (RED), implement in parallel:
T019: fingerprint.py (independent)

# Then sequential:
T020: content_comparator.py (depends on T019 for fingerprint format)
T021: content fingerprint CLI
T022: content compare CLI
T023: adversary tests
```

---

## Implementation Strategy

### MVP First (User Stories 1-3)

1. Phase 1 + 2: Setup + Foundation
2. Phase 3: Caption collection (US1) → **Test: captions collected for public+private**
3. Phase 4: Reuse detection (US2) → **Test: suspicion scores calculated**
4. Phase 5: Admin review (US3) → **Test: review workflow operational**
5. **STOP and VALIDATE**: Core reuse detection fully functional

### Incremental Delivery

6. Phase 6: Quality checklist (US4) → adds quality analysis
7. Phase 7: Reports (US5) → adds report generation
8. Phase 8: Scan pipeline (US6) → adds convenience command
9. Phase 9: Polish → hardening and integration tests

---

## Notes

- TDD mandatory: write test → verify RED → implement → verify GREEN
- Commit after each task with conventional commit format
- SQLite DB created per project at `projects/{project}/tube_scout.db`
- Embedding model download (~2GB) happens on first `content fingerprint` run
- Captions API quota: 250 units/video — test with --quota-limit to avoid exhaustion
