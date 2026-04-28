# Tasks: OAuth Migration, Rate Limiting, Pipeline Enhancement & GPU Support

**Input**: Design documents from `/specs/005-oauth-ratelimit-gpu/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/cli-commands.md

**Tests**: Included (TDD mandatory per CLAUDE.md — RED-GREEN-REFACTOR)

**Organization**: Tasks grouped by user story. Each story is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Create new files and model scaffolding needed across multiple stories

- [ ] T001 Create RateLimitProfile pydantic model (base_delay, max_retries, backoff_multiplier, jitter) with TRANSCRIPT_PROFILE and YOUTUBE_API_PROFILE presets in src/tube_scout/models/config.py
- [ ] T002 [P] Create StageResult and PipelineResult pydantic models in src/tube_scout/models/config.py
- [ ] T003 [P] Create empty src/tube_scout/services/rate_limiter.py module with docstring

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared infrastructure that MUST be complete before ANY user story can begin

**CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 RED: Write unit tests for RateLimiter (wait, wait_on_error, exponential backoff, jitter, max retries exceeded) in tests/unit/test_rate_limiter.py
- [ ] T005 GREEN: Implement RateLimiter class with wait() for inter-request delay and wait_on_error(attempt) for exponential backoff, accepting RateLimitProfile and optional on_backoff callback in src/tube_scout/services/rate_limiter.py
- [ ] T006 REFACTOR: Verify RateLimiter tests pass, refactor if needed in src/tube_scout/services/rate_limiter.py
- [ ] T007 [P] RED: Write unit tests for get_device() — returns "cpu" when unset, "cuda" when TUBE_SCOUT_DEVICE=cuda, "cpu" when TUBE_SCOUT_DEVICE=cpu, raises ValueError for invalid values in tests/unit/test_device_config.py
- [ ] T008 [P] GREEN: Implement get_device() -> str function reading TUBE_SCOUT_DEVICE env var with cpu default and cpu/cuda validation in src/tube_scout/models/config.py
- [ ] T009 Add stage_completed: bool = False field to existing CollectionState model in src/tube_scout/models/config.py

**Checkpoint**: Foundation ready — rate limiter, device config, and pipeline models available for all stories

---

## Phase 3: User Story 1 — OAuth-Only Authentication (Priority: P1) MVP

**Goal**: Remove all API key authentication paths. System authenticates exclusively via OAuth 2.0 using TUBE_SCOUT_CLIENT_SECRET env var.

**Independent Test**: Run any collect command — it must use OAuth (no API key prompt/fallback). grep -r "YOUTUBE_API_KEY" src/ returns 0 results.

### Tests for User Story 1

- [ ] T010 [P] [US1] RED: Write tests for YouTubeDataService requiring client param only (no api_key), raising TypeError when api_key passed, in tests/unit/test_youtube_data.py — update existing tests that use api_key
- [ ] T011 [P] [US1] RED: Write tests for auth.py requiring TUBE_SCOUT_CLIENT_SECRET env var (no file-glob fallback), raising ValueError when env var missing, in tests/unit/test_auth.py

### Implementation for User Story 1

- [ ] T012 [US1] GREEN: Remove api_key parameter and YOUTUBE_API_KEY env var lookup from YouTubeDataService.__init__(), require client: Any as mandatory param in src/tube_scout/services/youtube_data.py
- [ ] T013 [US1] GREEN: Remove _default_client_secret_path() file-glob fallback from auth.py, make TUBE_SCOUT_CLIENT_SECRET env var the sole credential source in src/tube_scout/services/auth.py
- [ ] T014 [US1] Update all YouTubeDataService instantiation sites in CLI to use auth.build_data_client() — update collect_videos_command, collect_comments_command, and other collect_* commands in src/tube_scout/cli/collect.py
- [ ] T015 [US1] Update any remaining test fixtures/mocks that reference YOUTUBE_API_KEY or developerKey across tests/unit/ directory
- [ ] T016 [US1] VERIFY: Search entire src/ for YOUTUBE_API_KEY, api_key (YouTube context), developerKey — confirm zero references remain

**Checkpoint**: OAuth-only authentication working. All collect commands use OAuth. Zero API key references in codebase.

---

## Phase 4: User Story 2 — Rate-Limited Transcript Collection (Priority: P1)

**Goal**: Transcript collection for 200+ videos completes without IP blocking, using per-service rate limiting with configurable delays.

**Independent Test**: Run transcript collection on a channel with 50+ videos — all transcripts collected, no HTTP 429 or IP block errors, progress shows delay info.

### Tests for User Story 2

- [ ] T017 [P] [US2] RED: Write tests for TranscriptService with rate limiter integration — verify wait() called between requests, backoff on error, configurable profile in tests/unit/test_transcript.py
- [ ] T018 [P] [US2] RED: Write tests for YouTubeAnalyticsService using shared RateLimiter instead of inline retry logic in tests/unit/test_youtube_analytics.py

### Implementation for User Story 2

- [ ] T019 [US2] GREEN: Integrate RateLimiter with TRANSCRIPT_PROFILE into TranscriptService — add rate_limiter param to __init__, call wait() before each YouTubeTranscriptApi request in src/tube_scout/services/transcript.py
- [ ] T020 [US2] GREEN: Replace inline retry logic (_MAX_RETRIES, _RETRY_BASE_DELAY) in YouTubeAnalyticsService with shared RateLimiter using YOUTUBE_API_PROFILE in src/tube_scout/services/youtube_analytics.py
- [ ] T021 [US2] Wire RateLimiter on_backoff callback to Rich progress display — show backoff events inline in progress bar in src/tube_scout/cli/collect.py
- [ ] T022 [US2] Add rate_limit_transcript and rate_limit_youtube_api fields (RateLimitProfile) to Settings model, load from config in src/tube_scout/models/config.py

**Checkpoint**: Rate-limited transcript and API collection working. Configurable delays. Progress shows backoff events.

---

## Phase 5: User Story 3 — Single-Command Multi-Step Collection (Priority: P2)

**Goal**: `collect all --channel <alias>` executes 5-stage pipeline with proper error handling and stage-level resume.

**Independent Test**: Run `collect all --channel <alias>` — all 5 stages complete. Interrupt mid-run, re-run — skips completed stages.

### Tests for User Story 3

- [ ] T023 [P] [US3] RED: Write tests for collect_all_command with --channel param — verifies authenticate_channel called, all 5 stages invoked with channel context in tests/unit/test_collect_all.py
- [ ] T024 [P] [US3] RED: Write tests for pipeline error handling — video listing failure aborts, other stage failures continue with summary in tests/unit/test_collect_all.py
- [ ] T025 [P] [US3] RED: Write tests for stage-level resume — is_stage_complete() and mark_stage_complete() in checkpoint, skip completed stages on re-run in tests/integration/test_pipeline_resume.py

### Implementation for User Story 3

- [ ] T026 [US3] GREEN: Add --channel optional param to collect_all_command, call authenticate_channel(alias) when provided, pass client to all stages in src/tube_scout/cli/collect.py
- [ ] T027 [US3] GREEN: Replace bare except SystemExit: pass with per-stage error tracking — StageResult for each stage, abort pipeline on video listing failure, continue on others in src/tube_scout/cli/collect.py
- [ ] T028 [US3] GREEN: Add is_stage_complete(channel_id, stage_name) and mark_stage_complete(channel_id, stage_name) methods to checkpoint manager in src/tube_scout/storage/checkpoint.py
- [ ] T029 [US3] GREEN: Add stage completion check before each stage in collect_all — skip if complete unless --force-refresh, print resume info in src/tube_scout/cli/collect.py
- [ ] T030 [US3] Print pipeline summary at end — list each stage with status (completed/failed/skipped), total items, duration in src/tube_scout/cli/collect.py

**Checkpoint**: `collect all --channel` working with error handling and resume. Backward compatible without --channel.

---

## Phase 6: User Story 4 — Cross-Machine OAuth Secret Sync (Priority: P2)

**Goal**: After `nixos-rebuild switch`, OAuth client secret is available via env var and tube-scout can start OAuth flow without manual file copying.

**Independent Test**: Set TUBE_SCOUT_CLIENT_SECRET to a valid path, run tube-scout — OAuth flow initiates. Runtime tokens stored in ~/.config/tube-scout/tokens/ only.

### Tests for User Story 4

- [ ] T031 [US4] RED: Write tests verifying auth.py reads client secret exclusively from TUBE_SCOUT_CLIENT_SECRET env var path (JSON file), not from any hardcoded or glob path, in tests/unit/test_auth.py

### Implementation for User Story 4

- [ ] T032 [US4] GREEN: Ensure _find_client_secret() in auth.py reads the JSON file at the path specified by TUBE_SCOUT_CLIENT_SECRET env var, raises clear error if env var unset or file missing in src/tube_scout/services/auth.py
- [ ] T033 [US4] Verify runtime tokens in ~/.config/tube-scout/tokens/ are NOT referenced in any agenix or deployment config — document the separation in specs/005-oauth-ratelimit-gpu/quickstart.md

**Checkpoint**: OAuth client secret fully env-var driven. Clear separation between agenix-managed secret and machine-local tokens.

---

## Phase 7: User Story 5 — GPU-Accelerated ML Processing (Priority: P3)

**Goal**: ML tasks use GPU when TUBE_SCOUT_DEVICE=cuda, fall back to CPU when unset or cpu.

**Independent Test**: Set TUBE_SCOUT_DEVICE=cuda (on GPU machine), run sentiment analysis — model loads on GPU. Unset var, run again — model loads on CPU.

### Tests for User Story 5

- [ ] T034 [P] [US5] RED: Write tests for sentiment service with device param — verify transformers.pipeline receives device="cpu" by default, device="cuda" when configured, in tests/unit/test_sentiment.py

### Implementation for User Story 5

- [ ] T035 [US5] GREEN: Pass device=get_device() to transformers.pipeline() call in local sentiment backend, ensure model loads on specified device in src/tube_scout/services/sentiment.py
- [ ] T036 [US5] REFACTOR: Verify all current ML service entry points (sentiment local backend) call get_device() — add comment marking future ML services (Whisper STT, v4 embeddings) as GPU-ready integration points in src/tube_scout/services/sentiment.py

**Checkpoint**: GPU device configuration working. All ML services use shared get_device(). CPU fallback verified.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Edge case testing, documentation, final validation

- [ ] T037 [P] Write rate limiting edge case adversary tests (concurrent instances, mid-collection token expiry, backoff ceiling) in tests/adversary/test_rate_limit_edge.py
- [ ] T038 [P] Write pipeline edge case adversary tests (interrupt and resume, partial stage completion, --force-refresh override) in tests/adversary/test_pipeline_edge.py
- [ ] T039 Run full test suite — verify all existing 201+ tests still pass plus new tests
- [ ] T040 Validate quickstart.md end-to-end flow against actual implementation in specs/005-oauth-ratelimit-gpu/quickstart.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — MVP, must be first
- **US2 (Phase 4)**: Depends on Phase 2 + RateLimiter from Phase 2
- **US3 (Phase 5)**: Depends on Phase 2; benefits from US1 (OAuth for --channel) and US2 (rate limiting in pipeline)
- **US4 (Phase 6)**: Depends on US1 (OAuth-only migration)
- **US5 (Phase 7)**: Depends on Phase 2 (get_device); independent of other stories
- **Polish (Phase 8)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Phase 1 (Setup) → Phase 2 (Foundational)
                      ├── US1 (OAuth-Only) ──→ US4 (Agenix Sync)
                      ├── US2 (Rate Limiting) ─┐
                      │                         ├── US3 (Pipeline --channel)
                      │   US1 ──────────────────┘
                      └── US5 (GPU) [independent]
```

### Within Each User Story

1. RED: Tests written and FAILING
2. GREEN: Minimal implementation to pass tests
3. REFACTOR: Clean up, verify all tests pass
4. Checkpoint: Story independently testable

### Parallel Opportunities

- **Phase 1**: T001, T002, T003 can all run in parallel
- **Phase 2**: T004-T006 (rate limiter) parallel with T007-T008 (device config); T009 parallel with both
- **Phase 3 tests**: T010 parallel with T011
- **Phase 4 tests**: T017 parallel with T018
- **Phase 5 tests**: T023, T024, T025 all parallel
- **US5**: Entirely parallel with US2/US3 (no shared file dependencies)

---

## Parallel Example: User Story 1

```bash
# Launch tests in parallel (different files):
Task: "T010 — YouTubeDataService OAuth-only tests in tests/unit/test_youtube_data.py"
Task: "T011 — auth.py TUBE_SCOUT_CLIENT_SECRET tests in tests/unit/test_auth.py"

# Then implementation in parallel (different files):
Task: "T012 — Remove api_key from YouTubeDataService in src/tube_scout/services/youtube_data.py"
Task: "T013 — Remove file-glob fallback from auth.py in src/tube_scout/services/auth.py"
```

## Parallel Example: User Story 3

```bash
# Launch all tests in parallel (different files):
Task: "T023 — collect all --channel tests in tests/unit/test_collect_all.py"
Task: "T024 — Pipeline error handling tests in tests/unit/test_collect_all.py"  # same file, run sequentially
Task: "T025 — Stage-level resume tests in tests/integration/test_pipeline_resume.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (OAuth-Only)
4. **STOP and VALIDATE**: grep for API key references, run OAuth flow
5. Deploy if ready — system now uses OAuth exclusively

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 (OAuth-Only) → **MVP!** API keys removed, OAuth works
3. US2 (Rate Limiting) → Transcript collection reliable at scale
4. US3 (Pipeline --channel) → Single command for full collection
5. US4 (Agenix Sync) → Multi-machine deployment ready
6. US5 (GPU) → ML performance optimization
7. Polish → Edge cases, adversary tests, docs

### Recommended Agent Team Strategy

With code-team (developer + pair-programmer + auditor + adversary):

1. developer: Implement Phase 1 + 2 (foundational)
2. developer: US1 → US2 → US3 → US4 → US5 (sequential, priority order)
3. pair-programmer: Validate FR traceability after each story checkpoint
4. auditor: Full audit after all stories complete
5. adversary: Phase 8 edge case testing

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for FR traceability
- TDD mandatory: RED (test fails) → GREEN (minimal impl) → REFACTOR
- Commit after each task or logical TDD cycle
- Stop at any checkpoint to validate story independently
- US3 (Pipeline) has the most cross-cutting changes to collect.py — consider as integration point after US1+US2
