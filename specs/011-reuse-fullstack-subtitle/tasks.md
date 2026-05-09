---

description: "Task list for spec 011 — Subtitle Full-Stack Reuse Detection (nC2 + Time-axis + 4-Layer Defense)"
---

# Tasks: Subtitle Full-Stack Reuse Detection (nC2 + Time-axis + 4-Layer Defense)

**Input**: Design documents from `/specs/011-reuse-fullstack-subtitle/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli_content.md, contracts/service_layer.md, contracts/db_schema.md, quickstart.md

**Tests**: MANDATORY — Constitution Principle I (Test-First Development, NON-NEGOTIABLE) requires RED → GREEN → REFACTOR for every task. Every implementation task is preceded by a failing test.

**Organization**: Tasks are grouped by user story (US1~US5 from spec.md) so each story can be implemented and validated independently against the spec acceptance criteria.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Different file, no incomplete dependency → can run in parallel
- **[Story]**: US1~US5 — maps task to spec.md user story (Setup / Foundational / Polish phases have no [Story])
- All paths are absolute repo-relative

## Path Conventions (from plan.md)

- Source: `src/tube_scout/{models,services,storage,cli,reporting,visualization}/`
- Tests: `tests/{contract,unit,integration,adversary}/`
- Fixtures: `tests/fixtures/spec011/`
- Specs: `specs/011-reuse-fullstack-subtitle/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project / fixture infrastructure for spec 011 work. Zero new deps (plan.md confirmed).

- [ ] T001 [P] Create fixture directory `tests/fixtures/spec011/` with synthetic caption JSON files (3 cases for time-axis: identical 20-min contiguous, 5-min × 4 scattered, 2-min disjoint) and 1 baseline-corpus fixture (5-video professor) — all under `tests/fixtures/spec011/captions/`
- [ ] T001a [P] Create labelled 4-pattern fixture set `tests/fixtures/spec011/patterns/labelled_pairs.json` (≥20 pairs, ≥5 per pattern: whole-same-week / scattered-same-week / whole-different-week / scattered-different-week) with ground-truth pattern label per pair — used by SC-002 95% accuracy assertion in T044a
- [ ] T002 [P] Create default policy template `tests/fixtures/spec011/policy.yaml` carrying defaults from research.md R-4 (`layer_a_min_seconds: 60`, `layer_c_evolution_band: [0.60, 0.75]`, `matching_cosine_cull: 0.55`, `pattern_whole_threshold_ratio: 0.50`, `composite_weights` summing to 1.0)
- [ ] T003 [P] Create test SQLite fixture builder helper at `tests/fixtures/spec011/fixture_db.py` that produces (a) clean spec 011 v2-migrated DB, (b) spec 007 legacy DB for backward-compat tests, (c) synthetic 200-video professor pool builder for perf budget tests, (d) synthetic 4000-pair pre-populated DB for overnight-resume tests
- [ ] T004 Verify `uv sync` + `pytest --collect-only tests/` succeeds with current dependency set (sanity — confirm no new dep needed)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: DB migration, base Pydantic models, advisory lock, phrase normalization, professor resolution, CLI scaffolding. **NO user story can begin until this phase is complete** (every user story imports these).

**⚠️ CRITICAL**: All [Foundation] tasks must complete before any [US*] phase starts.

### Models & DB schema (foundation for all user stories)

- [ ] T005 [P] Write contract test `tests/contract/test_db_schema_v2_contract.py` enforcing `contracts/db_schema.md` (idempotent migration, ALTER columns present, new tables present, CHECK constraints reject invalid enums, `_schema_version` row, spec 007 row preservation, spec 007 column hash unchanged) — RED
- [ ] T006 Implement `migrate_to_v2(db_path: Path)` in `src/tube_scout/storage/content_db.py` — read PRAGMA table_info → ALTER missing columns on `comparison_results` (matching_mode default `'M-default'`, professor_id, i6/i7/i8, reuse_pattern, layer_attribution, baseline_subtracted_length_seconds, pre_subtraction_i2, pre_subtraction_i6) + CREATE IF NOT EXISTS for `professor_pool`, `professor_pool_membership`, `baseline_corpus`, `phrase_whitelist`, `pair_checkpoint`, `match_spans`, `_schema_version` + indexes (`idx_cr_mode`, `idx_cr_prof`, `idx_cr_pattern`, `idx_span_cmp`) + backfill `matching_mode` for legacy rows + integrity_check + stamp `_schema_version='spec-011/v1'`. Single transaction with rollback on failure (GREEN T005)
- [ ] T007 [P] Create `src/tube_scout/models/reuse_v2.py` with Pydantic models: `ReusePatternLabel` (Enum), `LayerAttribution`, `MatchSpan`, `CaptionPool`, `VideoRef`, `BaselinePhrase`, `WhitelistPairEntry`, `WhitelistPhraseEntry`, `PairCheckpoint`, `PolicyConfig`, `CandidatePair`, `TimeAxisResult`, `ProfessorMapping`, `BaselineBootstrapReport`, `WhitelistView` — all with type hints + Google-style English docstrings + Pydantic v2 `model_config` with `frozen=True` where appropriate
- [ ] T008 Extend `ComparisonResult` Pydantic in `src/tube_scout/models/content.py` with new optional fields (matching_mode literal, professor_id, i6/i7/i8, reuse_pattern, layer_attribution list, baseline_subtracted_length_seconds, pre_subtraction_i2/i6) — backward compat: all new fields default-able so spec 007 callers unaffected

### Policy YAML loader

- [ ] T009 [P] Write unit test `tests/unit/test_policy_loader.py` — load valid YAML, reject invalid (composite_weights ≠ 1.0, band out of [0,1], negative threshold), missing file message points to `tube-scout content policy show > policy.yaml` — RED
- [ ] T010 Implement `src/tube_scout/services/policy_loader.py::load_policy(project_dir: Path) -> PolicyConfig` — read `02_analyze/content/policy.yaml`, parse via PolicyConfig Pydantic, validate composite_weights sum within ±0.01 of 1.0, fail-fast with English actionable message when missing or invalid (GREEN T009)

### Advisory lock

- [ ] T011 [P] Write unit test `tests/unit/test_advisory_lock.py` — first writer acquires `BEGIN IMMEDIATE`, second concurrent writer raises `ConcurrentWriteRejected`, lock released on context exit even on exception — RED
- [ ] T012 Implement `src/tube_scout/services/advisory_lock.py::layer_d_write_lock(db_path)` context manager + `ConcurrentWriteRejected` exception — wraps SQLite `BEGIN IMMEDIATE`, translates `OperationalError("database is locked")` to standard English message (GREEN T011)

### Phrase normalization (single source of truth used by Layer B + Layer D)

- [ ] T013 [P] Write unit test `tests/unit/test_phrase_whitelist_normalize.py` — NFKC unifies full-width/half-width, lowercase only English letters, punctuation set stripped (Korean punctuation `。、，「」『』""''‥…` + ASCII), multi-whitespace collapsed, leading/trailing trim, idempotent — RED
- [ ] T014 Implement `src/tube_scout/services/phrase_whitelist.py::normalize_phrase(text: str) -> str` (5 steps per research.md R-7: NFKC → lowercase → punct strip → ws collapse → trim) (GREEN T013)

### Professor resolver (cross-channel pool unification — Q4)

- [ ] T015 [P] Write unit test `tests/unit/test_professor_resolver.py` — `map_professor` idempotent, duplicate `(channel, __channel_owner__)` for different professor_id raises ValueError, `resolve_caption_pool` walks all memberships, missing mapping triggers fallback to channel-only pool — RED
- [ ] T016 Implement `src/tube_scout/services/professor_resolver.py` (`map_professor`, `unmap_professor`, `list_professors`, `resolve_caption_pool`) calling spec 003 `resolve_channel_alias()` — never directly parses channels.json (boundary B-6) (GREEN T015)

### CLI scaffolding (groups for later wiring)

- [ ] T017 Add Typer subcommand groups in `src/tube_scout/cli/content.py` for `professor`, `baseline`, `whitelist`, `policy` — placeholder commands that fail-fast with "Not yet implemented; pending US3/US4 implementation" so contract tests can verify command tree shape independently of behavior
- [ ] T018 Wire `migrate_to_v2(db_path)` to be called once at every spec 011 CLI entry (lazy startup hook in `cli/content.py`) — idempotent, runs before any DB read/write

**Checkpoint**: Foundation ready. All user story phases (US1~US5) can now begin. Foundation includes (a) v2-migrated DB schema, (b) all Pydantic models, (c) PolicyConfig loader, (d) advisory lock, (e) phrase normalization, (f) professor resolver, (g) CLI command tree. Spec 007 callers continue to work unchanged.

---

## Phase 3: User Story 1 — nC2 Cross-Pair Matching across Years and Courses (Priority: P1) 🎯 MVP

**Goal**: 한 교수의 caption pool(채널 경계 무관)에서 nC2 모든 쌍을 비교 후보로 생성하고, 1차 cosine cull로 후보를 줄여 spec 007의 5 지표를 적용해 의심 쌍을 정렬한다. 시간축 지표(I-6/I-7/I-8)는 US2에서 추가 — US1 MVP는 spec 007 지표만으로도 cross-course 재활용을 검출.

**Independent Test**: 같은 교수의 2개 이상 영상 자막이 수집된 상태에서 `tube-scout content scan --mode nc2 --professor <id>`를 실행하면 nC2 쌍이 생성되고 cosine cull 후 후보 쌍의 5 지표가 산출되어 `comparison_results`에 `matching_mode='M-nC2'`로 저장된다.

### Tests for User Story 1 (RED — must fail before implementation)

- [ ] T019 [P] [US1] Write contract test `tests/contract/test_cli_content_v2_contract.py::test_compare_scan_mode_options` enforcing `contracts/cli_content.md` §2-§3 — `--mode {default,nc2}`, `--professor <id>` required for nc2, conflicting `--channel + --mode nc2` warning + ignore, missing professor mapping → exit 2 with English actionable message — RED
- [ ] T020 [P] [US1] Write contract test `tests/contract/test_service_layer_contract.py::test_nc2_signatures` enforcing `contracts/service_layer.md` §1, §6, §7 — `nc2_matcher.generate_nc2_pairs/get_caption_pool`, `pair_checkpoint.start_run/iterate_unfinished_pairs/mark_pair_done/finalize_run`, `professor_resolver.resolve_caption_pool/map_professor/unmap_professor/list_professors` exist with exact signatures + Google docstrings — RED
- [ ] T021 [P] [US1] Write unit test `tests/unit/test_nc2_matcher.py` — pair count = nC2(N), cosine cull threshold honored from PolicyConfig, empty pool returns [], single-video pool returns [], professor with 0 mapped videos raises actionable ValueError — RED
- [ ] T022 [P] [US1] Write unit test `tests/unit/test_pair_checkpoint.py` — start_run inserts row, iterate_unfinished skips pairs already in `comparison_results`, mark_pair_done increments count, finalize_run sets status, resume after simulated crash continues from next unfinished pair — RED
- [ ] T023 [P] [US1] Write integration test `tests/integration/test_nc2_pipeline.py::test_nc2_basic_flow` — fixture DB with 5 videos for one professor across 2 channels, run `nc2_matcher.generate_nc2_pairs` → cosine cull → store rows with `matching_mode='M-nC2'` → assert 10 pairs total, candidates after cull ≤ 10, all stored with 5 indicators — RED
- [ ] T024 [P] [US1] Write integration test `tests/integration/test_cross_channel_pool.py` — same professor mapped on `nursing` + `park-personal` aliases, `resolve_caption_pool('prof-x')` returns videos from both channels, nC2 generates pairs across channel boundary (boundary B-1 acceptance) — RED
- [ ] T025 [P] [US1] Write integration test `tests/integration/test_spec007_compatibility.py` — start with spec 007 fixture DB (10 spec 007 rows present), run `migrate_to_v2` + spec 011 nc2 scan, assert: spec 007 rows untouched (column hash matches), spec 007 caption files / embeddings.parquet not regenerated, spec 007 `compare` (default mode) still works after migration (boundary B-2, SC-009) — RED
- [ ] T026 [P] [US1] Write integration test `tests/integration/test_resume_idempotent.py` — simulate Ctrl+C mid-run by truncating `comparison_results` to half-completion, re-invoke scan with `--resume`, assert run completes from last unfinished pair, no duplicate rows, `pair_checkpoint.status='completed'` (FR-031 + SC-006) — RED

### Implementation for User Story 1

- [ ] T027 [P] [US1] Implement `src/tube_scout/services/nc2_matcher.py::get_caption_pool(professor_id, db_path)` — calls `professor_resolver.resolve_caption_pool` + filters by collected captions in `processing_status` (GREEN T021)
- [ ] T028 [P] [US1] Implement `src/tube_scout/services/nc2_matcher.py::generate_nc2_pairs(professor_id, db_path, captions_dir, cosine_cull_threshold)` — load existing embeddings from `embeddings.parquet` (spec 007 boundary B-2), compute pairwise cosine via numpy/polars matrix op, filter by threshold, return list of `CandidatePair` (GREEN T021, T023)
- [ ] T029 [P] [US1] Implement `src/tube_scout/services/pair_checkpoint.py` — `start_run`, `iterate_unfinished_pairs` (UPSERT-aware via `comparison_results` lookup), `mark_pair_done`, `finalize_run`, plus `resume_run(professor_id, mode)` lookup helper (GREEN T022, T026)
- [ ] T030 [US1] Wire `tube-scout content scan --mode nc2 --professor <id> [--resume]` in `src/tube_scout/cli/content.py` — call `nc2_matcher.generate_nc2_pairs` → `pair_checkpoint.start_run` (or resume) → loop unfinished pairs → call existing `services/content_comparator.py::compare_pair` (spec 007 5 indicators) → UPSERT into `comparison_results` with `matching_mode='M-nC2'` + `professor_id` set → `mark_pair_done` → `finalize_run` (GREEN T019, T023, T026)
- [ ] T031 [US1] Wire `tube-scout content compare --mode {default,nc2}` extending spec 007 compare command — when `--mode nc2`, delegate to scan-style flow above; when default, untouched spec 007 path (GREEN T019)
- [ ] T032 [US1] Wire `tube-scout content professor map/list/show/unmap` CLI subcommands in `src/tube_scout/cli/content.py` — `map` advisory-locked, idempotent on duplicate; `unmap` requires explicit alias + author; `show` includes total_videos_in_pool + captions_collected counts (GREEN T024, contracts/cli_content.md §5)
- [ ] T033 [US1] Wire CLI startup hook to call `migrate_to_v2` once per project (lazy) so users do not need a separate migrate command — already scaffolded in T018, now activated for all spec 011 commands

**Checkpoint**: US1 fully functional. spec 007 backward compat preserved. Operator can: (a) map professors across channels, (b) run nC2 scan that produces 5-indicator suspect pairs across years/courses, (c) interrupt and resume. **MVP delivery point** — quickstart.md §3-§6 executable.

---

## Phase 4: User Story 2 — Time-axis Indicators (I-6 / I-7 / I-8) (Priority: P1)

**Goal**: 비교 쌍에 (I-6) 최장 연속 일치 길이, (I-7) 일치 분포 dispersion, (I-8) 위치 다양성을 산출해 통째형/분산형/즉흥 일치를 정량적으로 구별.

**Independent Test**: 합성 자막 3쌍 (a) 20분 연속 일치 (b) 5분×4 분산 일치 (c) 2분 짧은 일치를 입력하면 I-6/I-7/I-8가 세 케이스를 각각 다른 값으로 산출하고, US1의 nC2 결과 row에 컬럼이 채워진다.

### Tests for User Story 2 (RED)

- [ ] T034 [P] [US2] Write unit test `tests/unit/test_time_axis_indicators.py` — feed 3 synthetic caption pair fixtures (T001), assert I-6 ≥ 1200s for case (a), I-6 ≈ 300s for case (b), I-6 < 60s for case (c), I-7 dispersion ranks (b) > (a), I-8 ranks (b) > (a) — RED
- [ ] T035 [P] [US2] Write unit test for `find_match_spans` greedy alignment edge cases — anchor-anchor extension, normalized-exact match (uses `normalize_phrase`), minimum span emission unit, returns sorted-by-start MatchSpan list — RED
- [ ] T036 [P] [US2] Extend `tests/integration/test_nc2_pipeline.py::test_nc2_with_time_axis` — full nC2 → 5 indicators + I-6/I-7/I-8 + match_spans rows persisted; assert pair classified into one of 4 patterns after T040 lands (xfail at this stage, will pass after T040) — RED
- [ ] T036a [P] [US2] Write unit test `tests/unit/test_composite_score.py` (FR-008) — given a `ComparisonResult` with i1~i8 values and a `PolicyConfig.composite_weights` dict, `compute_suspicion_score(result, policy)` returns a 0–100 float; weights summing to 1.0 and all-max indicators yield 100; whole-week reuse (i1=hash, i6 ≥ 0.5×min_duration) reaches `critical` bucket; scattered-different-week with mid-range i2 reaches at least `moderate` bucket per spec.md Assumptions — RED

### Implementation for User Story 2

- [ ] T037 [P] [US2] Implement `src/tube_scout/services/time_axis_indicators.py::find_match_spans(captions_a, captions_b, normalize)` — segment-level normalized exact match + greedy left-to-right span extension per research.md R-2 (GREEN T035)
- [ ] T038 [US2] Implement `src/tube_scout/services/time_axis_indicators.py::compute_time_axis(pair, captions_a, captions_b) -> TimeAxisResult` — calls `find_match_spans` then derives I-6 (max length_seconds), I-7 (stdev of length_seconds + cluster count), I-8 (positional spread across early/middle/late thirds normalized 0-1) (GREEN T034)
- [ ] T038a [P] [US2] Implement `src/tube_scout/services/content_comparator.py::compute_suspicion_score(result, policy) -> tuple[float, str]` (FR-008) — sums weighted indicator contributions per `policy.composite_weights` (i1 hash → 0/1, i2/i3/i6/i7/i8 normalized to 0–1, i4/i5 inverted-and-capped) into 0–100 score, returns `(score, grade)` using bucket cuts (≥80 critical / 60–79 high / 40–59 moderate / <40 normal). Pure function, no DB access (GREEN T036a)
- [ ] T039 [US2] Wire time-axis computation + composite recomputation into `src/tube_scout/services/content_comparator.py::compare_pair` — only when `matching_mode='M-nC2'` (M-default keeps spec 007 fast path); call `compute_time_axis` then `compute_suspicion_score` so `suspicion_score` and `grade` reflect the 8-indicator weighting from `PolicyConfig.composite_weights`; persist `i6/i7/i8/pre_subtraction_i6/suspicion_score/grade` in `comparison_results` and `match_spans` rows in DB (GREEN T036, T036a)
- [ ] T040 [US2] Add per-pair MatchSpan persistence in `src/tube_scout/storage/content_db.py::insert_match_spans(comparison_id, spans)` with idempotent UPSERT keyed on (comparison_id, span_index) — invoked from compare_pair after time-axis computation

**Checkpoint**: US2 functional. nC2 results now carry I-6/I-7/I-8 + match_spans evidence. Pattern classification (US3) and reports (US5) can consume these.

---

## Phase 5: User Story 3 — 4-Layer False-Positive Defense (Priority: P1)

**Goal**: nC2 + 시간축의 false positive 폭증을 (A) 길이 컷 / (B) per-professor stylistic baseline 차감 / (C) 점진 진화 등급 demote / (D) pair + phrase whitelist 4계층으로 방어. 각 비교 쌍은 어떤 Layer가 어떻게 작용했는지 attribution을 기록한다.

**Independent Test**: 4 케이스 (a) 짧은 즉흥 일치 (b) baseline 비유 포함 (c) 70% 동일 점진 진화 (d) 직전 분석에서 FALSE_POSITIVE 마킹된 쌍 — 각각 Layer A/B/C/D가 차단/강등/차감하고 사유가 layer_attribution에 기록된다.

### Tests for User Story 3 (RED)

- [ ] T041 [P] [US3] Write unit test `tests/unit/test_baseline_corpus.py` — bootstrap 5 earliest videos, phrases occurring in ≥3 videos seeded with `seeded=1`, idempotent re-run does not duplicate, `add_baseline_phrase` increments occurrences on duplicate, `subtract_baseline` removes only baseline-matching MatchSpans and reports total subtracted seconds — RED
- [ ] T042 [P] [US3] Write unit test `tests/unit/test_layer_defense.py` — Layer A excludes pair where I-6 < `policy.layer_a_min_seconds` and records `layer="A", action="excluded"`; Layer B subtracts baseline phrase spans and records `pre_subtraction_i6` ≠ post `i6_longest_contiguous_seconds`; Layer C demotes pairs with i2 in `[low, high]` band from `critical/high` to `moderate/normal`; Layer D pair-whitelist (review_status=FALSE_POSITIVE) skipped before measurement; Layer D phrase-whitelist removes phrase-matching spans; Layer order is A → B → D-phrase → C — RED
- [ ] T043 [P] [US3] Write unit test `tests/unit/test_pattern_classifier.py` — `whole-same-week` when I-6 ≥ 0.5 × min(duration_a, duration_b) AND I-7 within median × 1.5 AND week_a == week_b; `scattered-different-week` when I-6 below half ratio OR I-7 disperse AND week_a != week_b OR missing; tie-break documented in code comment — RED
- [ ] T044 [P] [US3] Write integration test `tests/integration/test_layer_defense_pipeline.py` — synthetic 4 cases (a) short impromptu (b) baseline analogy (c) gradual evolution 70% (d) prior FALSE_POSITIVE pair → run scan, assert each row's `layer_attribution` JSON contains the expected layer entry, `grade` reflects demotion (Layer C), `comparison_results` excluded entirely (Layer A), `match_spans` filtered (Layer B/D-phrase) — RED
- [ ] T044a [P] [US3] Write integration test `tests/integration/test_pattern_accuracy.py` (SC-002) — load labelled fixture set from T001a (`labelled_pairs.json`, ≥20 pairs), run pipeline, classify each pair, compute confusion matrix vs ground-truth pattern label, assert `accuracy >= 0.95` overall AND `>= 0.90` per pattern; mark Layer-B-affected pairs separately so absorption rate (SC-004) can be derived: assert recurring stylistic phrases appear in ≤ 10% of suspect pairs after Layer B vs without — RED
- [ ] T045 [P] [US3] Write contract test `tests/contract/test_service_layer_contract.py::test_layer_signatures` enforcing `contracts/service_layer.md` §3-§4 + §8 — `layer_defense.apply_layers`, `baseline_corpus.bootstrap_baseline/add_baseline_phrase/list_baseline/remove_baseline_phrase/subtract_baseline`, `pattern_classifier.classify_reuse_pattern` — RED
- [ ] T046 [P] [US3] Write contract test for `tube-scout content baseline {bootstrap,add,list,remove}` and `content policy {show,validate}` per `contracts/cli_content.md` §6 + §8 — RED

### Implementation for User Story 3

- [ ] T047 [P] [US3] Implement `src/tube_scout/services/baseline_corpus.py` — `bootstrap_baseline` (load earliest N videos by `published_at`, normalize segments, count occurrences across distinct videos, INSERT phrases meeting `min_occurrences` threshold with `seeded=1`), `add_baseline_phrase` (UPSERT incrementing occurrences), `list_baseline`, `remove_baseline_phrase`, `subtract_baseline(professor_id, spans, db_path)` (returns trimmed span list + subtracted seconds) (GREEN T041)
- [ ] T048 [P] [US3] Implement `src/tube_scout/services/pattern_classifier.py::classify_reuse_pattern(comparison, durations, same_week, policy)` returning `ReusePatternLabel` — uses I-6 ratio and I-7 dispersion thresholds from PolicyConfig; M-default rows return None (no pattern) (GREEN T043)
- [ ] T049 [P] [US3] Implement `src/tube_scout/services/layer_defense.py::apply_layers(comparison, spans, professor_id, db_path, policy)` — orchestrates A → B → D-phrase → C in order, attaches `LayerAttribution` records per layer that acted, sets `pre_subtraction_*` columns before B subtraction, returns updated `(comparison, spans)` tuple. Pure (no DB writes — caller persists) per service_layer.md §3 (GREEN T042, T044)
- [ ] T050 [US3] Wire layer_defense + pattern_classifier into `src/tube_scout/services/content_comparator.py::compare_pair` — order: cosine cull (US1) → time-axis (US2) → apply_layers (US3) → classify_reuse_pattern (US3) → persist (GREEN T044)
- [ ] T051 [US3] Implement separate filter helper `src/tube_scout/services/layer_defense.py::filter_pair_whitelisted(candidate_pairs, db_path) -> list[CandidatePair]` that drops pairs already marked `review_status='FALSE_POSITIVE'` in `comparison_results`, and call it in `cli/content.py::scan` between `nc2_matcher.generate_nc2_pairs` and `pair_checkpoint.start_run`. Do NOT modify `iterate_unfinished_pairs` (preserves T029 single-responsibility) (GREEN T044 case d)
- [ ] T052 [US3] Wire `tube-scout content baseline {bootstrap,add,list,remove}` CLI subcommands in `src/tube_scout/cli/content.py` (GREEN T046, contracts/cli_content.md §6)
- [ ] T053 [US3] Wire `tube-scout content policy {show,validate}` CLI subcommands — read-only display of effective policy + composite_weights sum check + band/threshold validation (GREEN T046, contracts/cli_content.md §8)

**Checkpoint**: US3 functional. nC2 results now carry full layer attribution. Run scan on the same data twice with FALSE_POSITIVE marked from US4 to verify Layer D pair short-circuit works.

---

## Phase 6: User Story 4 — Whitelist-Accumulating Review Workflow (Priority: P2)

**Goal**: 운영자가 의심 쌍을 검토하면서 "오탐" + 어구 화이트리스트를 누적해, 다음 분석에서 같은 쌍·같은 어구가 재알림되지 않게 한다. 모든 mutation은 advisory lock 하에 single-active-admin 가정으로 직렬화.

**Independent Test**: scan 결과에서 한 쌍을 FALSE_POSITIVE로 mark + 한 어구를 phrase-whitelist에 add → 같은 분석을 재실행하면 두 입력 모두 0건 재알림으로 반영되고 헤더에 "excluded by Layer D" 카운트가 표시된다 (SC-005).

### Tests for User Story 4 (RED)

- [ ] T054 [P] [US4] Write contract test `tests/contract/test_cli_content_v2_contract.py::test_whitelist_review_commands` enforcing `contracts/cli_content.md` §4 + §7 — `whitelist {add-pair, add-phrase, list, export, remove}` and `review --pattern --status --mark` argument schema, exit codes (0/1/2/3), advisory lock conflict → exit 3 — RED
- [ ] T055 [P] [US4] Write unit test `tests/unit/test_phrase_whitelist.py` — `add_pair_whitelist` updates `comparison_results.review_status='FALSE_POSITIVE'`, `add_phrase_whitelist` enforces UNIQUE(professor_id, phrase_normalized), `list_whitelist` filters by professor + kind, `export_whitelist` produces csv/xlsx/markdown with raw phrase + reason + admin + date columns, `remove_whitelist` for pair resets review_status to UNREVIEWED — RED
- [ ] T056 [P] [US4] Write integration test `tests/integration/test_layer_d_persistence.py` — first scan produces 50 suspect pairs, mark 1 as FALSE_POSITIVE + add 1 phrase to whitelist, second scan: that pair never appears in candidates, that phrase's spans excluded from match calculations across all pairs of the same professor, header shows "excluded by Layer D pair-whitelist: 1, phrase-whitelist hits: N" (SC-005, FR-023) — RED
- [ ] T057 [P] [US4] Write integration test `tests/integration/test_advisory_lock_concurrent.py` — spawn two threads each calling `add_phrase_whitelist`, second receives `ConcurrentWriteRejected` translated to exit 3 with the standard English message at CLI surface — RED

### Implementation for User Story 4

- [ ] T058 [P] [US4] Implement remaining `src/tube_scout/services/phrase_whitelist.py` functions — `add_pair_whitelist(source_video_id, target_video_id, reason, db_path, registered_by)`, `add_phrase_whitelist(professor_id, phrase_raw, reason, db_path, registered_by)`, `list_whitelist(db_path, professor_id, kind)`, `export_whitelist(db_path, fmt, output_path)` (csv/xlsx via openpyxl/markdown), `remove_whitelist(db_path, kind, entry_id)` — all mutations wrapped in `layer_d_write_lock` (GREEN T055, T057)
- [ ] T059 [US4] Wire `tube-scout content whitelist {add-pair, add-phrase, list, export, remove}` CLI subcommands in `src/tube_scout/cli/content.py` — translates `ConcurrentWriteRejected` to exit 3 with standard English message; export honors `--format` and `--output` (GREEN T054)
- [ ] T060 [US4] Extend `tube-scout content review` CLI in `src/tube_scout/cli/content.py` with `--pattern <label>`, `--status {UNREVIEWED|PENDING|CONFIRMED_DUPLICATE|FALSE_POSITIVE}`, `--mark <pair_id> <state>` — uses `add_pair_whitelist` for FALSE_POSITIVE mark (GREEN T054)
- [ ] T061 [US4] Verify Layer D phrase-whitelist hits feed back into `services/phrase_whitelist.py::subtract_phrase_whitelist(spans, professor_id, db_path)` consumed by `layer_defense.apply_layers` (US3 hook now activated) — wire span filtering into Layer D position of pipeline, mark `match_spans.whitelisted=1` (GREEN T056)
- [ ] T062 [US4] Add header summary emission in scan completion message: pair-whitelist count, phrase-whitelist hit count (FR-023) — written to stdout + persisted in `pair_checkpoint` row for later report consumption

**Checkpoint**: US4 functional. quickstart.md §8-§11 executable end-to-end. Layer D fully closed loop.

---

## Phase 7: User Story 5 — Reports with 4-Pattern Classification and Time-axis Evidence (Priority: P2)

**Goal**: HTML 보고서를 4 재활용 패턴별로 분리하고, 각 의심 쌍의 시간축 일치 구간을 시각화하며, Layer B 차감과 Layer D 제외 카운트를 헤더에 명시.

**Independent Test**: 4 패턴이 섞인 합성 데이터에서 `tube-scout report content --professor <id>` 호출 시 패턴별 섹션이 분리된 HTML이 생성되고, 펼치면 시간축 막대 그래프 + 일치 어구 샘플 + (Layer B 적용 시) pre/post 값이 모두 표시된다.

### Tests for User Story 5 (RED)

- [ ] T063 [P] [US5] Write unit test `tests/unit/test_content_report_v2.py` — given fixture `comparison_results` with 4 patterns + Layer B subtraction + Layer D exclusion, generate HTML and assert (a) one section per pattern, (b) headers contain "excluded by Layer D pair-whitelist: N", (c) per-pair detail includes pre/post i6 when `baseline_subtracted_length_seconds > 0`, (d) match-span time-axis chart embedded as static image — RED
- [ ] T064 [P] [US5] Write unit test `tests/unit/test_time_axis_chart.py` — `time_axis_chart.render(spans, duration_a, duration_b)` returns plotly figure with horizontal bars for each MatchSpan on each video timeline, color-coded by `baseline_subtracted` and `whitelisted` flags — RED
- [ ] T065 [P] [US5] Write integration test `tests/integration/test_report_v2_generation.py` — full pipeline + report generation → assert HTML structure (4 sections), Excel has whitelist sheet + baseline sheet (FR-024), JSON output preserves all spec 011 fields — RED

### Implementation for User Story 5

- [ ] T066 [P] [US5] Implement `src/tube_scout/visualization/time_axis_chart.py::render(spans, duration_a, duration_b) -> plotly.graph_objects.Figure` — horizontal bar per span, two rows (video A, video B), color encoding for baseline_subtracted / whitelisted, exported as static PNG via plotly's image export (GREEN T064)
- [ ] T067 [P] [US5] Create Jinja2 template `src/tube_scout/reporting/templates/content_v2.html.j2` — header (counts: total, per-pattern, Layer A excluded, Layer D excluded, Layer B subtraction events) + 4 pattern sections + per-pair expandable detail (i1~i8 table, pre/post columns, time-axis PNG embed, sample matched phrases up to 5) (GREEN T063)
- [ ] T068 [US5] Extend `src/tube_scout/reporting/content_report.py` with `generate_v2_report(project_dir, professor_id, fmt)` — queries `comparison_results` filtered by `matching_mode='M-nC2'` + professor_id, renders HTML via Jinja2, generates Excel (openpyxl) with sheets: Summary / By Pattern / Whitelist / Baseline / Layer Attribution Audit, generates JSON full dump (GREEN T065)
- [ ] T069 [US5] Wire `tube-scout report content --professor <id> [--format html|xlsx|json|all]` CLI in `src/tube_scout/cli/report.py` — dispatch to `generate_v2_report`, output under `03_report/content/v2/{date}-{professor_id}-nc2.{ext}` (GREEN T065, quickstart §7)
- [ ] T070 [US5] Verify spec 002/004/006 existing reports unaffected — run a regression test ensuring `bundle_report.py` produces identical output for spec 007 inputs after spec 011 code lands (boundary B-4)

**Checkpoint**: All 5 user stories functional. quickstart.md §1-§13 executable end-to-end against fixture data.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: perf/scale validation, adversary tests, regression, security/error message audit, documentation.

- [ ] T071 [P] Implement adversary tests in `tests/adversary/test_reuse_v2_adversary.py` — malformed timestamps in caption JSON, empty pool (1-video professor), ASR-noise-corrupted segments, mixed Korean/English code-switching, ultra-long capture (90+ minute video), professor mapping with 0 captions collected (B-3 fail-fast), policy.yaml missing/invalid (exit 4 verified)
- [ ] T071a [P] Implement perf budget test `tests/perf/test_nc2_perf_budget.py` (SC-001) — fixture builder T003 generates 200-video professor pool with synthetic embeddings + captions; assert full nC2 scan (cosine cull → time-axis → 4-layer → composite score → persist) completes in < 30 minutes wall clock on a representative dev box; mark with `@pytest.mark.slow` so it can be opted in/out of CI
- [ ] T071b [P] Implement scale resume test `tests/perf/test_overnight_resume.py` (SC-006) — fixture builder T003 pre-populates a 4000-pair partially-completed run, simulate three independent crashes at random checkpoints, run scan with `--resume` after each crash, assert end state has all pairs completed exactly once (no duplicates), `pair_checkpoint.status='completed'`, total wall-clock for a single uninterrupted equivalent stays within an overnight (≤ 12 h) budget
- [ ] T071c [P] Implement composite-score correlation harness `tests/perf/test_expert_correlation.py` (SC-007) — placeholder that loads `tests/fixtures/spec011/expert_validation/labelled_100.json` (100 pairs with expert labels), computes Spearman/Pearson correlation between system suspicion_score and expert score, asserts ≥ 0.90 when fixture present. If fixture file is missing, `pytest.skip` with a message pointing to "post-launch calibration phase per spec.md Assumptions"; the fixture is built during the 2–4 week calibration window, not in dev — task wires the test scaffold so calibration drop-in is one PR
- [ ] T072 [P] Run quickstart.md §1-§13 against real fixture data — manual validation that each step's expected output matches; bug-fix any deviation by amending implementation tasks (no spec mutations)
- [ ] T073 [P] Audit every new error message against `contracts/cli_content.md` §11 table — ensure all messages are English, contain actionable next-step instruction, leak no internal paths or env var names (Constitution II + spec 011 boundary B-10)
- [ ] T074 Run full regression suite — `uv run pytest tests/` including all spec 007/008/009/010 tests; assert 0 regressions (SC-009, boundary B-2/B-4)
- [ ] T075 Run `uv run ruff check src/ tests/` — zero violations across new code; type-check via mypy if configured

---

## Post-Merge Actions (NOT part of dev checklist)

These are operator-side items handled after spec 011 PR merges. Do NOT include in dev acceptance gates.

- **Memory update**: append a one-line entry to `~/.claude/projects/-home-kjeong-localgit-tube-scout/memory/project_dev_status.md` — "spec 011 (자막 풀스택 nC2 + 시간축 + 4계층) merged YYYY-MM-DD".
- **Calibration window (2–4 weeks)**: build `tests/fixtures/spec011/expert_validation/labelled_100.json` from real operator FALSE_POSITIVE/CONFIRMED_DUPLICATE markings; once present, T071c stops skipping and SC-007 becomes a hard gate for v0.5 entry.
- **Policy doc finalization**: align `policy.yaml` defaults with the policy document negotiated with 교무과 + DX센터 + 학사 (idea/idea-2026-05-09-roadmap.md §7.4 PS-A-13/16) — spec 011 launches with conservative defaults; calibration adjusts in place.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T001-T004 all parallel.
- **Foundational (Phase 2)**: Depends on Setup. T005→T006 sequential. T007/T008/T009→T010/T011→T012/T013→T014/T015→T016/T017/T018 grouped per concern. **BLOCKS Phase 3-7**.
- **US1 (Phase 3, P1)**: Depends on Foundational. **MVP target**.
- **US2 (Phase 4, P1)**: Depends on Foundational + US1 services (CandidatePair → time-axis input).
- **US3 (Phase 5, P1)**: Depends on Foundational + US2 (Layer A needs I-6, Layer B operates on MatchSpan). Reuses spec 007 review_status for Layer D pair-level.
- **US4 (Phase 6, P2)**: Depends on Foundational + US3 (Layer D phrase-level uses `subtract_baseline` pattern).
- **US5 (Phase 7, P2)**: Depends on US1-US4 (consumes full DB schema).
- **Polish (Phase 8)**: Depends on US1-US5 complete.

### User Story Dependencies (Within Same Priority)

- US1 → US2 → US3 sequential (P1 chain) since each builds the next layer of pipeline output.
- US4 + US5 (P2) can proceed in parallel after US3 completes — different sub-systems (Layer D mutation flow vs reporting output).

### Within Each User Story

- All [P] tests in the same phase can run in parallel (different test files).
- Tests must be RED before implementation begins (Constitution Principle I).
- Models / pure utilities first → service-layer functions → CLI wiring → integration validation.
- Each Phase ends at a Checkpoint that is independently runnable.

### Parallel Opportunities

- Phase 1: T001 / T002 / T003 in parallel (T004 sequential after — verifies install).
- Phase 2: After T005-T006 (DB migration), T007-T018 split into 5 independent concerns — models / policy / lock / normalize / resolver — all parallelizable except wiring T017-T018.
- Phase 3 (US1): T019-T026 all parallel (different test files), T027-T029 parallel implementations, T030-T033 sequential (cli/content.py shared).
- Phase 4 (US2): T034-T036 parallel tests, T037-T040 split between `time_axis_indicators.py` (parallel) and `content_comparator.py` + `content_db.py` (sequential per file).
- Phase 5 (US3): T041-T046 parallel tests, T047/T048/T049 parallel impl (different files), T050-T053 sequential CLI wiring.
- Phase 6 (US4): T054-T057 parallel tests, T058 single file, T059-T062 sequential CLI wiring.
- Phase 7 (US5): T063-T065 parallel tests, T066/T067 parallel impl, T068-T070 sequential.
- Phase 8: T071/T072/T073 parallel; T074/T075 sequential gates; T076 documentation.

---

## Parallel Example: User Story 1 (P1 MVP)

```bash
# Launch all RED tests for US1 in parallel (different files):
Task: "Contract test for compare/scan mode options in tests/contract/test_cli_content_v2_contract.py"
Task: "Contract test for nc2 service signatures in tests/contract/test_service_layer_contract.py"
Task: "Unit test for nc2_matcher in tests/unit/test_nc2_matcher.py"
Task: "Unit test for pair_checkpoint in tests/unit/test_pair_checkpoint.py"
Task: "Integration test for nc2 basic flow in tests/integration/test_nc2_pipeline.py"
Task: "Integration test for cross-channel pool in tests/integration/test_cross_channel_pool.py"
Task: "Integration test for spec007 backward compat in tests/integration/test_spec007_compatibility.py"
Task: "Integration test for resume idempotency in tests/integration/test_resume_idempotent.py"

# Then GREEN parallel implementations (different files):
Task: "Implement nc2_matcher in src/tube_scout/services/nc2_matcher.py"
Task: "Implement pair_checkpoint in src/tube_scout/services/pair_checkpoint.py"

# Sequential CLI wiring (shared file src/tube_scout/cli/content.py):
Task: "Wire content scan --mode nc2 in src/tube_scout/cli/content.py"
Task: "Wire content compare --mode nc2 in src/tube_scout/cli/content.py"
Task: "Wire content professor commands in src/tube_scout/cli/content.py"
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Complete Phase 1 (Setup, 4 tasks).
2. Complete Phase 2 (Foundational, 14 tasks — DB schema + models + lock + normalize + resolver + CLI scaffold). **BLOCKS all stories**.
3. Complete Phase 3 (US1, 15 tasks — nC2 matching + cross-channel pool + spec 007 backward compat + resume).
4. **STOP and VALIDATE**: run quickstart.md §3-§6 + integration tests against synthetic fixture pool. Demo to operator.
5. Decision gate: ship MVP (5 indicators across nC2 pool only — already covers PS-U-2 cross-course detection at lower confidence) or proceed to US2 for full 8-indicator capability.

### Incremental Delivery (recommended path)

1. **MVP**: Setup + Foundational + US1 → demo cross-course detection with 5 indicators.
2. **+ US2** (8 tasks): full I-6/I-7/I-8 — pattern classification becomes meaningful.
3. **+ US3** (13 tasks): false-positive defense — operator review burden manageable.
4. **+ US4** (9 tasks): whitelist accumulation — recurring stylistic FP eliminated.
5. **+ US5** (8 tasks): operator-facing reports for 교무 회의.
6. **+ Polish** (6 tasks): adversary, regression, audit, docs.

### Parallel Team Strategy

- **Solo developer (default)**: sequential US1 → US2 → US3 → US4 → US5 → Polish. Tests-first per task.
- **2-developer team**: After Phase 2 complete, Dev A on US1 → US2 → US3 (P1 chain), Dev B on test-infrastructure + US4/US5 prep + Polish in parallel after US3 completes.

---

## Notes

- Constitution Principle I (TDD, NON-NEGOTIABLE): every implementation task has a preceding test task in this list. Implementation tasks are GREEN of stated test IDs.
- Constitution Principle VII (Cross-Spec Boundaries): boundaries B-1~B-10 from spec.md are exercised by integration tests T024 (B-1), T025 (B-2), T071 caption-missing case (B-3), T070 (B-4), T020+T045+T054 contract tests (B-5/B-8), professor_resolver impl (B-6), report output path (B-7), no-secret review (B-9), error message audit T073 (B-10).
- Each US phase ends at a Checkpoint allowing independent demo. MVP = Phase 1 + 2 + 3 (33 tasks ≈ 1.5–2 weeks dev-squad).
- Total task count: **76 tasks**.
- Tests-only commits in early phases are acceptable (RED state) — Constitution Principle I requires tests to fail before GREEN, not skipped.
- All file paths are absolute repo-relative; LLM-executable without further context.
- `[P]` markers are conservative — same-file edits never marked [P] even if logically independent.
