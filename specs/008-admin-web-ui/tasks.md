---
description: "Task list for 008-admin-web-ui — 교무과 담당자용 간편 웹 UI"
---

# Tasks: 교무과 담당자용 간편 웹 UI (Admin Web UI)

**Input**: Design documents from `/specs/008-admin-web-ui/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/http-routes.md](./contracts/http-routes.md), [contracts/admin-cli.md](./contracts/admin-cli.md)

**Tests**: Tests are **MANDATORY** per Constitution I (Test-First, NON-NEGOTIABLE). Every implementation task is preceded by a RED test that MUST be authored, run, and confirmed failing before the corresponding implementation begins.

**Organization**: Tasks are grouped by user story (US1=P1, US2=P2, US3=P3) so each can be implemented, tested, and shipped independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on uncompleted tasks)
- **[Story]**: Maps task to user story (US1/US2/US3) — Setup/Foundational/Polish phases have no story label
- All paths are absolute or rooted at the repo `/home/kjeong/localgit/tube-scout/`

## Path Conventions

- Source: `src/tube_scout/web/...`, new CLI subcommand: `src/tube_scout/cli/admin.py`
- Tests: `tests/contract/`, `tests/integration/`, `tests/unit/`
- Specs: `specs/008-admin-web-ui/...`
- Runtime data: `~/.config/tube-scout/departments.json`, `~/.local/share/tube-scout/admin.db`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency setup.

- [ ] T001 Add new runtime dependencies to `pyproject.toml`: `starlette`, `uvicorn[standard]`, `itsdangerous`, `bcrypt`, `python-multipart`. Update `[project.optional-dependencies].dev`: `pytest-asyncio`, `httpx`. Run `uv lock` to refresh lockfile.
- [ ] T002 [P] Create empty package skeleton at `src/tube_scout/web/__init__.py`, plus subpackages `src/tube_scout/web/{routes,middleware,jobs,repo,templates,static}/__init__.py`.
- [ ] T003 [P] Configure `pytest-asyncio` in `pyproject.toml` `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`. Verify `pytest --collect-only` runs without errors.
- [ ] T004 [P] Update `.gitignore` to exclude `~/.local/share/tube-scout/admin.db`, `*.db-wal`, `*.db-shm`. Add `coverage.xml`, `htmlcov/`.
- [ ] T005 [P] Create runtime directories on first boot: `~/.config/tube-scout/`, `~/.local/share/tube-scout/{logs,locks}/`. Add a helper `src/tube_scout/web/paths.py` exposing `CONFIG_DIR`, `STATE_DIR`, `LOG_DIR`, `LOCK_DIR` constants resolved via `xdg_base_dirs` fallback.

**Checkpoint**: Skeleton imports cleanly (`python -c "from tube_scout.web import paths"`).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure used by every user story (models, repos, middleware, runner skeleton, error mapping). Must complete before any story phase begins.

**⚠️ CRITICAL**: No US1/US2/US3 task may start until this phase passes its checkpoint.

### Tests (RED — author and confirm failing first)

- [ ] T006 [P] Write `tests/unit/test_paths.py` covering `CONFIG_DIR`/`STATE_DIR`/`LOG_DIR`/`LOCK_DIR` defaults and override via env (`XDG_CONFIG_HOME`, `XDG_STATE_HOME`).
- [ ] T007 [P] Write `tests/unit/test_departments_repo.py` covering atomic write, schema validation (Pydantic), duplicate alias rejection, mtime-based cache invalidation.
- [ ] T008 [P] Write `tests/unit/test_jobs_repo.py` covering `analysis_jobs` CRUD: insert pending, transition to running/completed/failed/interrupted, status check constraint enforcement, monotonic stage transitions, FK to departments.
- [ ] T009 [P] Write `tests/unit/test_results_repo.py` covering `analysis_results` insert + lookup + JSON round-trip for `priority_summary`.
- [ ] T010 [P] Write `tests/unit/test_reviews_repo.py` covering `reuse_review_status` UPSERT, status enum check, note length 512 cap.
- [ ] T011 [P] Write `tests/unit/test_operator_actions_repo.py` covering append-only insert + `at DESC` ordering.
- [ ] T012 [P] Write `tests/unit/test_session_signing.py` covering itsdangerous signing/verification, 8h expiration, tamper detection, CSRF token generation.
- [ ] T013 [P] Write `tests/unit/test_rate_limit.py` covering in-memory `LoginAttempt` increment, 5-failure threshold, 5-minute lock, success reset.
- [ ] T014 [P] Write `tests/unit/test_password_hashing.py` covering bcrypt verify against pre-hashed env value, wrong password rejection, malformed hash handling.
- [ ] T015 [P] Write `tests/unit/test_error_mapping.py` asserting every internal error code in `web/errors.py` has a Korean user message and that no message leaks env/path/stack identifiers.
- [ ] T016 [P] Write `tests/unit/test_progress_serializer.py` covering stage-label Korean mapping for all 8 stages and JSON shape per http-routes.md GET /progress contract.
- [ ] T017 [P] Write `tests/unit/test_filename_slug.py` covering `{display_name}_{professor}_{course}_{period}` slug builder, RFC-5987 encoding for Content-Disposition.
- [ ] T018 [P] Write `tests/unit/test_lifespan_env_validation.py` covering app startup failure when required env vars are missing (Constitution II Fail-Fast).
- [ ] T019 [P] Write `tests/integration/test_app_boot.py` validating Starlette app builds via `create_app()` with all middlewares wired and `/healthz` returning 200.

### Implementation (GREEN — minimum code to pass tests)

- [ ] T020 [P] Create Pydantic v2 models for `Department`, `AnalysisJob`, `AnalysisResult`, `ReviewStatus`, `OperatorAction`, `SessionPayload`, `LoginAttempt` in `src/tube_scout/web/models.py` per data-model.md.
- [ ] T021 Implement `src/tube_scout/web/repo/db.py` — SQLite connection factory, WAL mode enable, schema bootstrap (`CREATE TABLE IF NOT EXISTS` for all 5 tables + indexes per data-model.md), migration version table.
- [ ] T022 [P] Implement `src/tube_scout/web/repo/departments_repo.py` — atomic JSON write, mtime cache, Pydantic validation. Depends on T020.
- [ ] T023 [P] Implement `src/tube_scout/web/repo/jobs_repo.py` — `insert_pending`, `transition_to`, `update_progress`, `find_by_id`, `find_in_progress_for_department`, `list_history(filters, limit, offset)`. Depends on T020, T021.
- [ ] T024 [P] Implement `src/tube_scout/web/repo/results_repo.py` — `insert_result`, `get_result`. Depends on T020, T021.
- [ ] T025 [P] Implement `src/tube_scout/web/repo/reviews_repo.py` — `upsert_review`, `find_by_pair`, `list_for_job`. Depends on T020, T021.
- [ ] T026 [P] Implement `src/tube_scout/web/repo/operator_actions_repo.py` — `record_action(action, target_alias, actor, result, detail)`. Depends on T020, T021.
- [ ] T027 [P] Implement `src/tube_scout/web/middleware/session.py` — itsdangerous serializer wrapper, signing/verification, 8h expiration check, CSRF token issue+verify helpers. Depends on T020.
- [ ] T028 [P] Implement `src/tube_scout/web/middleware/rate_limit.py` — in-memory `LoginAttempt` tracker class, `register_failure`, `register_success`, `is_locked`. No external dependencies.
- [ ] T029 [P] Implement `src/tube_scout/web/middleware/auth_required.py` — Starlette middleware that 302-redirects unauthenticated requests to `/login?next=<path>`, allowlists `/login` and `/healthz`. Depends on T027.
- [ ] T030 [P] Implement `src/tube_scout/web/middleware/security_headers.py` — adds `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` per http-routes.md cross-cutting.
- [ ] T031 [P] Implement `src/tube_scout/web/middleware/https_redirect.py` — 308 redirect HTTP→HTTPS unless `X-Forwarded-Proto: https` header set by reverse proxy.
- [ ] T032 Implement `src/tube_scout/web/errors.py` — error code → Korean user message dict, `to_user_message(code, **ctx)` helper, fallback "내부 오류 — 운영자에게 문의하세요". Depends on T015.
- [ ] T033 [P] Implement `src/tube_scout/web/jobs/progress.py` — in-memory `JobProgress` dataclass + serializer to JSON shape from http-routes.md, stage-label Korean mapping.
- [ ] T034 [P] Implement `src/tube_scout/web/jobs/runner.py` — asyncio Task spawner, per-department `fcntl.flock(LOCK_EX | LOCK_NB)` on `~/.local/share/tube-scout/locks/{alias}.lock`, lifecycle hooks (start, stage transition, complete, fail, interrupted on shutdown). Depends on T023, T033.
- [x] T035 Implement `src/tube_scout/web/jobs/pipeline.py` — 7-stage orchestrator. Initial stub landed under T035 (commits 3edbe4f/8600948); real services integration shipped under **T035-bis** (commit 2739abf) — see entry below. Depends on T034.
- [ ] T036 Implement `src/tube_scout/web/app.py` — `create_app() -> Starlette` factory, lifespan that validates required env vars (`TUBE_SCOUT_ADMIN_USERNAME`, `TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT`, `TUBE_SCOUT_SESSION_SECRET`) and bootstraps DB. Mounts middlewares (https_redirect → security_headers → session → auth_required → rate_limit) and registers route groups (added in story phases). Depends on T021, T027, T028, T029, T030, T031, T032, T036.
- [ ] T037 Implement `GET /healthz` route in `src/tube_scout/web/routes/health.py` returning 200 `text/plain` `ok`, registered in `app.py`.

**Checkpoint**: All Phase 2 tests GREEN; `uvicorn tube_scout.web.app:create_app --factory --port 8000` boots and `/healthz` responds 200.

---

## Phase 3: User Story 1 — 분석 실행 + 진행률 + 결과 다운로드 (Priority: P1) 🎯 MVP

**Goal**: 교무과 담당자가 로그인 후 학과·교수·과목·기간 4개 입력으로 분석을 시작하고, 진행률을 화면에서 확인하고, 완료 시 HTML/PDF/Excel 보고서를 같은 화면에서 다운로드한다(spec FR-001~018, SC-001~006, SC-010~011).

**Independent Test**: 운영자가 학과 1개를 등록하고 `tube-scout admin verify <alias>`로 검증한 후, 비개발자 테스터가 quickstart Scenario A를 5분 이내·터미널 0회 접근으로 통과한다.

### Tests for User Story 1 (RED first)

- [ ] T038 [P] [US1] Write `tests/contract/test_auth_routes.py` per http-routes.md POST /login section: `test_post_login_success_sets_session_cookie`, `test_post_login_invalid_credentials_shows_kr_message`, `test_post_login_locks_after_5_failures`, `test_post_login_locked_returns_403_with_remaining_seconds`, `test_post_login_missing_csrf_returns_400`, `test_get_login_renders_form`, `test_post_logout_clears_cookie`.
- [ ] T039 [P] [US1] Write `tests/contract/test_jobs_form_routes.py` per http-routes.md POST /jobs section: `test_get_jobs_new_renders_form_with_department_dropdown`, `test_post_jobs_creates_job_and_redirects`, `test_post_jobs_validation_blank_fields`, `test_post_jobs_validation_period_end_before_start`, `test_post_jobs_validation_future_period_start`, `test_post_jobs_unknown_department_alias`, `test_post_jobs_rejects_when_same_department_running`, `test_post_jobs_job_id_matches_yyyymmdd_hhmmss_pattern`.
- [ ] T040 [P] [US1] Write `tests/contract/test_progress_routes.py` per http-routes.md GET /jobs/{id}/progress section: `test_progress_running_returns_processed_total`, `test_progress_completed_returns_done_stage`, `test_progress_failed_returns_kr_error_message`, `test_progress_404_for_unknown_job`, `test_progress_no_internal_paths_in_response`.
- [ ] T041 [P] [US1] Write `tests/contract/test_files_routes.py` per http-routes.md GET /jobs/{id}/files/{kind} section: `test_files_v1v3_html_inline_disposition`, `test_files_pdf_attachment_with_korean_filename`, `test_files_unknown_kind_returns_404`, `test_files_missing_disk_returns_kr_message`, `test_files_traversal_rejected`, `test_files_all_5_kinds_resolve_for_completed_job`.
- [ ] T042 [P] [US1] Write `tests/contract/test_results_route.py`: `test_get_jobs_id_results_renders_all_5_download_links`, `test_get_jobs_id_redirects_to_progress_when_running`, `test_get_jobs_id_redirects_to_results_when_completed`.
- [ ] T043 [P] [US1] Write `tests/integration/test_login_flow.py` covering full login round-trip with bcrypt verification, session cookie issuance, redirect to `next` URL, logout invalidates session.
- [x] T035-bis [US1] Refactored `src/tube_scout/cli/collect.py` to add a Typer-free internal helper `_collect_all_for_web(*, department_alias, professor_name, course_name, period_start, period_end, project_dir, on_progress)` (architect ADR-006 R-8 — `on_progress: Callable[[str, int, int], None]` per-stage callback). `src/tube_scout/web/jobs/pipeline.py` calls it from listing/metadata/transcripts/retention/analytics stages, then dispatches to `_run_reuse_detection_stage` (spec 007 import-guard with WARN log on absence — Constitution II silent-skip avoidance) and `_run_reporting_stage` (BundleReportGenerator wiring — patchable test surface). `pipeline.not_integrated` error code removed (R-9). RED test: `tests/integration/test_pipeline_real_services.py` (5 cases GREEN). R-10 baseline: `tests/integration/test_collect_cli_no_regression.py` (15 cases — public Typer command signatures preserved). Commits: 7950c97 (R-10 baseline), e07451e (T035-bis RED), 2739abf (T035-bis GREEN).
- [ ] T044 [P] [US1] Write `tests/integration/test_job_lifecycle_happy_path.py` mocking each service-layer call, asserting 7 stage transitions, progress JSON shape per stage, completion writes `analysis_results` row, files materialize under `projects/{job_id}/`.
- [ ] T045 [P] [US1] Write `tests/integration/test_concurrent_departments.py` starting 2 jobs on different aliases simultaneously, asserting both complete with separate `result_dir` and progress streams (spec FR-029).
- [ ] T046 [P] [US1] Write `tests/integration/test_concurrent_same_department.py` starting 2 jobs on the same alias, asserting the second receives 409 with Korean rejection message (spec FR-028).
- [ ] T047 [P] [US1] Write `tests/integration/test_pipeline_oauth_expired.py` mocking OAuth refresh failure at stage 3, asserting `status=failed`, `error_code=oauth_expired`, no internal path leaks.
- [ ] T048 [P] [US1] Write `tests/integration/test_pipeline_quota_exceeded.py` mocking 403 quotaExceeded from YouTube Data API, asserting Korean message + state transition.
- [ ] T049 [P] [US1] Write `tests/integration/test_pipeline_no_videos_matched.py` mocking empty results, asserting status=completed but result page renders "조건에 맞는 영상이 없습니다" without empty file links (spec FR-007e in scenario 5).
- [ ] T050 [P] [US1] Write `tests/integration/test_session_expiry.py` advancing clock past 8h, asserting next request 302→/login.
- [ ] T051 [P] [US1] Write `tests/integration/test_https_redirect.py` asserting HTTP request without `X-Forwarded-Proto: https` returns 308 to HTTPS.

### Implementation for User Story 1

- [ ] T052 [P] [US1] Implement `src/tube_scout/web/routes/auth.py` — `GET /login`, `POST /login`, `POST /logout`. Uses repo + middleware from Phase 2.
- [ ] T053 [P] [US1] Implement `src/tube_scout/web/routes/jobs.py` — `GET /jobs/new`, `POST /jobs`, `GET /jobs/{job_id}` (router that branches by status to progress vs results page).
- [ ] T054 [P] [US1] Implement `GET /jobs/{job_id}/progress` JSON route in `src/tube_scout/web/routes/jobs.py` (extends T053 file).
- [ ] T055 [P] [US1] Implement `src/tube_scout/web/routes/results.py` — `GET /jobs/{job_id}/results` (HTML), `GET /jobs/{job_id}/files/{kind}` (FileResponse with Korean Content-Disposition slug, traversal protection).
- [ ] T056 [P] [US1] Create Jinja2 base layout `src/tube_scout/web/templates/base.html` (한국어 lang, UTF-8, CSRF token meta tag, minimal CSS link).
- [ ] T057 [P] [US1] Create `src/tube_scout/web/templates/login.html` per spec FR-001~004 with username/password form + CSRF.
- [ ] T058 [P] [US1] Create `src/tube_scout/web/templates/form.html` — 학과 dropdown(Department list), 교수명/과목명/기간 inputs, [분석 시작] button. Client-side validation hints in Korean.
- [ ] T059 [P] [US1] Create `src/tube_scout/web/templates/progress.html` — current stage label (Korean), processed/total counter, polling JS that hits `/jobs/{id}/progress` every 3s.
- [ ] T060 [P] [US1] Create `src/tube_scout/web/templates/result.html` — 5개 다운로드 링크(v1v3 HTML/PDF/Excel + reuse HTML/Excel), 매칭 영상 수, 우선순위 요약 표.
- [ ] T061 [P] [US1] Create `src/tube_scout/web/templates/error.html` — 한국어 오류 메시지 + [재실행] 또는 [홈으로] 진입점.
- [ ] T062 [P] [US1] Create `src/tube_scout/web/static/css/app.css` — 최소 스타일(폼, 테이블, 진행률 바, 한국어 폰트 fallback).
- [ ] T063 [P] [US1] Create `src/tube_scout/web/static/js/progress.js` — 폴링 fetch + DOM 업데이트, 완료 시 `/jobs/{id}/results`로 자동 이동.
- [ ] T064 [US1] Wire all US1 routes into `app.py` (`auth_routes`, `jobs_routes`, `results_routes`) and mount `/static`. Depends on T052, T053, T054, T055.
- [ ] T065 [US1] Verify all US1 contract + integration tests are GREEN. If any fail, fix implementation (Constitution III/IV: do not weaken tests). Run `pytest tests/contract/ tests/integration/ -v -k "US1 or auth or jobs or progress or files or results or pipeline or login or session or https"`.

**Checkpoint**: User Story 1 fully functional and testable independently — quickstart Scenario A passes manually + all US1 tests GREEN. **MVP READY.**

---

## Phase 4: User Story 2 — 이력 재열람 + 재실행 + 재사용 탐지 리뷰 (Priority: P2)

**Goal**: 사용자가 과거 분석 이력 목록에서 항목을 클릭해 결과를 재열람하고, 실패/중단 작업은 checkpoint 기반 재실행으로 빠르게 회복하고, 재사용 탐지 영상 쌍에 [중복 확정]/[오탐] 리뷰를 영속한다(spec FR-019~022a, SC-005, SC-009).

**Independent Test**: US1을 통해 완료/실패/중단 이력 3건이 쌓인 상태에서 quickstart Scenario D + Scenario C 후반부([재실행])가 통과한다.

### Tests for User Story 2 (RED first)

- [ ] T066 [P] [US2] Write `tests/contract/test_history_routes.py` per http-routes.md GET /history: `test_history_lists_jobs_newest_first`, `test_history_filters_by_status`, `test_history_filters_by_department`, `test_history_pagination_limit_offset`, `test_history_links_each_row_to_job_view`, `test_history_renders_korean_status_labels`.
- [ ] T067 [P] [US2] Write `tests/contract/test_retry_routes.py` per http-routes.md POST /jobs/{id}/retry: `test_retry_failed_job_creates_new_job_id`, `test_retry_completed_job_rejected_409`, `test_retry_interrupted_job_succeeds`, `test_retry_missing_csrf_rejected`.
- [ ] T068 [P] [US2] Write `tests/contract/test_reviews_routes.py` per http-routes.md POST /jobs/{id}/reviews/{pair_id}: `test_review_marks_pair_as_confirmed_duplicate`, `test_review_marks_pair_as_false_positive`, `test_review_unknown_pair_returns_404`, `test_review_invalid_status_rejected`, `test_review_note_over_512_rejected`.
- [ ] T069 [P] [US2] Write `tests/integration/test_checkpoint_resume.py` simulating failure at stage 5, asserting [재실행] starts a new job_id but resumes from stage 5 using spec 007 checkpoint, completes faster than full re-run.
- [ ] T070 [P] [US2] Write `tests/integration/test_review_persistence_next_run.py` mocking spec 007 reuse detection: mark pair as `false_positive` in run 1, run analysis again with same inputs, assert pair excluded from new alerts (spec FR-020 + SC-009).
- [ ] T071 [P] [US2] Write `tests/integration/test_history_full_flow.py` creating 5 mixed-status jobs, fetching `/history` with various filters, asserting ordering + filter correctness.

### Implementation for User Story 2

- [ ] T072 [P] [US2] Implement `src/tube_scout/web/routes/history.py` — `GET /history` with query parsing, repo call, Jinja2 render.
- [ ] T073 [P] [US2] Implement `POST /jobs/{job_id}/retry` in `src/tube_scout/web/routes/jobs.py` (extends US1 file) — validates status, generates new job_id, calls `runner.run_job(new_id, resume_from=original_id)`.
- [ ] T074 [P] [US2] Implement `src/tube_scout/web/routes/reviews.py` — `POST /jobs/{job_id}/reviews/{pair_id}` with status enum validation, note length cap, repo upsert.
- [ ] T075 [P] [US2] Extend `src/tube_scout/web/jobs/pipeline.py` (or add `pipeline_resume.py`) to honor `resume_from` parameter — read spec 007 checkpoint, skip stages already complete, resume at next stage. Depends on existing T035.
- [ ] T076 [P] [US2] Extend `src/tube_scout/web/jobs/pipeline.py` reuse detection stage to filter out pairs whose `ReviewStatus` is `confirmed_duplicate` or `false_positive` from new alerts (spec FR-020).
- [ ] T077 [P] [US2] Create `src/tube_scout/web/templates/history.html` — 표 형태(학과, 교수명, 과목명, 기간, 생성일시, 상태) 최신순, 상태/학과 필터 폼, 페이지네이션.
- [ ] T078 [P] [US2] Extend `src/tube_scout/web/templates/result.html` — 재사용 탐지 영상 쌍 목록 + [중복 확정]/[오탐]/[미검토 회복] 버튼, note textarea (선택, 0–512자).
- [ ] T079 [P] [US2] Add `[재실행]` button to `src/tube_scout/web/templates/error.html` (POST form to `/jobs/{id}/retry` with CSRF).
- [ ] T080 [US2] Wire `history_routes`, `reviews_routes` into `app.py`. Depends on T072, T074.
- [ ] T081 [US2] Verify all US2 tests GREEN. Run `pytest tests/contract/ tests/integration/ -v -k "US2 or history or retry or review or checkpoint"`.

**Checkpoint**: US1 + US2 both functional independently — quickstart Scenario D passes, retry → checkpoint resume works, review status survives next analysis.

---

## Phase 5: User Story 3 — 운영자 CLI (학과 등록·상태·갱신·검증) (Priority: P3)

**Goal**: 운영자가 CLI 명령으로 신규 학과 등록(agenix 시크릿 매핑 + OAuth 동의)과 토큰 상태 모니터링·갱신·검증을 수행한다. 사용자 1회 셋업 5분 이하·이후 사용자 추가 인증 0회를 달성한다(spec FR-024~027, SC-007).

**Independent Test**: quickstart Scenario "사전 준비 §3 학과 등록" → `verify` 6단계 모두 ✓ → 사용자 화면 새로고침 시 신규 학과 드롭다운 노출.

### Tests for User Story 3 (RED first)

- [ ] T082 [P] [US3] Write `tests/integration/test_admin_add_department.py` per admin-cli.md §1: `test_add_department_writes_departments_json`, `test_add_department_rejects_duplicate_alias`, `test_add_department_validates_alias_pattern`, `test_add_department_fails_when_env_missing`, `test_add_department_records_operator_action`, `test_add_department_no_oauth_consent_flag_skips_browser`.
- [ ] T083 [P] [US3] Write `tests/integration/test_admin_list.py` per admin-cli.md §2: `test_list_outputs_registered_departments`, `test_list_json_flag_returns_machine_readable`, `test_list_no_departments_shows_empty_message`.
- [ ] T084 [P] [US3] Write `tests/integration/test_admin_status.py` per admin-cli.md §3: `test_status_flags_expired_tokens_red`, `test_status_flags_near_expiry_yellow`, `test_status_shows_running_jobs_count`, `test_status_alias_filter_returns_single`, `test_status_json_output_contract`, `test_status_records_operator_action`.
- [ ] T085 [P] [US3] Write `tests/integration/test_admin_refresh.py` per admin-cli.md §4: `test_refresh_unknown_alias_rejected`, `test_refresh_skips_valid_token_without_force`, `test_refresh_force_renews_anyway`, `test_refresh_records_failure_on_invalid_grant`.
- [ ] T086 [P] [US3] Write `tests/integration/test_admin_verify.py` per admin-cli.md §5: `test_verify_all_steps_pass_returns_zero`, `test_verify_missing_env_var_fails_with_kr_message`, `test_verify_invalid_token_fails_at_step_5`, `test_verify_api_quota_exceeded_reports_kr_message`.
- [ ] T087 [P] [US3] Write `tests/integration/test_admin_status_log_channel.py` asserting that token expiry detection writes a structured log line (file or `journald`-compatible JSON) per spec Q3 / FR-026 — covers the second half of the alert channel decision.
- [ ] T088 [P] [US3] Write `tests/integration/test_admin_dropdown_refresh.py` adding a new department via `admin add-department` while the web app is running, asserting next `GET /jobs/new` page shows the new alias without server restart (spec FR-025).

### Implementation for User Story 3

- [ ] T089 [P] [US3] Create `src/tube_scout/cli/admin.py` — Typer subcommand group skeleton (`admin_app = typer.Typer(help="운영자 전용 명령")`), register in `cli/main.py` via `app.add_typer(admin_app, name="admin")`.
- [ ] T090 [P] [US3] Implement `tube-scout admin add-department` per admin-cli.md §1 — Pydantic-validated options, env presence check (Constitution II Fail-Fast), atomic write to `departments.json`, optional OAuth consent flow via `services.auth`, `OperatorAction` log. Depends on T022, T026, T089.
- [ ] T091 [P] [US3] Implement `tube-scout admin list` per admin-cli.md §2 — read repo, render `rich.Table` (Korean headers) or JSON. Depends on T022, T089.
- [ ] T092 [P] [US3] Implement `tube-scout admin status` per admin-cli.md §3 — for each department: load token, compute expiry delta, query running jobs from `jobs_repo`, summarize last 7d operator actions, color-code output, log structured event to file under `LOG_DIR/admin-status.log`. Depends on T022, T023, T026, T089.
- [ ] T093 [P] [US3] Implement `tube-scout admin refresh <alias> [--force]` per admin-cli.md §4 — call `services.auth.refresh_token`, log result. Depends on T022, T026, T089.
- [ ] T094 [P] [US3] Implement `tube-scout admin verify <alias>` per admin-cli.md §5 — 6-step health check, exit 0 on full success, 1 on any failure, log result. Depends on T022, T026, T089.
- [ ] T095 [US3] Verify all US3 tests GREEN. Run `pytest tests/integration/test_admin_*.py -v`.

**Checkpoint**: US1 + US2 + US3 all independently functional. quickstart full flow ("사전 준비" → Scenario A → D) passes end-to-end.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Hardening, documentation, NixOS integration, end-to-end validation.

### Tests

- [ ] T096 [P] Write `tests/integration/test_security_headers.py` asserting every response carries `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` (covers cross-cutting requirement).
- [ ] T097 [P] Write `tests/integration/test_no_secrets_in_responses.py` — sweep all 14 routes with sample payloads, regex-scan response bodies + headers for `TUBE_SCOUT_*`, token strings (`ya29.`, `1//`), `~/.config/tube-scout/`, `agenix` references, and assert 0 hits (spec SC-006).
- [ ] T098 [P] Write `tests/integration/test_korean_messages_only.py` — sweep all 4xx responses, assert `error_message_kr` field present and matches Korean Unicode block; English stack traces appear only in log file, never in HTTP body.
- [ ] T099 [P] Write `tests/integration/test_full_quickstart_scenario_a.py` automating quickstart Scenario A end-to-end with `httpx.AsyncClient`: login → submit job → poll progress until `done` → download all 5 files → assert each is non-empty and matches expected MIME.

### Implementation

- [ ] T100 [P] Create `flake.nix` (or amend if exists) NixOS module section with `agenix` configuration referencing `tube-scout-{shared,physiology,nursing,...}.age` and a `systemd.services.tube-scout-admin-web` unit running `uvicorn tube_scout.web.app:create_app --factory --uds /run/tube-scout/admin-web.sock`.
- [ ] T101 [P] Create `docs/008-admin-web-ui-deployment.md` with: agenix file format examples, nginx/Caddy reverse proxy snippet (HTTPS + UDS upstream), systemd unit overlay, log rotation hint, backup recommendation for `admin.db`.
- [ ] T102 Run `ruff check src/tube_scout/web/ src/tube_scout/cli/admin.py tests/`. Fix all issues (no `--no-fix`).
- [ ] T103 Run `ruff format src/tube_scout/web/ src/tube_scout/cli/admin.py tests/`.
- [ ] T104 [P] Run `pytest --cov=tube_scout.web --cov=tube_scout.cli.admin --cov-report=term-missing --cov-fail-under=85`. Fix gaps.
- [ ] T105 Update project-level `CLAUDE.md` "Active Technologies" line for 008 to enumerate the actual additions (`starlette`, `uvicorn`, `itsdangerous`, `bcrypt`, `python-multipart`, `pytest-asyncio`, `httpx`) — replace the bare "Python 3.11" auto-generated line.
- [ ] T106 Manually run quickstart §사전준비 + Scenario A through E on the developer machine. Record any deviations and open follow-up issues.
- [ ] T107 Bump `pyproject.toml` version (per memory `feedback_version_policy`: idea 번호 ≠ 제품 버전 — bump MINOR per Constitution governance, e.g., 0.2.0 → 0.3.0). Commit message: `chore(release): 0.3.0 — feature 008 admin web UI`.

**Checkpoint**: All tests GREEN, coverage ≥85%, security/secrets/i18n cross-checks pass, deployment doc shipped, version bumped.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No prerequisites. T001 must finish before T002–T005 (lockfile must exist).
- **Foundational (Phase 2)**: Depends on Phase 1 complete. Tests T006–T019 author first; implementation T020–T037 follows. T020 (models) blocks all repos. T021 (DB schema) blocks T023–T026. T036 (`app.py`) is the integration point — last to land in Phase 2.
- **Phase 3 (US1)**: Depends on Phase 2 checkpoint passing.
- **Phase 4 (US2)**: Depends on Phase 2 + US1 routes file (jobs.py — extends, not replaces) + US1 templates.
- **Phase 5 (US3)**: Depends on Phase 2 only (CLI is independent of web routes; uses repos).
- **Phase 6**: Depends on US1, US2, US3 all GREEN.

### User Story Dependencies

- **US1 (P1)**: depends only on Phase 2.
- **US2 (P2)**: extends US1 jobs.py + templates/result.html. Cannot be tested in isolation without US1's pipeline + result page.
- **US3 (P3)**: independent of US1/US2 (CLI uses repos directly). Can be developed in parallel with US1 by a second contributor.

### Within Each Story

- All `[P]` test tasks (T038–T051, T066–T071, T082–T088) author first and confirm RED.
- Models/repos before services before routes before templates.
- Verify tests GREEN at the end of each story (T065, T081, T095).

### Parallel Opportunities

- **Phase 1**: T002–T005 in parallel after T001.
- **Phase 2**: T006–T019 (all 14 unit/integration RED tests) in parallel. T022–T034 (most repos + middlewares) in parallel after T020+T021.
- **US1**: T038–T051 (14 tests) in parallel. T052–T063 (routes + templates + static) largely in parallel; T064 + T065 last.
- **US2**: T066–T071 in parallel. T072–T079 in parallel; T080 + T081 last.
- **US3**: T082–T088 in parallel. T090–T094 in parallel after T089.
- **Cross-story**: After Phase 2 checkpoint, US1 and US3 can run in parallel by 2 contributors.

---

## Parallel Example: User Story 1 RED tests

```bash
# Author all US1 contract + integration tests in parallel (separate files):
Task: "Write tests/contract/test_auth_routes.py"
Task: "Write tests/contract/test_jobs_form_routes.py"
Task: "Write tests/contract/test_progress_routes.py"
Task: "Write tests/contract/test_files_routes.py"
Task: "Write tests/contract/test_results_route.py"
Task: "Write tests/integration/test_login_flow.py"
Task: "Write tests/integration/test_job_lifecycle_happy_path.py"
Task: "Write tests/integration/test_concurrent_departments.py"
Task: "Write tests/integration/test_concurrent_same_department.py"
Task: "Write tests/integration/test_pipeline_oauth_expired.py"
Task: "Write tests/integration/test_pipeline_quota_exceeded.py"
Task: "Write tests/integration/test_pipeline_no_videos_matched.py"
Task: "Write tests/integration/test_session_expiry.py"
Task: "Write tests/integration/test_https_redirect.py"
```

```bash
# After RED confirmed, author route handlers + templates in parallel:
Task: "Implement src/tube_scout/web/routes/auth.py"
Task: "Implement src/tube_scout/web/routes/results.py"
Task: "Create src/tube_scout/web/templates/login.html"
Task: "Create src/tube_scout/web/templates/form.html"
Task: "Create src/tube_scout/web/templates/progress.html"
Task: "Create src/tube_scout/web/templates/result.html"
Task: "Create src/tube_scout/web/static/css/app.css"
Task: "Create src/tube_scout/web/static/js/progress.js"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational checkpoint.
2. Phase 3 US1 → quickstart Scenario A passes.
3. **STOP and VALIDATE**: ship MVP for early feedback.

### Incremental Delivery

1. Setup + Foundational → infrastructure ready.
2. Add US1 → quickstart Scenario A → ship internally.
3. Add US3 (CLI admin) in parallel with US2 by second developer (reduces calendar time).
4. Add US2 → quickstart Scenario D + checkpoint resume.
5. Phase 6 polish + deployment doc + version bump → public release.

### Parallel Team Strategy (dev-squad workflow)

Per memory `feedback_devsquad_full_team`, spawn the full dev-squad team from the start:

- **developer A**: Phase 2 Foundational (T020–T037) → US1 implementation (T052–T064).
- **developer B**: Phase 2 tests (T006–T019) RED → US1 tests (T038–T051) RED → US3 (T082–T094).
- **pair-programmer**: continuous FR ↔ code traceability check across all phases.
- **auditor**: enters at Phase 6 (post-implementation) for security + type + docstring sweep.
- **adversary**: enters after US1 GREEN to attack failure cases (token expiry, traversal, race conditions).

---

## Notes

- **Tests are MANDATORY** (Constitution I = NON-NEGOTIABLE). Every implementation task is preceded by a RED test in the same phase. If a test cannot be authored to fail first, escalate before proceeding.
- **No CLI behavior changes** (Constitution IV / spec FR-022, FR-030). All web routes call existing `services/...` functions; new logic 0 lines outside `web/` and `cli/admin.py`.
- **Secrets are agenix-only** (Constitution VI / spec FR-027). No task introduces a plaintext secret file. `departments.json` carries env-var names only.
- **External DB forbidden** (Constitution V / spec FR-024). SQLite + filesystem + in-memory dict only.
- **Conventional Commits** for every task: `feat(web)`, `test(web)`, `chore(web)`, `docs(web)`, `fix(web)`, `refactor(web)`. Scope `cli` for `admin.py` work.
- **Verify each Checkpoint** before advancing phases — do not let work in progress span checkpoints.
