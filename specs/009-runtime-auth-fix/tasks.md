---
description: "Task list for spec 009 — Runtime Integration & Multi-Channel Auth Fix"
---

# Tasks: Runtime Integration & Multi-Channel Auth Fix

**Input**: Design documents from `/specs/009-runtime-auth-fix/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: MANDATORY for every implementation task (Constitution v1.1.0 Principle I: Test-First Development is NON-NEGOTIABLE). RED test MUST be written and confirmed failing before any GREEN implementation task in the same logical unit.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1, US2, US3, US4 — maps to spec.md user stories
- File paths are absolute project-relative

## Path Conventions

Single project layout (per plan.md):

- Source: `src/tube_scout/`
- Tests: `tests/{contract,integration,unit,manual}/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project-level scaffolding for spec 009.

- [x] T001 Verify branch state and pyproject.toml; add `httpx` as a direct dependency in `pyproject.toml` (currently transitive via google-api-python-client). Run `uv lock` to refresh lock file.
- [x] T002 Add `tmp_projects_root` pytest fixture to `tests/conftest.py` (creates `tmp_path / "projects"` and yields it; idea-6-aware — also patches any `Path("./projects")` defaults if encountered). NOT [P]: edits the same file as the post-spec-009 conftest baseline; sequence with T003.
- [x] T003 [P] Add `httpx_mock` fixture configuration to a NEW dedicated module `tests/fixtures/httpx_mock.py` (re-exported via `tests/conftest.py`'s plugin chain), plus pin `pytest-httpx` in `pyproject.toml` if not yet present. Lives in a separate file from T002 to enable safe parallel execution.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: New error classes and the channel-alias resolver that every subsequent user story consumes. Per Principle I, RED tests precede GREEN.

**⚠️ CRITICAL**: No US1/US2/US3/US4 task may begin until this phase is complete.

- [x] T004 [P] RED unit tests for new `UserFacingError` subclasses (`LegacyTokenChannelMismatch`, `LegacyTokenCorrupt`, `MultipleAliasesNoSelection`, `NoAliasRegistered`, `DeviceCodeTimeout`, `DeviceCodeAccessDenied`, `LatestProjectMissing`, `ProducerCommandRequiresChannel`) in `tests/unit/test_errors_new.py`. Each test asserts `message`, `next_command`, and that no secret leaks (Principle II).
- [x] T005 [P] RED unit tests for `resolve_channel_alias(explicit, registry) -> str` covering: explicit-valid, explicit-invalid (raises), zero-alias (raises NoAliasRegistered), one-alias (auto-select + dim notice), multi-alias (raises MultipleAliasesNoSelection with corrected commands). Path: `tests/unit/test_resolve_channel_alias.py`.
- [x] T006 GREEN implementation of new error classes in `src/tube_scout/cli/errors.py` to make T004 pass. Each subclass MUST follow idea6 ADR-007 pattern (cause + `next_command`).
- [x] T007 GREEN implementation of `resolve_channel_alias` helper in `src/tube_scout/services/auth.py` to make T005 pass. Depends on T006 (uses `NoAliasRegistered`, `MultipleAliasesNoSelection`).

- [x] T007a Add the "Cross-Spec Boundaries" section to `specs/009-runtime-auth-fix/spec.md` (per Constitution Principle VII — moved from Phase 7 polish). Mirror the 13-row enumeration in plan.md's Constitution Check, framed at stakeholder readability. Verify no boundary in plan.md is absent from spec.md and vice versa. (Prior placement at T046 made Principle VII a polish-time gate, which contradicts NN status; this task closes that gap before any user-story implementation begins.)

**Checkpoint**: New errors, channel resolver, and Principle VII compliance ready. User-story phases can begin.

---

## Phase 3: User Story 1 — Multi-channel-aware data collection that does not get blocked at auth (Priority: P1) 🎯 MVP

**Goal**: Operator can run any auth-using `collect` command and have it route through `tokens/<alias>.json` (no legacy `token.json` fallback), with OAuth flow that does not hang in multi-account browser environments. Legacy token migration runs once on first invocation.

**Independent Test**: On a machine with `tokens/nursing.json` covering force-ssl + yt-analytics scopes and a stale `~/.config/tube-scout/token.json` from a prior single-channel install, running `tube-scout collect retention --channel nursing --project latest` MUST succeed using the alias token, ignore the legacy file, and never bind a TCP listener for OAuth.

### Tests for User Story 1 (RED — write first, confirm failing)

- [x] T008 [P] [US1] RED contract tests for OAuth 2.0 device authorization grant against Google endpoints in `tests/contract/test_auth_device_flow.py`. Cover: success path, `authorization_pending` → success, `slow_down` → backoff → success, `expired_token` → `DeviceCodeTimeout`, `access_denied` → `DeviceCodeAccessDenied`, network error → `UserFacingError`. Use `httpx_mock` fixtures.
- [x] T009 [P] [US1] RED unit test in `tests/unit/test_auth_flow_selection.py`: (a) `--browser-redirect` in non-TTY context falls back to device flow (per FR-012); (b) device flow without TTY raises `InteractiveAuthRequired` only if stdout is also unavailable; (c) **`--browser-redirect` with a stalled callback raises a timeout error after 5 minutes and closes the listener socket (per FR-013-bis)** — use a fake clock or `monkeypatch.setattr(time, "monotonic", ...)` to avoid wall-clock waits in the test.
- [x] T010 [P] [US1] RED contract tests for `auth_migration.run_once()` in `tests/contract/test_auth_migration.py`: corrupt JSON → unlink + warning, `recover_channel_id` returns None → unlink, race-protection via `fcntl.flock`. Mock `youtube.channels.list(mine=True)` calls.
- [x] T011 [P] [US1] RED integration tests for legacy token migration end-to-end in `tests/integration/test_legacy_token_migration.py`: every scenario from contracts/token_migration.md ("Test contract" table — match-newer, match-older, no-match, corrupt, missing, both-paths-present).
- [x] T012 [P] [US1] RED unit tests for `build_analytics_client(alias)` and `build_reporting_client(alias)` accepting alias parameter and routing through `authenticate_channel(alias)` in `tests/unit/test_auth_routing.py`. Assert `~/.config/tube-scout/token.json` is NEVER read.
- [x] T013 [P] [US1] RED integration test asserting `collect retention --channel nursing --project latest` reads `tokens/nursing.json` and never opens port 8080. Path: `tests/integration/test_collect_retention_routing.py`.

### Implementation for User Story 1

- [x] T014 [P] [US1] GREEN: Implement RFC 8628 device flow in new module `src/tube_scout/services/auth_device_flow.py`. Public function `run_device_flow(client_id, client_secret, scopes) -> Credentials`. Use `httpx` for endpoint calls. Handle all polling states (R1).
- [x] T015 [P] [US1] GREEN: Implement `recover_channel_id(creds, cache_path) -> str | None` and `run_once(config_dir, registry)` in new module `src/tube_scout/services/auth_migration.py`. Atomic `os.rename`, `fcntl.flock`, idempotent (R2).
- [x] T016 [US1] GREEN: Wire `auth_migration.run_once()` into `services/auth.py:authenticate_channel()` as a one-shot preflight (module-level guard). Depends on T014, T015.
- [x] T017 [US1] GREEN: Refactor `services/auth.py:build_analytics_client()` and `build_reporting_client()` to accept `alias: str` and route through `authenticate_channel(alias)`. Mark old `authenticate()` as private/deprecated. Depends on T016.
- [x] T018 [US1] GREEN: Update `cli/auth_cli.py` to use device flow as default (FR-011). Add `--browser-redirect` opt-in flag (FR-012). Headless fallback: `--browser-redirect` + non-TTY → device flow. **In addition (FR-013-bis)**: when `--browser-redirect` is selected, configure `flow.run_local_server` with a 5-minute upper-bound timeout; on timeout, raise `DeviceCodeTimeout` (or a sibling `BrowserRedirectTimeout` class — add to T004/T006 if needed) and ensure the listener socket is closed. Depends on T014.
- [x] T019 [US1] GREEN: Update `cli/collect.py:collect_retention_command` and `collect_analytics_command` to call `build_analytics_client(alias)` / `build_reporting_client(alias)` with the resolved alias from preflight. Remove any direct `authenticate()` call. Depends on T017, T007.

**Checkpoint**: User Story 1 complete — auth no longer blocks. End-to-end:
`auth --channel nursing` (device flow) → `collect retention --channel nursing --project latest` succeeds and writes retention data. Legacy `token.json` was migrated or deleted on first invocation.

---

## Phase 4: User Story 2 — Sequential collection without manual project plumbing (Priority: P1)

**Goal**: Running consumer commands (`collect transcripts`, `collect retention`, `analyze *`, `content *`, `report *`) without `--project` automatically operates on the latest project. The producer (`collect videos`) atomically advances `latest` on success, never on partial failure. No empty sibling projects are created.

**Independent Test**: From a clean `projects/` directory, run `collect videos --channel <alias>` followed immediately by `collect transcripts --channel <alias>` (no `--project` on either). The transcripts step must find the videos and proceed. Final filesystem state: exactly one new project directory; `projects/latest` resolves to it.

### Tests for User Story 2 (RED)

- [x] T020 [P] [US2] RED unit test in `tests/unit/test_resolve_project_unit.py`: `resolve_project(project_dir, project=None, producer=False)` opens existing latest; raises `LatestProjectMissing` if none. `producer=True` creates new project.
- [x] T021 [P] [US2] RED contract test in `tests/contract/test_resolve_project.py`: explicit `--project latest` and `--project <path>` semantics unchanged (FR-004 backward compat). New behavior covered for `project=None` per producer/consumer split.
- [x] T022 [P] [US2] RED unit test in `tests/unit/test_producer_constant.py`: `PRODUCER_COMMANDS = frozenset({"collect.videos"})` is the single source of truth; `is_producer(command_id)` returns expected booleans.
- [x] T023 [P] [US2] RED integration test in `tests/integration/test_collect_videos_commit.py`: `collect videos` success path advances `projects/latest` atomically (`commit_latest()` invoked once on completion); partial failure (mid-run exception) does NOT advance `latest`.
- [x] T024 [P] [US2] RED integration test in `tests/integration/test_collect_chain.py`: full sequence `collect videos --channel <alias>` → `collect transcripts --channel <alias>` (no `--project` flags) operates on the same project; no empty sibling projects exist after.

### Implementation for User Story 2

- [x] T025 [US2] GREEN: Add `PRODUCER_COMMANDS = frozenset({"collect.videos"})` constant and `is_producer(command_id) -> bool` helper to `src/tube_scout/cli/project.py`. Depends on T022.
- [x] T026 [US2] GREEN: Update `resolve_project(project_dir, project, producer=False)` signature in `src/tube_scout/cli/project.py`. New default: when `project is None`, open existing latest unless `producer=True`. Depends on T020, T025.
- [x] T027 [US2] GREEN: Wire `mgr.commit_latest()` into the success path of `collect_videos_command` in `src/tube_scout/cli/collect.py` (after data write completes). On exception, do NOT call `commit_latest`. Depends on T023, T026.
- [x] T028 [US2] GREEN: Audit every CLI command in `cli/collect.py`, `cli/analyze.py`, `cli/content.py`, `cli/report.py`, `cli/search_cli.py`, `cli/validate_cli.py`, `cli/status.py`, `cli/admin.py` and pass `producer=is_producer("<command_id>")` to `resolve_project()`. Producer set today: only `collect.videos`. Depends on T026.

**Checkpoint**: User Story 2 complete — chained collect commands work without `--project` flags. `projects/latest` is always coherent.

---

## Phase 5: User Story 3 — Symmetric `--channel` API (Priority: P2)

**Goal**: Every `collect <subcommand>` accepts `--channel <alias>`. Multi-alias environments require explicit selection; single-alias environments auto-select with a notice; zero-alias environments refuse with guidance.

**Independent Test**: With two aliases registered, run `collect retention --channel <alias-2>`; the command accepts the flag, routes auth through `tokens/<alias-2>.json`, and never falls back to `<alias-1>` or default token. Running the same command without `--channel` refuses with a message listing both aliases.

### Tests for User Story 3 (RED)

- [x] T029 [P] [US3] RED contract test in `tests/contract/test_collect_channel_symmetry.py`: `--channel` flag exists on `collect retention`, `collect analytics`, `collect bulk` (and continues to exist on videos/transcripts/comments). `--help` text mentions it. Invalid `--channel <bad-alias>` raises `UserFacingError` with `next_command`.
- [x] T030 [P] [US3] RED integration test in `tests/integration/test_resolve_channel_multi_alias.py`: with 2 aliases registered, `collect retention` (no `--channel`) raises `MultipleAliasesNoSelection` listing both aliases with last-used dates and a corrected command. With 1 alias, auto-select with dim notice. With 0 aliases, raises `NoAliasRegistered`.

### Implementation for User Story 3

- [x] T031 [US3] GREEN: Add `--channel` Typer option to `collect_retention_command`, `collect_analytics_command`, `collect_bulk_command` in `src/tube_scout/cli/collect.py`. Match the existing `--channel` option semantics on videos/transcripts. Depends on T029, T019.
- [x] T032 [US3] GREEN: Centralize alias resolution by calling `resolve_channel_alias(--channel)` at the top of EVERY collect subcommand's preflight, **including the already-symmetric `collect_videos_command`, `collect_transcripts_command`, and `collect_comments_command`** (in addition to the newly-added retention/analytics/bulk). Replace every ad-hoc `if channel: ... else:` branch in `cli/collect.py`. The single, centralized call site is the FR-006 invariant. Depends on T031, T030, T007.
- [x] T033 [US3] GREEN: Update `collect_all_command` (the composite) to pass the resolved alias through to every step; reject `--project` in the composite (per contracts/cli_collect.md). Depends on T032.

**Checkpoint**: User Story 3 complete — CLI surface is symmetric. Multi-alias environments are unambiguous.

---

## Phase 6: User Story 4 — Diagnostic transcript collection (Priority: P3)

**Goal**: Every transcript JSON carries a `source` field. The verbose 1st-step exception is suppressed when fallback succeeds (one dim line instead). A per-channel `transcripts_audit.csv` lists every missed video with classification + hint.

**Independent Test**: Run `collect transcripts --channel nursing`. Inspect any produced JSON: `source` field equals `manual` | `auto_generated` | `captions_api`. Inspect terminal output for a private video where fallback succeeded: at most one dim line for the primary failure. Inspect `transcripts_audit.csv`: every miss has a non-empty `classification` and `hint`.

### Tests for User Story 4 (RED)

- [x] T034 [P] [US4] RED unit test in `tests/unit/test_transcript_source_field.py`: `TranscriptService.fetch_transcript()` (and persistence) sets `source` correctly for each of the three retrieval paths.
- [x] T035 [P] [US4] RED snapshot test in `tests/unit/test_transcript_output_format.py`: for a synthetic 3-video fixture (1 manual, 1 private+fallback-success, 1 both-fail), the captured stdout matches a fixture file. Fallback-success case shows ≤1 dim line for primary failure; both-fail case shows full traceback.
- [x] T036 [P] [US4] RED unit test in `tests/unit/test_transcripts_audit_classify.py`: every classification rule from research.md R5 is exercised with a synthetic `(primary_error, fallback_error, video_meta)` triple. Asserts the chosen classification + hint.
- [x] T037 [P] [US4] RED integration test in `tests/integration/test_transcript_audit.py`: `collect transcripts` produces `01_collect/transcripts_audit.csv` at the project root with one row per missed video. Header matches data-model.md E5.

### Implementation for User Story 4

- [x] T038 [P] [US4] GREEN: Add `source: str` field to transcript JSON write path in `src/tube_scout/services/transcript.py`. Backward-compatible: existing JSON without `source` still parses (consumers treat absent as `unknown`). Depends on T034.
- [x] T039 [P] [US4] GREEN: Implement classification table in new module `src/tube_scout/services/transcripts_audit.py`. Public function `classify_miss(primary_error, fallback_error, video_meta) -> tuple[classification, hint]`. Public function `write_audit_csv(rows, path)`. Depends on T036.
- [x] T040 [US4] GREEN: In `cli/collect.py:collect_transcripts_command`, suppress the verbose youtube-transcript-api exception printout. Capture `(primary_class, primary_first_line)`. On fallback success, emit one dim line. On both-fail, print full traceback as today. Depends on T035, T038.
- [x] T041 [US4] GREEN: Wire `transcripts_audit.write_audit_csv()` into `collect_transcripts_command` end-of-run. Build rows from in-memory miss collection. Output path: `<project>/01_collect/transcripts_audit.csv`. Depends on T039, T037.

**Checkpoint**: User Story 4 complete — transcript collection is diagnosable.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verify quickstart, lint, docs, manual OAuth, Principle VII spec amendment.

- [x] T042 [P] Add manual OAuth E2E test in `tests/manual/test_real_oauth_device_flow.py` (excluded from default suite by idea6 D-9). Walks an operator through `auth --channel <test-alias>` against real Google with a fixture client_secret. **Record wall-clock duration of the device-code flow** in the test artifact and assert it is ≤120 seconds (SC-002).
- [x] T043 [P] Run silent-skip lint guard against all changed files; assert zero new SystemExit absorption sites (idea6 FR-IDEA6-010 / Constitution Principle II).
- [x] T044 [P] Run `ruff check` and `ruff format` on every changed file. **Additionally run `mypy --strict` on every changed module under `src/tube_scout/cli/` and `src/tube_scout/services/`** (Constitution Principle III: every parameter and return value carries a type annotation). Fix any new violations.
- [x] T045 [P] Update CLAUDE.md (project) to mention spec 009 changes: device flow default, legacy token auto-migration, project resolution default. Append-only in the "Recent Changes" section maintained by `update-agent-context.sh`.
- [ ] T046 (REMOVED — promoted to T007a in Phase 2 to honor Principle VII at gate time. This slot is intentionally retained as a documentation marker to preserve task-ID stability for any external trackers.)
- [ ] T047 Run `quickstart.md` end-to-end on the operator's machine against the real `nursing` channel. Validate every Validation step. Record the outcome in `quickstart.md`'s "What you just verified" table or as a checklist.
- [x] T048 Final integration: run the full default test suite (`pytest`). Assert green: 1530+ passed, 0 failed, only `tests/manual/` skipped. **Verified 2026-05-08**: 1956 passed, 7 skipped (5 transcripts_audit pre-emptive placeholders + 1 symlink-not-supported + 1 manual), 3 xfailed, 0 failed; peak RSS 256 MB, wall 88 s.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup, T001–T003)**: No dependencies. T003 is [P]; T002 is sequential against the conftest.py baseline; T001 is sequential (pyproject + uv lock).
- **Phase 2 (Foundational, T004–T007 + T007a)**: Depends on Phase 1. T004 + T005 [P] in parallel. T006 depends on T004; T007 depends on T005 + T006. T007a is a doc edit on `spec.md` and is independent of T004–T007 (can run in parallel). **BLOCKS Phases 3–6**.
- **Phase 3 (US1, T008–T019)**: Depends on Phase 2 complete.
- **Phase 4 (US2, T020–T028)**: Depends on Phase 2 complete. **Independent of US1**: can run in parallel by a different developer.
- **Phase 5 (US3, T029–T033)**: Depends on Phase 2 + Phase 3 complete (consumes T019's refactored auth API). Cannot start before Phase 3 lands.
- **Phase 6 (US4, T034–T041)**: Depends on Phase 2 complete. **Independent of US1/US2/US3**: can run in parallel.
- **Phase 7 (Polish, T042–T048)**: Depends on Phases 3–6 complete.

### Within Each User Story

Per Constitution Principle I (NON-NEGOTIABLE): every implementation task has a corresponding RED test task ahead of it. Implementation MUST NOT begin until the RED test is confirmed failing.

- US1 RED batch: T008–T013 (6 tests, all [P]) → US1 GREEN: T014, T015 [P], then T016 → T017 → T018 → T019.
- US2 RED batch: T020–T024 (5 tests, all [P]) → US2 GREEN: T025 → T026 → T027 → T028.
- US3 RED batch: T029, T030 (2 tests, all [P]) → US3 GREEN: T031 → T032 → T033.
- US4 RED batch: T034–T037 (4 tests, all [P]) → US4 GREEN: T038, T039 [P] → T040 → T041.

### Parallel Opportunities

- Phase 1: T003 alone is [P] (T002 sequential, see above; conflict avoided by splitting fixtures into separate files).
- Phase 2: T004 + T005 + T007a in parallel (different files: errors test, resolver test, spec.md edit).
- Phase 3: T008–T013 all in parallel (different test files). T014 + T015 in parallel (different new modules).
- Phase 4: T020–T024 all in parallel.
- Phase 5: T029 + T030 in parallel.
- Phase 6: T034–T037 in parallel. T038 + T039 in parallel.
- Phase 7: T042–T045 in parallel.

### Cross-Story Parallelism

After Phase 2 closes:

- Developer A: US1 (Phase 3) — auth refactor track
- Developer B: US2 (Phase 4) — project resolution track
- Developer C: US4 (Phase 6) — transcript polish track
- Developer D: US3 (Phase 5) — must wait for Phase 3 to complete (consumes refactored auth API)

---

## Parallel Example: Phase 3 (User Story 1)

```bash
# Launch all US1 RED tests together (independent files):
Task: "T008 [US1] RED contract tests in tests/contract/test_auth_device_flow.py"
Task: "T009 [US1] RED unit test in tests/unit/test_auth_flow_selection.py"
Task: "T010 [US1] RED contract tests in tests/contract/test_auth_migration.py"
Task: "T011 [US1] RED integration tests in tests/integration/test_legacy_token_migration.py"
Task: "T012 [US1] RED unit tests in tests/unit/test_auth_routing.py"
Task: "T013 [US1] RED integration test in tests/integration/test_collect_retention_routing.py"

# After RED batch is green-failing, launch independent GREEN modules:
Task: "T014 [US1] Device flow in src/tube_scout/services/auth_device_flow.py"
Task: "T015 [US1] Migration in src/tube_scout/services/auth_migration.py"
```

---

## Implementation Strategy

### MVP Scope = User Story 1 only

Per spec.md, US1 is the only critical-blocker (D-15 + D-17 prevent any retention/analytics today). Shipping just US1 unblocks the operator's end-to-end pipeline.

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. STOP. Validate: `tube-scout collect retention --channel nursing --project latest` succeeds.
3. Demo / deploy MVP.
4. Resume with US2, then US3, then US4.

### Recommended Order (single developer)

US1 (P1) → US2 (P1) → US3 (P2) → US4 (P3) → Polish.

### dev-squad Parallel Strategy

Per memory `feedback_devsquad_full_team`, spawn the full team at the start of Phase 3 (after Phase 2 closes):

- developer-A: US1 (auth track)
- developer-B: US2 (project resolution track)
- developer-C: US4 (transcript polish — independent of others)
- pair-programmer + auditor + adversary + qa-engineer: cross-cutting verification across all stories from day 1
- Hold US3 until US1 lands (consumes T019); developer-A picks it up immediately after US1 closure.

---

## Notes

- Every GREEN task has a RED predecessor in the same story. Verify RED fails before writing any GREEN code (Principle I).
- File paths are absolute project-relative; no ambiguity. Each task is independently completable by an LLM with the design docs.
- Commit after each logical group (RED batch, then GREEN batch). Conventional commits: `test(...)` for RED, `feat(...)` / `refactor(...)` for GREEN.
- ADV findings (per memory `feedback_adv_fix_one_per_commit`): if adversary surfaces a P1, that fix gets its own commit separate from these tasks.
- Stop at any phase checkpoint to validate independently.
