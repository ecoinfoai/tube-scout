# Tasks: Tube Scout — 강의 영상 분석 플랫폼

**Input**: Design documents from `/specs/001-lecture-video-analytics/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/cli-commands.md

**Tests**: Included — TDD mandatory per project rules (RED → GREEN → refactor).

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, dependencies, basic structure

- [ ] T001 Create project directory structure per plan.md: `src/tube_scout/`, `src/tube_scout/cli/`, `src/tube_scout/services/`, `src/tube_scout/models/`, `src/tube_scout/storage/`, `src/tube_scout/reporting/`, `src/tube_scout/visualization/`, `tests/unit/`, `tests/integration/`
- [ ] T002 Initialize Python project with `pyproject.toml` — define metadata, dependencies (typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pandas, polars, plotly, jinja2, pydantic), dev dependencies (pytest, pytest-cov, ruff), and `[project.scripts]` entry point `tube-scout = "tube_scout.cli.main:app"`
- [ ] T003 [P] Configure ruff for linting/formatting in `pyproject.toml` and create `ruff.toml` if needed
- [ ] T004 [P] Create `conftest.py` in `tests/` with shared fixtures (tmp_data_dir, mock API responses directory)
- [ ] T005 [P] Add all `__init__.py` files across `src/tube_scout/` package tree

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Tests for Foundational

- [ ] T006 [P] Write tests for Config model validation in `tests/unit/test_models.py` — test channel_id format (UC prefix), non-empty professor_name, list-based channels structure
- [ ] T007 [P] Write tests for JSON store read/write in `tests/unit/test_json_store.py` — test atomic write (temp→rename), read non-existent file, round-trip
- [ ] T008 [P] Write tests for Parquet store read/write in `tests/unit/test_parquet_store.py` — test write DataFrame, read back, append mode
- [ ] T009 [P] Write tests for checkpoint manager in `tests/unit/test_checkpoint.py` — test save/load state, resume detection, force-refresh clearing

### Implementation for Foundational

- [ ] T010 [P] Implement Config pydantic model in `src/tube_scout/models/config.py` — ChannelConfig (channel_id, professor_name), Settings (data_dir, sentiment_backend, default_report_format), AppConfig (channels list, settings)
- [ ] T011 [P] Implement JSON store in `src/tube_scout/storage/json_store.py` — read_json(), write_json() with atomic write (temp file → rename), ensure parent dirs
- [ ] T012 [P] Implement Parquet store in `src/tube_scout/storage/parquet_store.py` — read_parquet(), write_parquet(), append_parquet() using polars
- [ ] T013 [P] Implement checkpoint manager in `src/tube_scout/storage/checkpoint.py` — CollectionState model, save_checkpoint(), load_checkpoint(), clear_checkpoint()
- [ ] T014 Implement Typer app entry point in `src/tube_scout/cli/main.py` — create app with sub-commands (collect, analyze, report, status, list), version callback
- [ ] T015 Implement `tube-scout init` command in `src/tube_scout/cli/main.py` — accept --channel-id, --professor, --data-dir; validate inputs; write config.json
- [ ] T016 Implement `tube-scout status` command in `src/tube_scout/cli/status.py` — read config + checkpoint, display channel info, collection state, analysis completion as rich table

**Checkpoint**: Foundation ready — `tube-scout init` and `tube-scout status` work, storage layer tested

---

## Phase 3: User Story 1 — 교수 영상 식별 및 기본 메트릭 수집 (Priority: P1) 🎯 MVP

**Goal**: 채널 ID와 교수명으로 대상 영상을 식별하고 기본 메트릭(조회수, 좋아요, 댓글 수, 길이)을 수집하여 테이블로 표시

**Independent Test**: `tube-scout init` → `tube-scout collect videos` → `tube-scout list` 실행 시 교수명 필터링된 영상 목록과 메트릭이 표시됨

### Tests for User Story 1

- [ ] T017 [P] [US1] Write tests for Channel model in `tests/unit/test_models.py` — test uploads_playlist_id derivation (UC→UU), validation
- [ ] T018 [P] [US1] Write tests for Video model in `tests/unit/test_models.py` — test field validation, professor_name filter matching (partial match)
- [ ] T019 [P] [US1] Write tests for YouTubeDataService in `tests/unit/test_youtube_data.py` — mock API responses for channels.list, playlistItems.list, videos.list; test pagination; test professor name filtering
- [ ] T020 [P] [US1] Write integration test for collect videos flow in `tests/integration/test_collect_flow.py` — mock API, run collect, verify data files created in data/raw/

### Implementation for User Story 1

- [ ] T021 [P] [US1] Implement Channel model in `src/tube_scout/models/channel.py` — channel_id, channel_name, uploads_playlist_id (auto-derived), professor_name, filtered_video_count, last_collected_at
- [ ] T022 [P] [US1] Implement Video model in `src/tube_scout/models/video.py` — video_id, channel_id, title, published_at, duration_seconds, view_count, like_count, comment_count, has_transcript, transcript_type, has_analytics, collected_at; add title_contains_professor() method (dislike_count 제외 — YouTube API 정책 변경)
- [ ] T023 [US1] Implement YouTubeDataService in `src/tube_scout/services/youtube_data.py` — get_channel_info() via channels.list, list_all_videos() via playlistItems.list with pagination (50/page), get_video_details() via videos.list batch (50/batch), filter_by_professor() applying partial match
- [ ] T024 [US1] Implement `tube-scout collect videos` subcommand in `src/tube_scout/cli/collect.py` — call YouTubeDataService, save to data/raw/channels/{channel_id}/ as JSON+Parquet, update checkpoint, show rich progress bar, handle quota exceeded (save checkpoint, exit code 2)
- [ ] T025 [US1] Implement `tube-scout list` command in `src/tube_scout/cli/status.py` — read videos_meta.json, display rich table (ID, title, date, views, likes, duration), --sort and --limit options

**Checkpoint**: MVP complete — `tube-scout collect videos` + `tube-scout list` show professor's videos with metrics

---

## Phase 4: User Story 2 — 시청 패턴 심층 분석 (Priority: P1)

**Goal**: 영상별 시청 유지율 곡선을 수집하고, Rewatch Hotspot과 Skip Zone을 자동 식별하여 시각화

**Independent Test**: `tube-scout collect retention --video-id X` → `tube-scout analyze retention --video-id X` → HTML 차트에 유지율 곡선 + 하이라이트 구간 표시

### Tests for User Story 2

- [ ] T026 [P] [US2] Write tests for ViewingPattern model in `tests/unit/test_models.py` — test elapsed_ratio range, hotspot/skip detection thresholds
- [ ] T027 [P] [US2] Write tests for YouTubeAnalyticsService in `tests/unit/test_youtube_analytics.py` — mock Analytics API response for audienceWatchRatio, test OAuth error handling, test graceful degradation
- [ ] T028 [P] [US2] Write tests for retention analysis (hotspot/skip detection) in `tests/unit/test_youtube_analytics.py` — test with synthetic retention curves, verify hotspot/skip identification

### Implementation for User Story 2

- [ ] T029 [P] [US2] Implement ViewingPattern model in `src/tube_scout/models/video.py` — elapsed_ratio, audience_watch_ratio, relative_retention, is_rewatch_hotspot, is_skip_zone
- [ ] T030 [US2] Implement YouTubeAnalyticsService in `src/tube_scout/services/youtube_analytics.py` — OAuth2 authentication flow, get_retention_data() via reports.query, handle auth errors with graceful message
- [ ] T031 [US2] Implement retention analysis logic in `src/tube_scout/services/youtube_analytics.py` — detect_rewatch_hotspots() (above-average rewatch threshold), detect_skip_zones() (below-average retention threshold)
- [ ] T032 [US2] Implement `tube-scout collect retention` subcommand in `src/tube_scout/cli/collect.py` — call AnalyticsService, save to data/raw/retention/{video_id}.parquet, handle no-auth gracefully
- [ ] T033 [US2] Implement `tube-scout analyze retention` subcommand in `src/tube_scout/cli/analyze.py` — run hotspot/skip detection, save results
- [ ] T034 [US2] Implement retention chart in `src/tube_scout/visualization/charts.py` — plotly line chart with colored regions (green=normal, red=hotspot, gray=skip), save as HTML

**Checkpoint**: Retention analysis works — hotspots/skips identified and visualized

---

## Phase 5: User Story 3 — 댓글 하이브리드 분석 (Priority: P2)

**Goal**: 영상 댓글을 수집하고 감성/토픽/질문을 LLM으로 자동 분류, Rewatch Hotspot과 교차 분석

**Independent Test**: `tube-scout collect comments` → `tube-scout analyze sentiment` → 댓글별 감성/토픽/질문 분류 결과 표시

### Tests for User Story 3

- [ ] T035 [P] [US3] Write tests for Comment model in `tests/unit/test_models.py` — test sentiment enum, topics list, is_question flag
- [ ] T036 [P] [US3] Write tests for SentimentService in `tests/unit/test_sentiment.py` — mock LLM API response for batch comment analysis, test caching (content hash), test --sentiment-backend switching

### Implementation for User Story 3

- [ ] T037 [P] [US3] Implement Comment model in `src/tube_scout/models/comment.py` — comment_id, video_id, author, text, published_at, sentiment, topics, is_question, analysis_backend, analyzed_at
- [ ] T038 [US3] Implement comment collection in `src/tube_scout/services/youtube_data.py` — get_comments() via commentThreads.list with pagination, save to data/raw/comments/{video_id}.json
- [ ] T039 [US3] Implement `tube-scout collect comments` subcommand in `src/tube_scout/cli/collect.py` — iterate filtered videos, collect comments, checkpoint per video
- [ ] T040 [US3] Implement SentimentService in `src/tube_scout/services/sentiment.py` — LLM backend (batch 10~20 comments per prompt, structured output: sentiment + topics + is_question), response caching by content hash, --sentiment-backend option (llm/local/skip)
- [ ] T041 [US3] Implement `tube-scout analyze sentiment` subcommand in `src/tube_scout/cli/analyze.py` — call SentimentService, save to data/processed/sentiment/{video_id}.parquet
- [ ] T042 [US3] Implement cross-analysis: questions vs Rewatch Hotspot mapping in `src/tube_scout/services/sentiment.py` — cross_reference_questions_hotspots() linking question topics to retention time ranges

**Checkpoint**: Comment analysis works — sentiment/topic/questions extracted, cross-referenced with hotspots

---

## Phase 6: User Story 4 — LLM 자막 분석 및 난이도 예측 (Priority: P2)

**Goal**: 자막을 수집하여 LLM으로 챕터 분할, 요약, 난이도 예측 수행

**Independent Test**: `tube-scout collect transcripts` → `tube-scout analyze transcript --video-id X` → 챕터별 제목/요약/난이도 점수 표시

### Tests for User Story 4

- [ ] T043 [P] [US4] Write tests for TranscriptSegment model in `tests/unit/test_models.py` — test time range validation, difficulty_score range
- [ ] T044 [P] [US4] Write tests for TranscriptService in `tests/unit/test_transcript.py` — mock youtube-transcript-api responses (manual, auto-generated, not found), test language fallback
- [ ] T045 [P] [US4] Write tests for SegmenterService in `tests/unit/test_segmenter.py` — mock LLM response, test chapter splitting output structure, test difficulty scoring

### Implementation for User Story 4

- [ ] T046 [P] [US4] Implement TranscriptSegment model in `src/tube_scout/models/video.py` — video_id, segment_index, start_seconds, end_seconds, title, text, summary, difficulty_score, tags
- [ ] T047 [US4] Implement TranscriptService in `src/tube_scout/services/transcript.py` — fetch_transcript() via youtube-transcript-api (ko manual → ko auto → fallback), record transcript_type ("manual"/"auto_generated") in Video model, handle TranscriptsDisabled/NoTranscriptFound, save to data/raw/transcripts/{video_id}.json
- [ ] T048 [US4] Implement `tube-scout collect transcripts` subcommand in `src/tube_scout/cli/collect.py` — iterate filtered videos, fetch transcripts, checkpoint per video, log skipped videos
- [ ] T049a [US4] Implement optional Whisper STT fallback in `src/tube_scout/services/transcript.py` — when youtube-transcript-api returns no transcript, attempt Whisper STT if installed (`openai-whisper` optional dependency), skip with log if unavailable. Flag auto-generated transcripts with `transcript_type="stt_whisper"` and lower confidence
- [ ] T049 [US4] Implement SegmenterService in `src/tube_scout/services/segmenter.py` — LLM-based chapter splitting (input: full transcript text, output: segments with title/summary/difficulty), tag extraction, save to data/processed/segments/{video_id}.json. Include transcript_type quality warning for auto-generated/STT transcripts
- [ ] T050 [US4] Implement `tube-scout analyze transcript` subcommand in `src/tube_scout/cli/analyze.py` — call SegmenterService, display results as rich table (segment title, time range, difficulty)
- [ ] T051 [US4] Implement difficulty vs retention comparison in `src/tube_scout/services/segmenter.py` — compare_with_retention() showing predicted difficulty vs actual Rewatch Hotspot alignment

**Checkpoint**: Transcript analysis works — chapters split, difficulty predicted, compared with actual retention

---

## Phase 7: User Story 5 — 분석 리포트 생성 (Priority: P2)

**Goal**: 영상별 개별 리포트와 채널 종합 리포트를 HTML로 생성

**Independent Test**: `tube-scout report video --video-id X` → HTML 파일에 성과 요약, 유지율 차트, 난이도 구간, 개선 제안 포함

### Tests for User Story 5

- [ ] T052 [P] [US5] Write tests for Report model in `tests/unit/test_models.py` — test report_type enum, file_path generation
- [ ] T053 [P] [US5] Write tests for VideoReportGenerator in `tests/unit/test_report.py` — mock input data, verify required sections present in output HTML

### Implementation for User Story 5

- [ ] T054 [P] [US5] Implement Report model in `src/tube_scout/models/config.py` — report_id (UUID), report_type, target_id, generated_at, format, file_path
- [ ] T055 [US5] Create Jinja2 HTML templates in `src/tube_scout/reporting/templates/` — video_report.html (metrics summary, retention chart, difficulty segments, comment insights, improvement suggestions), channel_report.html (comparison table, trend charts, overall insights)
- [ ] T056 [US5] Implement VideoReportGenerator in `src/tube_scout/reporting/video_report.py` — load all processed data for a video, generate plotly charts, render Jinja2 template, save to data/reports/video/{video_id}.html
- [ ] T057 [US5] Implement ChannelReportGenerator in `src/tube_scout/reporting/channel_report.py` — aggregate across all videos, generate comparison charts (views, retention, EQS), trend analysis, save to data/reports/channel/{channel_id}.html
- [ ] T058 [US5] Implement `tube-scout report video` and `tube-scout report channel` subcommands in `src/tube_scout/cli/report.py` — call generators, display output file path, --format option (html/notebook), --output-dir option
- [ ] T059 [US5] Implement improvement suggestions engine in `src/tube_scout/reporting/video_report.py` — generate_suggestions() based on retention hotspots, skip zones, comment questions, segment difficulty, optimal length analysis
- [ ] T059a [US5] Implement Jupyter Notebook export in `src/tube_scout/reporting/notebook_export.py` — convert report data to .ipynb using nbformat, include plotly charts as cell outputs, save to data/reports/video/{video_id}.ipynb or data/reports/channel/{channel_id}.ipynb

**Checkpoint**: Reports generated — HTML files with full analysis, charts, and actionable suggestions

---

## Phase 8: User Story 6 — 교육 품질 자동 스코어링 (Priority: P3)

**Goal**: RACED 5축 기반 교육 품질 점수(EQS)를 LLM으로 산출

**Independent Test**: `tube-scout analyze eqs --video-id X` → RACED 5축 점수 + 종합 점수 표시

### Tests for User Story 6

- [ ] T060 [P] [US6] Write tests for QualityScore model in `tests/unit/test_models.py` — test score ranges (0.0~1.0), overall calculation
- [ ] T061 [P] [US6] Write tests for EQSService in `tests/unit/test_eqs.py` — mock LLM response, test 5-axis scoring output

### Implementation for User Story 6

- [ ] T062 [US6] Implement QualityScore model in `src/tube_scout/models/video.py` — relevance, accuracy, clarity, engagement, depth (all 0.0~1.0), overall (weighted average), evaluated_at
- [ ] T063 [US6] Implement EQSService in `src/tube_scout/services/eqs.py` — LLM-based evaluation (input: transcript segments + viewing pattern + comment analysis, output: RACED 5-axis scores with justification), save to data/processed/eqs/{video_id}.json
- [ ] T064 [US6] Implement `tube-scout analyze eqs` subcommand in `src/tube_scout/cli/analyze.py` — call EQSService, display results as rich table (5 axes + overall), comparison mode for multiple videos
- [ ] T065 [US6] Implement EQS comparison chart in `src/tube_scout/visualization/charts.py` — plotly radar chart for single video, grouped bar chart for multi-video comparison

**Checkpoint**: EQS scoring works — 5-axis quality scores generated and visualized

---

## Phase 9: User Story 7 — 시계열 예측 및 이상 탐지 (Priority: P3)

**Goal**: 과거 시청 데이터로 향후 트렌드를 예측하고 이상치를 자동 탐지

**Independent Test**: `tube-scout analyze forecast` → 예측 차트(신뢰 구간 포함) + 이상치 구간 하이라이트 표시

### Tests for User Story 7

- [ ] T066 [P] [US7] Write tests for Forecast model in `tests/unit/test_models.py` — test confidence interval, anomaly flag
- [ ] T067 [P] [US7] Write tests for ForecasterService in `tests/unit/test_forecaster.py` — test with synthetic time series, verify prediction + anomaly detection output

### Implementation for User Story 7

- [ ] T068 [US7] Implement Forecast model in `src/tube_scout/models/video.py` — channel_id, metric_name, date, predicted_value, lower_bound, upper_bound, is_anomaly, anomaly_reason
- [ ] T069 [US7] Implement ForecasterService in `src/tube_scout/services/forecaster.py` — fit ARIMA/Prophet on historical view_count/watch_time, predict() with confidence intervals, detect_anomalies() using residual threshold, suggest_anomaly_reason() matching academic calendar patterns
- [ ] T070 [US7] Implement `tube-scout analyze forecast` subcommand in `src/tube_scout/cli/analyze.py` — call ForecasterService (require 6+ months data), save to data/processed/forecast/, display summary
- [ ] T071 [US7] Implement forecast chart in `src/tube_scout/visualization/charts.py` — plotly line chart with prediction + confidence band + anomaly markers

**Checkpoint**: Forecasting works — trends predicted, anomalies detected and visualized

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Integration, quality improvements, final validation

- [ ] T072 [P] Implement `tube-scout collect all` orchestrator in `src/tube_scout/cli/collect.py` — run videos → comments → transcripts → retention in sequence with shared checkpoint
- [ ] T073 [P] Implement `tube-scout analyze all` orchestrator in `src/tube_scout/cli/analyze.py` — run sentiment → transcript → retention → eqs → forecast in sequence
- [ ] T074 Add EQS scores to video/channel reports in `src/tube_scout/reporting/video_report.py` and `src/tube_scout/reporting/channel_report.py`
- [ ] T075 Add forecast section to channel report in `src/tube_scout/reporting/channel_report.py`
- [ ] T076 [P] Write integration test: full pipeline (init → collect all → analyze all → report) in `tests/integration/test_full_pipeline.py`
- [ ] T077 [P] Validate all environment variable references — no hardcoded paths or secrets in any source file
- [ ] T078 Run quickstart.md validation — execute all commands from quickstart.md against mock/test data

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — MVP, start first
- **US2 (Phase 4)**: Depends on Phase 2 — can parallel with US1 but benefits from US1 data
- **US3 (Phase 5)**: Depends on Phase 2 — benefits from US2 (cross-reference hotspots)
- **US4 (Phase 6)**: Depends on Phase 2 — benefits from US2 (difficulty vs retention comparison)
- **US5 (Phase 7)**: Depends on US1 + US2 — needs data from earlier stories to generate meaningful reports
- **US6 (Phase 8)**: Depends on US4 (transcript) + US2 (retention) + US3 (comments) for full scoring
- **US7 (Phase 9)**: Depends on US1 — needs historical metrics data
- **Polish (Phase 10)**: Depends on all desired user stories

### User Story Dependencies

```
Phase 2 (Foundation)
  ├── US1 (P1: 영상 식별) ──────────┬── US5 (P2: 리포트)
  ├── US2 (P1: 시청 패턴) ──────────┤
  ├── US3 (P2: 댓글 분석) ──────────┼── US6 (P3: EQS)
  ├── US4 (P2: 자막 분석) ──────────┘
  └── US1 ──── US7 (P3: 시계열 예측)
```

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD)
- Models before services
- Services before CLI commands
- Core implementation before cross-story integration

### Parallel Opportunities

- Phase 1: T003, T004, T005 can run in parallel
- Phase 2: T006~T009 (tests) in parallel, then T010~T013 (implementations) in parallel
- US1: T017~T020 (tests) in parallel, then T021+T022 (models) in parallel
- US2: T026~T028 (tests) in parallel
- US3: T035+T036 (tests) in parallel
- US4: T043~T045 (tests) in parallel
- US5~US7: test pairs in parallel within each story

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together (TDD RED phase):
Task: T017 "Test Channel model in tests/unit/test_models.py"
Task: T018 "Test Video model in tests/unit/test_models.py"
Task: T019 "Test YouTubeDataService in tests/unit/test_youtube_data.py"
Task: T020 "Integration test for collect flow in tests/integration/test_collect_flow.py"

# Launch US1 models together:
Task: T021 "Channel model in src/tube_scout/models/channel.py"
Task: T022 "Video model in src/tube_scout/models/video.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (영상 식별 + 기본 메트릭)
4. **STOP and VALIDATE**: `tube-scout init` → `collect videos` → `list` 동작 확인
5. 이 시점에서 교수는 자신의 영상 현황을 파악할 수 있음

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 (영상 식별) → MVP! 기본 영상 목록 + 메트릭
3. US2 (시청 패턴) → 핵심 가치 추가 — Rewatch Hotspot/Skip Zone
4. US3 (댓글 분석) + US4 (자막 분석) → 질적 인사이트 추가 (병렬 가능)
5. US5 (리포트) → 종합 산출물 생성
6. US6 (EQS) + US7 (시계열) → 고급 분석 (병렬 가능)
7. Polish → 통합 테스트, 품질 마무리

### Recommended Single-Developer Order

P1 → P2 → P3 순서로 순차 진행:
US1 → US2 → US3/US4 → US5 → US6/US7 → Polish

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- TDD mandatory: write tests FIRST (RED), then implement (GREEN), then refactor
- All API keys via environment variables (FR-013)
- Checkpoint/Resume on every collect operation (FR-015)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
