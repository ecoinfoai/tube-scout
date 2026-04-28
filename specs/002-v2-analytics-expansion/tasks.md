# Tasks: Tube Scout v2 Analytics Expansion

**Input**: Design documents from `/specs/002-v2-analytics-expansion/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-commands.md

**Tests**: TDD mandatory per project convention. Test tasks included for each user story.

**Organization**: Tasks grouped by user story. Each story independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Add new dependencies and base project configuration

- [ ] T001 Add new dependencies (anthropic, openai, statsmodels, prophet, transformers, torch) to pyproject.toml
- [ ] T002 Run `uv sync` and verify all existing 200+ tests still pass
- [ ] T003 Update flake.nix devShell if needed for new native dependencies (prophet, torch)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared models and infrastructure that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 [P] Create analytics models (AnalyticsReport, DailyMetrics, TrafficSource, DemographicGroup, GeographyData, DeviceData, PlaybackLocation, SubscriberChange) in src/tube_scout/models/analytics.py
- [ ] T005 [P] Create AcademicCalendar and CalendarEvent models, extend CollectionState with analytics_last_dates, extend Settings with llm_provider and analytics_start_date in src/tube_scout/models/config.py
- [ ] T006 [P] Extend Video model with new fields (description, tags, category_id, thumbnail_url, default_language, privacy_status, topic_categories, has_captions) in src/tube_scout/models/video.py
- [ ] T007 [P] Extend Channel model with new fields (subscriber_count, total_view_count, description) in src/tube_scout/models/channel.py
- [ ] T008 [P] Extend Comment model with new fields (parent_comment_id, reply_count) in src/tube_scout/models/comment.py
- [ ] T009 [P] Write tests for all new/extended models in tests/unit/test_analytics_models.py and update tests/unit/test_models.py
- [ ] T010 Create LLMAdapter class with Claude default + OpenAI support in src/tube_scout/services/llm_adapter.py
- [ ] T011 Write tests for LLMAdapter (mock both providers) in tests/unit/test_llm_adapter.py

**Checkpoint**: Foundation ready — all models extended, LLM adapter available, existing tests green

---

## Phase 3: User Story 1 — Comprehensive Analytics Data Collection (Priority: P1) MVP

**Goal**: Collect all 8 YouTube Analytics report types with incremental sync and 2-year default window

**Independent Test**: Run `tube-scout collect analytics` for a configured channel and verify all report types stored with correct schema

### Tests for User Story 1

- [ ] T015 [P] [US1] Write unit tests for 8 analytics report query methods in tests/unit/test_youtube_analytics_ext.py
- [ ] T016 [P] [US1] Write unit tests for incremental date tracking in tests/unit/test_checkpoint.py (extend existing)
- [ ] T017 [P] [US1] Write adversary tests for quota exhaustion, API errors, empty reports in tests/adversary/test_analytics_failures.py

### Implementation for User Story 1

- [ ] T018 [US1] Implement daily time-series collection (day dimension, views/watchTime/avgDuration/avgPercentage) in src/tube_scout/services/youtube_analytics.py
- [ ] T019 [US1] Implement traffic source collection in src/tube_scout/services/youtube_analytics.py
- [ ] T020 [US1] Implement demographics collection in src/tube_scout/services/youtube_analytics.py
- [ ] T021 [US1] Implement geography collection in src/tube_scout/services/youtube_analytics.py
- [ ] T022 [US1] Implement device/OS collection in src/tube_scout/services/youtube_analytics.py
- [ ] T023 [US1] Implement playback location collection in src/tube_scout/services/youtube_analytics.py
- [ ] T024 [US1] Implement subscriber change collection in src/tube_scout/services/youtube_analytics.py
- [ ] T025 [US1] Implement engagement metrics collection in src/tube_scout/services/youtube_analytics.py
- [ ] T026 [US1] Implement incremental sync logic (analytics_last_dates tracking, startDate override) in src/tube_scout/services/youtube_analytics.py
- [ ] T027 [US1] Implement retry with exponential backoff for API errors and quota limits in src/tube_scout/services/youtube_analytics.py
- [ ] T028 [US1] Add `collect analytics` CLI subcommand with --start-date, --report-type, --incremental flags in src/tube_scout/cli/collect.py
- [ ] T029 [US1] Implement storage for all analytics report types (Parquet for time-series, JSON for dimensional) in src/tube_scout/storage/ (extend existing)
- [ ] T030 [US1] Write integration test for full analytics collection flow in tests/integration/test_analytics_collect.py

**Checkpoint**: All 8 analytics report types collected, incremental sync working, data stored correctly

---

## Phase 4: User Story 2 — Extended Video and Channel Metadata (Priority: P1)

**Goal**: Collect complete video/channel metadata and comment replies

**Independent Test**: Run `tube-scout collect videos` and verify all extended fields populated; run `tube-scout collect comments` and verify replies collected

### Tests for User Story 2

- [ ] T031 [P] [US2] Write unit tests for extended video metadata collection in tests/unit/test_youtube_data.py (extend existing)
- [ ] T032 [P] [US2] Write unit tests for comment reply collection in tests/unit/test_youtube_data.py (extend existing)
- [ ] T033 [P] [US2] Write unit tests for new video detection (incremental) in tests/unit/test_youtube_data.py (extend existing)

### Implementation for User Story 2

- [ ] T034 [US2] Extend get_video_details() to request snippet,status,topicDetails parts and populate new Video fields in src/tube_scout/services/youtube_data.py
- [ ] T035 [US2] Extend get_channel_info() to return subscriber_count, total_view_count, description in src/tube_scout/services/youtube_data.py
- [ ] T036 [US2] Implement comment reply collection via comments().list(parentId=...) in src/tube_scout/services/youtube_data.py
- [ ] T037 [US2] Implement new video detection (diff existing vs API) for incremental collection in src/tube_scout/services/youtube_data.py
- [ ] T038 [US2] Update `collect videos` CLI to use extended metadata and support incremental in src/tube_scout/cli/collect.py
- [ ] T039 [US2] Update `collect comments` CLI with --include-replies flag in src/tube_scout/cli/collect.py
- [ ] T039a [US2] Handle 404/403 for deleted/private videos during incremental collection (skip and log warning) in src/tube_scout/services/youtube_data.py

**Checkpoint**: Full video metadata, channel info, and comment replies collected; incremental video sync working; deleted/private videos handled gracefully

---

## Phase 5: User Story 3 — Comment Sentiment Analysis (Priority: P2)

**Goal**: LLM and local NLP backends for comment sentiment analysis with explicit selection

**Independent Test**: Provide sample comments and verify sentiment labels + confidence scores from each backend

### Tests for User Story 3

- [ ] T040 [P] [US3] Write unit tests for LLM sentiment backend (mock LLMAdapter) in tests/unit/test_sentiment_llm.py
- [ ] T041 [P] [US3] Write unit tests for local NLP sentiment backend in tests/unit/test_sentiment_local.py
- [ ] T042 [P] [US3] Write adversary tests for unavailable backend, malformed LLM response in tests/adversary/test_llm_failures.py

### Implementation for User Story 3

- [ ] T043 [US3] Implement backend="llm" in SentimentService using LLMAdapter with structured output (positive/neutral/negative + confidence); handle mixed Korean+English comments via language-aware prompt in src/tube_scout/services/sentiment.py
- [ ] T044 [US3] Implement backend="local" in SentimentService using transformers pipeline with Korean model (KcELECTRA or KR-FinBert) in src/tube_scout/services/sentiment.py
- [ ] T045 [US3] Implement clear error reporting when selected backend is unavailable (no auto-fallback) and graceful empty return when video has comments disabled in src/tube_scout/services/sentiment.py
- [ ] T046 [US3] Verify existing content-hash caching works with both new backends in src/tube_scout/services/sentiment.py
- [ ] T047 [US3] Update `analyze sentiment` CLI to remove skip backend from user-facing options in src/tube_scout/cli/analyze.py
- [ ] T047a [US3] Add timed benchmark test: 100 Korean comments sentiment analysis < 60s (LLM backend) in tests/unit/test_sentiment_llm.py
- [ ] T047b [US3] Create labeled Korean comment sample set (20 comments) and add accuracy validation test (>=80% agreement) in tests/unit/test_sentiment_local.py

**Checkpoint**: Both LLM and local sentiment backends functional, explicit selection, caching working, SC-003/SC-004 benchmarks passing

---

## Phase 6: User Story 4 — Topic-Sentiment Mapping and Question Extraction (Priority: P2)

**Goal**: Group comments by topic, extract questions, cross-reference with retention hotspots

**Independent Test**: Provide comments with known topics/questions and verify clusters, per-topic sentiment, and hotspot matches

### Tests for User Story 4

- [ ] T048 [P] [US4] Write unit tests for topic extraction in tests/unit/test_topic_extractor.py
- [ ] T049 [P] [US4] Write unit tests for question extraction and hotspot cross-reference in tests/unit/test_topic_extractor.py

### Implementation for User Story 4

- [ ] T050 [US4] Create TopicExtractorService with LLM-based topic clustering (batch of 20 comments per call) in src/tube_scout/services/topic_extractor.py
- [ ] T051 [US4] Implement question identification and extraction in src/tube_scout/services/topic_extractor.py
- [ ] T052 [US4] Implement cross_reference_questions_hotspots() with relevance scoring (replace existing stub) in src/tube_scout/services/sentiment.py
- [ ] T053 [US4] Create TopicCluster and QuestionMatch models storage in src/tube_scout/storage/ (JSON format)
- [ ] T054 [US4] Add `analyze topic` CLI subcommand in src/tube_scout/cli/analyze.py
- [ ] T055 [US4] Handle edge case: video with no comments or comments disabled returns empty result without errors in src/tube_scout/services/topic_extractor.py

**Checkpoint**: Topics clustered with per-topic sentiment, questions extracted and matched to hotspots

---

## Phase 7: User Story 5 — LLM-Powered Transcript Analysis (Priority: P2)

**Goal**: Segment transcripts into chapters with summaries, difficulty scores, and topic tags via LLM

**Independent Test**: Provide a transcript and verify chapter boundaries, summaries, difficulty scores, and tags generated

### Tests for User Story 5

- [ ] T056 [P] [US5] Write unit tests for LLM-based transcript segmentation (mock LLMAdapter) in tests/unit/test_segmenter_llm.py
- [ ] T057 [P] [US5] Write unit tests for difficulty prediction and retention comparison in tests/unit/test_segmenter_llm.py

### Implementation for User Story 5

- [ ] T058 [US5] Implement LLM call in SegmenterService.segment_transcript() replacing NotImplementedError in src/tube_scout/services/segmenter.py
- [ ] T059 [US5] Implement difficulty score prediction (0.0-1.0) per segment via LLM in src/tube_scout/services/segmenter.py
- [ ] T060 [US5] Implement topic tag generation per segment via LLM in src/tube_scout/services/segmenter.py
- [ ] T061 [US5] Ensure Korean-language transcript handling produces Korean summaries in src/tube_scout/services/segmenter.py
- [ ] T062 [US5] Implement compare_with_retention() to cross-reference predicted difficulty with actual hotspots in src/tube_scout/services/segmenter.py
- [ ] T063 [US5] Handle malformed LLM responses gracefully (retry once, then return partial result) in src/tube_scout/services/segmenter.py
- [ ] T063a [US5] Add boundary accuracy test with reference-segmented transcript: 70% alignment within 30s tolerance in tests/unit/test_segmenter_llm.py

**Checkpoint**: Transcripts segmented with chapters, summaries, difficulty, and tags; Korean support verified; SC-005 benchmark passing

---

## Phase 8: User Story 6 — Education Quality Scoring (Priority: P3)

**Goal**: RACED 5-axis automatic quality scoring via LLM

**Independent Test**: Provide transcript and verify RACED scores returned for each axis + overall

### Tests for User Story 6

- [ ] T064 [P] [US6] Write unit tests for EQS LLM evaluation (mock LLMAdapter) in tests/unit/test_eqs_llm.py

### Implementation for User Story 6

- [ ] T065 [US6] Implement LLM call in EQSService.evaluate() replacing NotImplementedError in src/tube_scout/services/eqs.py
- [ ] T066 [US6] Ensure scores are comparable across videos (consistent prompt, normalized output) in src/tube_scout/services/eqs.py
- [ ] T067 [US6] Handle partial/malformed LLM responses in src/tube_scout/services/eqs.py

**Checkpoint**: EQS scoring functional, RACED 5-axis + overall weighted score per video

---

## Phase 9: User Story 7 — Advanced Time Series Forecasting (Priority: P3)

**Goal**: ARIMA/Prophet forecasting with academic calendar integration

**Independent Test**: Provide 180+ days of daily data + calendar file, verify forecast with confidence intervals and calendar annotations

### Tests for User Story 7

- [ ] T068 [P] [US7] Write unit tests for ARIMA forecasting in tests/unit/test_forecaster_ext.py
- [ ] T069 [P] [US7] Write unit tests for Prophet forecasting with calendar events in tests/unit/test_forecaster_ext.py
- [ ] T070 [P] [US7] Write unit tests for auto model selection logic in tests/unit/test_forecaster_ext.py

### Implementation for User Story 7

- [ ] T071 [US7] Connect daily time-series data (from US1) to forecaster pipeline input in src/tube_scout/services/forecaster.py
- [ ] T072 [US7] Implement ARIMA model backend in ForecasterService in src/tube_scout/services/forecaster.py
- [ ] T073 [US7] Implement Prophet model backend with academic calendar as holidays in src/tube_scout/services/forecaster.py
- [ ] T074 [US7] Implement auto model selection (< 90d: linear, 90-365d: ARIMA, >365d: Prophet) in src/tube_scout/services/forecaster.py
- [ ] T075 [US7] Add `calendar set` and `calendar show` CLI commands in src/tube_scout/cli/main.py
- [ ] T076 [US7] Update `analyze forecast` CLI with --model and --calendar flags in src/tube_scout/cli/analyze.py
- [ ] T077 [US7] Handle missing days in time-series data (interpolation or gap annotation) in src/tube_scout/services/forecaster.py
- [ ] T077a [US7] Add train/test split evaluation test: MAE < 10% on last 30 days held-out data in tests/unit/test_forecaster_ext.py

**Checkpoint**: Forecasting with ARIMA/Prophet, academic calendar integration, auto model selection; SC-006 MAE benchmark passing

---

## Phase 10: User Story 8 — Comment Insight Report (Priority: P3)

**Goal**: Dedicated report with per-topic sentiment summaries and auto-extracted FAQ

**Independent Test**: Provide analyzed comment data, verify report contains topic summaries, sentiment distribution, FAQ

### Tests for User Story 8

- [ ] T078 [P] [US8] Write unit tests for comment insight report generation in tests/unit/test_comment_report.py

### Implementation for User Story 8

- [ ] T079 [US8] Create CommentReportGenerator in src/tube_scout/reporting/comment_report.py
- [ ] T080 [US8] Create HTML template for comment insight report in src/tube_scout/reporting/templates/
- [ ] T081 [US8] Implement per-topic sentiment summary section in report in src/tube_scout/reporting/comment_report.py
- [ ] T082 [US8] Implement auto-extracted FAQ section in report in src/tube_scout/reporting/comment_report.py
- [ ] T083 [US8] Add `report comment-insight` CLI subcommand in src/tube_scout/cli/report.py

**Checkpoint**: Comment insight report generated in HTML with topic summaries and FAQ

---

## Phase 11: User Story 9 — Channel-Level Comprehensive Report (Priority: P3)

**Goal**: Channel report with video comparisons, trends, forecasts, and improvement suggestions

**Independent Test**: Provide full dataset, verify report includes comparisons, trends, forecasts, suggestions

### Tests for User Story 9

- [ ] T084 [P] [US9] Write unit tests for improvement suggestion generation in tests/unit/test_channel_report.py
- [ ] T085 [P] [US9] Write unit tests for video comparison logic in tests/unit/test_channel_report.py

### Implementation for User Story 9

- [ ] T086 [US9] Create ImprovementSuggestion model storage in src/tube_scout/storage/ (JSON format)
- [ ] T087 [US9] Implement video comparison analysis (by topic, length, format) in src/tube_scout/reporting/channel_report.py
- [ ] T088 [US9] Implement improvement suggestion generation logic in src/tube_scout/reporting/channel_report.py
- [ ] T089 [US9] Integrate time-series trend charts and forecast visualizations in src/tube_scout/reporting/channel_report.py
- [ ] T090 [US9] Update channel report HTML template with comparison tables, trends, suggestions in src/tube_scout/reporting/templates/
- [ ] T091 [US9] Update `report channel` CLI to include all new sections in src/tube_scout/cli/report.py

**Checkpoint**: Channel report complete with comparisons, trends, forecasts, and actionable suggestions

---

## Phase 12: User Story 10 — Bulk Data Download via Reporting API (Priority: P3)

**Goal**: YouTube Reporting API bulk CSV download for large channels

**Independent Test**: Create reporting job, poll status, verify downloaded CSV matches expected schema

### Tests for User Story 10

- [ ] T092 [P] [US10] Write unit tests for reporting job lifecycle (create, poll, download) in tests/unit/test_youtube_reporting.py
- [ ] T093 [P] [US10] Write adversary tests for job failure, timeout in tests/adversary/test_reporting_failures.py

### Implementation for User Story 10

- [ ] T094 [US10] Create ReportingJob model in src/tube_scout/models/analytics.py
- [ ] T095 [US10] Create YouTubeReportingService (job create, poll, CSV download) in src/tube_scout/services/youtube_reporting.py
- [ ] T096 [US10] Implement CSV parsing with polars and storage in src/tube_scout/services/youtube_reporting.py
- [ ] T097 [US10] Add `collect bulk` CLI subcommand with --report-type and --status flags in src/tube_scout/cli/collect.py
- [ ] T098 [US10] Verify existing `yt-analytics.readonly` scope is sufficient for Reporting API; add `yt-analytics-monetary.readonly` only if revenue reports are requested in src/tube_scout/services/auth.py

**Checkpoint**: Bulk data download working, CSVs stored, job status visible via CLI

---

## Phase 13: Polish & Cross-Cutting Concerns

**Purpose**: Quality, consistency, and regression prevention

- [ ] T099 [P] Run ruff check and fix all lint issues across new files
- [ ] T100 [P] Verify all 200+ existing tests still pass (no regressions)
- [ ] T101 Run full test suite including all new tests, ensure 100% new FR coverage
- [ ] T102 Update `collect all` CLI to include analytics collection step in src/tube_scout/cli/collect.py
- [ ] T103 Update `analyze all` CLI to include topic analysis step in src/tube_scout/cli/analyze.py
- [ ] T104 Update `tube-scout status` to show analytics collection state in src/tube_scout/cli/status.py
- [ ] T105 Add timing benchmark: channel report generation < 5 min for synthetic 500-video dataset in tests/integration/test_report_performance.py
- [ ] T106 Validate quickstart.md workflow end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — MVP, start first
- **US2 (Phase 4)**: Depends on Phase 2 — can run parallel with US1
- **US3 (Phase 5)**: Depends on Phase 2 (LLMAdapter) — can start after Phase 2
- **US4 (Phase 6)**: Depends on US3 (sentiment) + US1 (retention data for cross-reference)
- **US5 (Phase 7)**: Depends on Phase 2 (LLMAdapter) — can run parallel with US3
- **US6 (Phase 8)**: Depends on US5 (transcript segmentation)
- **US7 (Phase 9)**: Depends on US1 (daily time-series data)
- **US8 (Phase 10)**: Depends on US3 + US4 (sentiment + topic analysis)
- **US9 (Phase 11)**: Depends on US1 + US7 + US8 (analytics + forecasts + comment insights)
- **US10 (Phase 12)**: Depends on Phase 2 — can start after Phase 2 (independent of other stories)
- **Polish (Phase 13)**: Depends on all desired user stories

### User Story Dependencies Graph

```
Phase 2 (Foundational)
  ├── US1 (Analytics Collection) ──┬── US4 (Topic + Question)
  │                                │     └── US8 (Comment Report)
  │                                │           └── US9 (Channel Report)
  │                                └── US7 (Forecasting)
  │                                      └── US9 (Channel Report)
  ├── US2 (Extended Metadata) ─────────── US9 (Channel Report)
  ├── US3 (Sentiment) ────────────┬── US4 (Topic + Question)
  │                               └── US8 (Comment Report)
  ├── US5 (Transcript Analysis) ──── US6 (EQS)
  └── US10 (Bulk Download) ── independent
```

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD)
- Models before services
- Services before CLI commands
- Core implementation before edge case handling

### Parallel Opportunities

**After Phase 2 completes, these can run in parallel:**
- US1 + US2 + US3 + US5 + US10 (all independent of each other)

**After US1 + US3 complete:**
- US4 + US7 can start

**After US5 completes:**
- US6 can start

**After US3 + US4 complete:**
- US8 can start

---

## Parallel Example: Phase 2 (Foundational)

```bash
# All model tasks can run in parallel (different files):
Task T004: "Analytics models in src/tube_scout/models/analytics.py"
Task T005: "Calendar models in src/tube_scout/models/config.py"
Task T006: "Video model extension in src/tube_scout/models/video.py"
Task T007: "Channel model extension in src/tube_scout/models/channel.py"
Task T008: "Comment model extension in src/tube_scout/models/comment.py"

# Then sequentially:
Task T012: "LLMAdapter in src/tube_scout/services/llm_adapter.py"
Task T013: "LLMAdapter tests"
```

## Parallel Example: After Phase 2

```bash
# 5 user stories can start simultaneously:
Agent 1: US1 — Analytics collection (T015-T030)
Agent 2: US2 — Extended metadata (T031-T039)
Agent 3: US3 — Sentiment analysis (T040-T047)
Agent 4: US5 — Transcript analysis (T056-T063)
Agent 5: US10 — Bulk download (T092-T098)
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US1 (Analytics Collection)
4. Complete Phase 4: US2 (Extended Metadata)
5. **STOP and VALIDATE**: Full data collection working with all report types
6. This alone delivers significant value — complete dataset for manual analysis

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 + US2 → Full data collection (MVP)
3. US3 → Sentiment analysis available
4. US4 + US5 → Topic + transcript analysis
5. US6 + US7 → EQS + advanced forecasting
6. US8 + US9 → Comprehensive reports
7. US10 → Bulk download (optimization)
8. Each increment adds value without breaking previous work

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- TDD mandatory: write tests first (RED) → implement (GREEN) → refactor
- Commit after each task or logical group
- All error messages in English
- Google docstrings in English on all functions
- Type annotations on all function params and returns
