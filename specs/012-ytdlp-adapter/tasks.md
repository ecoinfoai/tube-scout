---
description: "Task list for spec 012 (yt-dlp 자막·음원·지문 어댑터)"
---

# Tasks: yt-dlp 자막·음원·지문 어댑터

**Input**: Design documents from `/specs/012-ytdlp-adapter/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅
**Tests**: REQUIRED (Constitution I — TDD NON-NEGOTIABLE — 모든 user story 에 RED-first test task 포함)
**Organization**: 6 phase (Setup → Foundational → US1 → US2 → US3 → Polish), 총 49 task

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Maps task to user story (US1/US2/US3) for traceability
- All paths are absolute or repo-relative.

## Path Conventions

- Source: `src/tube_scout/{services,cli,storage,models}/`
- Tests: `tests/{unit,contract,integration}/`
- Docs: `specs/012-ytdlp-adapter/` (this feature dir)
- Build: `flake.nix`, `pyproject.toml` (repo root)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 의존성 + Nix devShell + repo 위생 — TDD 진입 전 환경 검증.

- [ ] T001 Add `yt-dlp = ">=2026.03.17"` and `pyacoustid = ">=1.3.0"` to `pyproject.toml` `[project] dependencies` section, run `uv lock` to update `uv.lock`
- [ ] T002 [P] Patch `flake.nix` `devShells.default.buildInputs` to add 5 packages (`yt-dlp`, `chromaprint`, `ffmpeg`, `zlib`, `stdenv.cc.cc.lib`) and `shellHook` to export `LD_LIBRARY_PATH`. **Nix string escape 주의**: `shellHook = '' export LD_LIBRARY_PATH="${pkgs.chromaprint}/lib:${pkgs.zlib}/lib:${pkgs.stdenv.cc.cc.lib}/lib:''${LD_LIBRARY_PATH}"; '';` — `''$` 는 Nix multi-line string 에서 shell `$` 보존을 위한 escape (eager Nix evaluation 방지). Verify with `nix develop -c bash -c 'fpcalc -version && yt-dlp --version && echo "$LD_LIBRARY_PATH" | grep chromaprint'` (R-10)
- [ ] T003 [P] Add `.gitignore` entries: `cookies.txt`, `**/cookies*.txt`, `_workspace/spike/*.mp3`, `projects/*/01_collect/audio_temp/` to prevent secret leakage and audio file commits (Constitution VI)
- [ ] T004 [P] Verify `services/fingerprint.py` (text SHA — spec 011) exists untouched; create empty `src/tube_scout/services/audio_fingerprint.py` placeholder to lock module name (B-X1-9 collision prevention)
- [ ] T005 [P] Create empty placeholder files for new test modules: `tests/unit/test_srv3_parser.py`, `tests/unit/test_audio_fingerprint.py`, `tests/unit/test_ytdlp_adapter.py`, `tests/contract/test_ytdlp_adapter_contract.py` — ensures `pytest --collect-only` discovers them

**Checkpoint**: `nix develop -c uv run pytest --collect-only` finds new test files (currently empty), `nix develop -c bash -c 'yt-dlp --version && fpcalc -version'` succeeds.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Exception types + cookies resolver + DB v3 migration + audit CSV writer — 모든 US 가 의존하는 공통 인프라.

**⚠️ CRITICAL**: User stories(P1/P2/P3)는 본 phase 완료 전 시작 금지.

### Exception types (Constitution II — Fail-Fast)

- [ ] T006 [TEST] Write `tests/unit/test_ytdlp_errors.py` with 8 test cases (one per exception type — `YtdlpAuthError`, `YtdlpRateLimitError`, `YtdlpNetworkError`, `YtdlpLiveStreamError`, `YtdlpAudioDecodeError`, `CookiesSourceError`, `FingerprintExtractError`, `AudioTooShortError`) verifying English actionable message format per `contracts/ytdlp_adapter_contract.md` "Error pattern catalog" — **MUST FAIL** (RED)
- [ ] T007 Implement 8 exception classes in `src/tube_scout/services/ytdlp_errors.py` extending `Exception`, each with class-level docstring + `__init__(self, message: str, **context)` — make T006 PASS (GREEN)

### Cookies source resolver (FR-017, B-X1-6, R-6)

- [ ] T008 [P] [TEST] Write `tests/unit/test_resolve_cookies_source.py` with 5 scenarios (CLI flag > env var > default browser > implicit file fallback > all-fail actionable raise) per `contracts/ytdlp_adapter_contract.md::resolve_cookies_source` — **MUST FAIL** (RED)
- [ ] T009 Implement `resolve_cookies_source()` and `CookiesSource` dataclass in `src/tube_scout/services/ytdlp_adapter.py` (5-step resolution chain, 0600 perms validation, raises `CookiesSourceError` on all-fail) — make T008 PASS (GREEN)

### Audit CSV writer (FR-015, B-X1-7, R-11)

- [ ] T010 [P] [TEST] Write `tests/unit/test_audit_csv_writer.py` with 6 scenarios (header creation on first append / append no header on subsequent / column sequence frozen for transcripts / column sequence frozen for fingerprint / atomic write / concurrent append safe) — **MUST FAIL** (RED)
- [ ] T011 Implement `AuditWriter` class in `src/tube_scout/services/audit_writer.py` with `append_transcript_row()` and `append_fingerprint_row()` methods, atomic CSV write via `_csv_append_atomic(path, row, fieldnames)` helper — make T010 PASS (GREEN)

### Database v3 migration (FR-012, B-X1-2, R-8)

- [ ] T012 [P] [TEST] Write `tests/unit/test_content_db_v3.py` with 5 scenarios (empty DB → v2 → v3 / v2 row preservation / idempotent re-run / audio_fingerprint INSERT/SELECT / FK CASCADE on videos delete) per `data-model.md::E-3` DDL — **MUST FAIL** (RED)
- [ ] T013 Add `migrate_to_v3(db_path: Path) -> None` and `insert_audio_fingerprint(...)`, `get_audio_fingerprint(video_id)`, `audio_fingerprint_exists(video_id)` functions to `src/tube_scout/storage/content_db.py` (DDL: `audio_fingerprint` table + index + `PRAGMA user_version = 3`, idempotent via `CREATE TABLE IF NOT EXISTS`) — make T012 PASS (GREEN)

### Contract test scaffolding

- [ ] T014 [P] [TEST] Write `tests/contract/test_ytdlp_adapter_contract.py` validating 4 public function signatures (`fetch_caption_via_ytdlp`, `fetch_audio_via_ytdlp`, `resolve_cookies_source`, `extract_chromaprint_fingerprint`) match `contracts/ytdlp_adapter_contract.md` and `contracts/audio_fingerprint_contract.md` (use `inspect.signature()` to compare) — **MUST FAIL** (RED — functions not implemented)

**Checkpoint**: 4 foundational pieces (errors, cookies resolver, audit writer, DB v3) green. Contract scaffolding RED until US1/US2 implementations land.

---

## Phase 3: User Story 1 — 22채널 ASR 자막 백필 (Priority: P1) 🎯 MVP

**Goal**: 운영자가 `tube-scout collect transcripts --source ytdlp --channel <alias>` 또는 `--all-channels` 로 자교 22채널 일부공개·비공개 영상 자막을 quota 0 으로 백필. 결과는 spec 010 transcript JSON 형식으로 영속.

**Independent Test**: spike fixture srv3 1개 입력 → spec 010 호환 JSON 1개 출력. 시뮬레이트 채널(spec 003 mock alias) 흐름에서 22채널 isolation + idempotent skip 검증. Data API quota 사용 0 unit (network mock 으로 검증).

### Tests for User Story 1 ⚠️ RED-first 의무

- [ ] T015 [P] [US1] [TEST] Write `tests/unit/test_srv3_parser.py` with 7 scenarios (manual srv3 / `<p a="1">` skip / empty `<p>` skip / `<p>` direct text / empty `<body>` raises / malformed XML raises / UTF-8 한글 보존) per `contracts/srv3_parser_contract.md` using spike fixture `_workspace/spike/ytdlp-fixtures/tuxscjwiJYs.ko.srv3` (copy from `/tmp/spike-ytdlp/` first if needed) — **MUST FAIL** (RED)
- [ ] T016 [P] [US1] [TEST] Add 4 scenarios for `pick_priority_track()` (both → manual / only auto / only manual / both None) to `tests/unit/test_srv3_parser.py` — **MUST FAIL** (RED)
- [ ] T017 [P] [US1] [TEST] Write `tests/unit/test_ytdlp_adapter_caption.py` with 5 scenarios (`fetch_caption_via_ytdlp` returns (manual, None) when manual track present / returns (None, auto) when only auto / returns (None, None) when no captions / raises `YtdlpAuthError` on cookies fail / raises `YtdlpRateLimitError` after 3 backoffs) using `subprocess.run` mock — **MUST FAIL** (RED)
- [ ] T018 [P] [US1] [TEST] Write `tests/unit/test_collect_transcripts_cli.py` with 6 scenarios (default source api / env var TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE=ytdlp / flag overrides env / `--channel` exclusive with `--all-channels` / unregistered alias rejected exit 5 / `--force` overwrite) per `contracts/cli_contract.md` — **MUST FAIL** (RED)
- [ ] T019 [US1] [TEST] Write `tests/integration/test_ytdlp_caption_flow.py` end-to-end (yt-dlp subprocess mock returns spike-fixture srv3 → adapter → srv3_parser → JSON write atomic → audit CSV append → idempotent re-run skip) — **MUST FAIL** (RED)
- [ ] T020 [P] [US1] [TEST] Write `tests/integration/test_boundary_spec_010_compat.py` verifying B-X1-1 — generated `transcripts/{vid}.json` consumed by `services/captions_api.py` or spec 011 pipeline (`services/segmenter.py` if applicable) without conversion (load JSON + `pydantic.parse_obj_as` against spec 010 model) — **MUST FAIL** (RED)

### Implementation for User Story 1

- [ ] T021 [P] [US1] Implement `srv3_to_transcript_json()` and `pick_priority_track()` in `src/tube_scout/services/srv3_parser.py` per `contracts/srv3_parser_contract.md` (XML.etree parsing, `<p a="1">` skip, `<s>` text concat) — make T015+T016 PASS (GREEN)
- [ ] T022 [US1] Implement `fetch_caption_via_ytdlp()` in `src/tube_scout/services/ytdlp_adapter.py` per `contracts/ytdlp_adapter_contract.md` (subprocess yt-dlp with `--write-subs --write-auto-subs --sub-format srv3`, sleep, exponential backoff on 429, raises 4 exception types) — make T017 PASS (GREEN, depends T009 cookies resolver)
- [ ] T023 [US1] Extend `src/tube_scout/cli/collect.py` `transcripts` subcommand: add `--source {api|ytdlp}` flag with env var precedence (`TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE` → `api`), add `--channel` / `--all-channels` mutual exclusion, dispatch to `fetch_caption_via_ytdlp` + `srv3_to_transcript_json` + `AuditWriter.append_transcript_row` when source=ytdlp — make T018 PASS (GREEN, depends T011 + T021 + T022)
- [ ] T024 [US1] Wire `--all-channels` to alias resolver `src/tube_scout/services/auth.py:resolve_channel_alias()` (spec 009 FR-006) + registry loader `services/auth.py:load_registry()` to enumerate all registered aliases. Per-channel try/except isolation (FR-016) — make T018 (`--all-channels` scenario) PASS (GREEN)
- [ ] T025 [US1] Implement idempotent skip-existing logic in `src/tube_scout/cli/collect.py::transcripts` (check transcripts/{vid}.json existence before yt-dlp call, skip + audit unless `--force`) — make T019 PASS (GREEN)
- [ ] T026 [US1] Verify B-X1-1 compatibility — make T020 PASS (GREEN, may need pydantic model adjustment in spec 010 area; if model rejection, document in plan §Complexity Tracking and propose minimal patch)

**Checkpoint**: User Story 1 fully functional — `tube-scout collect transcripts --source ytdlp --channel <alias>` produces spec 010 compatible JSON, audit CSV row, network calls 0 to Data API. **MVP boundary complete**.

---

## Phase 4: User Story 2 — 음향 지문 영속화 (Priority: P2)

**Goal**: 운영자가 `tube-scout collect fingerprint --channel <alias>` 또는 `--all-channels` 로 채널 전체 영상(30s 미만 제외)에 대해 음원 추출 → chromaprint 지문 산출 → SQLite v3 영속 → 음원 즉시 삭제 lifecycle 을 일괄 실행. spec Y(미래) 입력 형식 동결.

**Independent Test**: spike fixture mp3 1개 입력 → fpcalc subprocess → DB INSERT → 음원 unlink → DB SELECT 결과 검증. self-hamming = 0 + V1↔V2 spike 측정값 일치(±1%).

### Tests for User Story 2 ⚠️ RED-first 의무

- [ ] T027 [P] [US2] [TEST] Write `tests/unit/test_audio_fingerprint.py` with 9 scenarios (`extract_chromaprint_fingerprint` from spike mp3 / `AudioTooShortError` for <30s / `FingerprintExtractError` on fpcalc fail / malformed stdout / `decode_fingerprint_to_array` shape+dtype / hamming self=0 / hamming shifted ~14.5 / `best_alignment_hamming` self / `best_alignment_hamming` V1↔V2 spike fixture) per `contracts/audio_fingerprint_contract.md` — **MUST FAIL** (RED)
- [ ] T028 [P] [US2] [TEST] Write `tests/unit/test_ytdlp_adapter_audio.py` with 4 scenarios (`fetch_audio_via_ytdlp` postprocessor-args has `ffmpeg:` prefix / 22050Hz mono mp3 returned / `YtdlpAudioDecodeError` on ffmpeg fail / cookies fallback works) per `contracts/ytdlp_adapter_contract.md` — **MUST FAIL** (RED)
- [ ] T029 [US2] [TEST] Write `tests/integration/test_audio_fingerprint_flow.py` with 4 scenarios (full lifecycle extract→fingerprint→DB→delete / 30s 미만 skip / idempotent skip / `--force` overwrite UPDATE) — **MUST FAIL** (RED)
- [ ] T030 [P] [US2] [TEST] Write `tests/unit/test_collect_audio_fingerprint_cli.py` with 5 scenarios (`collect audio --channel` / `collect fingerprint --channel` 별칭 동등성 / `--all-channels` / `--force` flag / SIGINT handler triggers temp cleanup) per `contracts/cli_contract.md` — **MUST FAIL** (RED)
- [ ] T031 [P] [US2] [TEST] Write `tests/integration/test_audio_temp_cleanup.py` verifying SC-004 invariant — after 5-video processing, `audio_temp/` directory is empty (lifecycle correctness) — **MUST FAIL** (RED)
- [ ] T032 [P] [US2] [TEST] Write `tests/integration/test_boundary_spec_011_db.py` verifying B-X1-2 — v2 schema (videos / matches tables) row counts unchanged after migrate_to_v3() + audio_fingerprint inserts — **MUST FAIL** (RED)

### Implementation for User Story 2

- [ ] T033 [P] [US2] Implement `extract_chromaprint_fingerprint()`, `decode_fingerprint_to_array()`, `hamming_distance_per_int()`, `best_alignment_hamming()`, `_parse_fpcalc_stdout()` in `src/tube_scout/services/audio_fingerprint.py` per `contracts/audio_fingerprint_contract.md` (subprocess fpcalc, regex parse, lazy import chromaprint+numpy, raises `FingerprintExtractError`/`AudioTooShortError`) — make T027 PASS (GREEN)
- [ ] T034 [US2] Implement `fetch_audio_via_ytdlp()` in `src/tube_scout/services/ytdlp_adapter.py` (subprocess yt-dlp with `--extract-audio --audio-format mp3 --audio-quality 128K --postprocessor-args "ffmpeg:-ar 22050 -ac 1"`, sleep, raises `YtdlpAudioDecodeError`) — make T028 PASS (GREEN)
- [ ] T035 [US2] Add `tube-scout collect audio` and `tube-scout collect fingerprint` (alias) Typer subcommands to `src/tube_scout/cli/collect.py` per `contracts/cli_contract.md`, dispatching: alias-resolve → fetch_audio_via_ytdlp → extract_chromaprint_fingerprint → insert_audio_fingerprint → unlink → AuditWriter.append_fingerprint_row — make T030 PASS (GREEN, depends T033 + T034 + T013 + T011)
- [ ] T036 [US2] Implement audio_temp lifecycle policy in `src/tube_scout/cli/collect.py` (try/finally with `audio_path.unlink(missing_ok=True)` + start-of-command cleanup of stale `audio_temp/*.mp3` from interrupted prior runs) — make T031 PASS (GREEN)
- [ ] T037 [US2] Wire idempotent skip via `audio_fingerprint_exists(video_id)` check + `--force` override before yt-dlp call — make T029 PASS (GREEN)
- [ ] T038 [US2] Verify B-X1-2 — make T032 PASS (GREEN; if v2 row touched, root-cause + fix)

**Checkpoint**: User Story 2 fully functional — `tube-scout collect fingerprint --channel <alias>` produces audio_fingerprint DB rows, audit CSV, audio_temp/ empty after run. spec Y read-only consume schema 동결.

---

## Phase 5: User Story 3 — 자교 채널 ToS 준수 + 음원 영구 보관 0 (Priority: P3)

**Goal**: alias resolver를 거치지 않은 채널 ID/URL 은 yt-dlp 호출 0 건으로 거절(FR-019, SC-008), SIGINT/SIGTERM 시 임시 음원 best-effort 정리(FR-020), audit CSV 가 운영자 컴플라이언스 검증을 가능케 함(FR-015).

**Independent Test**: `tube-scout collect transcripts --source ytdlp --channel <unregistered>` exit 5 + tcpdump으로 yt-dlp 네트워크 호출 0건 검증. SIGINT mid-run 시 audio_temp 잔재 0건 + audit "interrupted" 항목.

### Tests for User Story 3 ⚠️ RED-first 의무

- [ ] T039 [P] [US3] [TEST] Write `tests/integration/test_external_channel_reject.py` with 3 scenarios (unregistered alias / direct video URL bypass / `--all-channels` with empty registry) — verify exit code 5 + `subprocess.run` 가 yt-dlp 호출 0건(mock spy) — **MUST FAIL** (RED)
- [ ] T040 [P] [US3] [TEST] Write `tests/integration/test_signal_handler_cleanup.py` — SIGINT mid-run, verify audio_temp/ 잔재 0 + audit "interrupted" row 추가 + exit 130 — **MUST FAIL** (RED)
- [ ] T041 [P] [US3] [TEST] Write `tests/integration/test_audit_csv_compliance.py` — produced audit CSV columns sequence 매칭 `data-model.md::E-5` (transcripts: 6컬럼 / fingerprint: 6컬럼 정확 동결), append-only 검증 — **MUST FAIL** (RED)

### Implementation for User Story 3

- [ ] T042 [US3] Add alias resolver gate at top of all 3 collect subcommands (`transcripts`, `audio`, `fingerprint`) in `src/tube_scout/cli/collect.py` — call `resolve_alias_to_channel_id(alias)` (spec 003) before any yt-dlp/network call, raise + exit 5 on failure with actionable message — make T039 PASS (GREEN)
- [ ] T043 [US3] Implement signal handler in `src/tube_scout/cli/collect.py` (signal.signal SIGINT/SIGTERM → cleanup `audio_temp/*.mp3` with `unlink(missing_ok=True)` + audit "interrupted" row for in-progress video + exit 130/143) — make T040 PASS (GREEN)
- [ ] T044 [US3] Verification only — confirm `services/audit_writer.py` (created at T011) uses module-level frozen `TRANSCRIPTS_FIELDNAMES` and `FINGERPRINT_FIELDNAMES` constants (sequences already locked at Phase 2). T041 test asserts column equality against these constants — make T041 PASS (GREEN). NO new code in this task; if T011 missed the constant pattern, file a bug back to T011 instead of patching here.

**Checkpoint**: All 3 user stories independently functional. Constitution V (영속 0) + PS-A-12 (외부 채널 OUT) 코드 보장. spec X1 dev complete pending Polish phase.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 통합 검증, agenix 호환, 문서 동기화, version bump.

### Cross-Spec Boundary integration test (Constitution VII)

- [ ] T045 [P] [TEST] Write `tests/integration/test_cross_spec_boundary.py` covering B-X1-1~9 in single test file — 9 test functions, each verifies one boundary per spec.md §Cross-Spec Boundaries. Specifically `test_b_x1_9_text_audio_fingerprint_modules_isolated` MUST import both `services/fingerprint.py` (text SHA — spec 011) and `services/audio_fingerprint.py` (this spec) in same process, call sample functions from each, and assert no class/function name collision (Python `inspect.getmembers()` cross-check). — **MUST FAIL initially**, then pass as US1/US2/US3 implementations land

### Performance + adversary + auditor (dev-squad parallel agents)

- [ ] T046 [P] [TEST] Write `tests/integration/test_ytdlp_rate_limit.py` with `@pytest.mark.slow` decorator and 50-URL × 30s sleep sequence (production validation, opt-in via `pytest -m slow`) — verify 0 HTTP 429 occurrences after rate limit defaults (R-7)
- [ ] T046a [P] [TEST] Write `tests/integration/test_perf_bench.py::test_single_video_under_60s` with `@pytest.mark.slow` — measure end-to-end wall-clock for 1 spike-fixture video (caption + audio + fingerprint + DB persist, sleep mocked to 0) — assert ≤ 60s. Verifies SC-005 buildable component (sleep 30~60s 제외한 순수 wall-clock)
- [ ] T047 [P] adversary 매트릭스 — `_workspace/adversary/spec-012/ytdlp_attack_scenarios.md` 작성 (10+ persona: malicious cookies file path / SQL injection in alias / yt-dlp command injection / rate limit floor / disk-full mid-extraction / SIGTERM stress / Brave SQLite WAL race / cookies file race / external URL bypass / signal storm) → 각 시나리오 통합 테스트 1개 추가 in `tests/integration/test_adversary_*.py`
- [ ] T048 [P] auditor 전수검사 — security review (Constitution VI), type annotation coverage (`mypy --strict src/tube_scout/services/ytdlp_adapter.py`, `mypy src/tube_scout/services/srv3_parser.py`, `mypy src/tube_scout/services/audio_fingerprint.py`), Google docstring presence — 보고서 `_workspace/audit/spec-012-audit.md`

### Documentation sync

- [ ] T049 [P] Update `specs/012-ytdlp-adapter/quickstart.md` if implementation drift; verify operator self-audit checklist (6 invariants) all pass after run
- [ ] T050 [P] Update root `CLAUDE.md` "Recent Changes" entry summarizing spec X1 (audio_fingerprint table v3 + yt-dlp adapter + 3 new CLI subcommands); add to "Active Technologies" if not already added by `update-agent-context.sh`
- [ ] T051 [P] Run `ruff check . && ruff format --check .` clean; fix any offences

### Release

- [ ] T052 Bump version `pyproject.toml` `[project] version = "0.4.0"` (clarify Q decision 2026-05-09); update `CHANGELOG.md` if exists; prepare git tag `v0.4.0` annotation message (실제 tag 는 master merge 후 운영자 수동)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies, immediate start.
- **Phase 2 (Foundational)**: Depends on Phase 1 completion. **BLOCKS** Phase 3/4/5.
- **Phase 3 (US1) / Phase 4 (US2) / Phase 5 (US3)**: All depend on Phase 2. After Phase 2 complete, three phases can run in **parallel** (separate developers/agents).
- **Phase 6 (Polish)**: Depends on Phase 3+4+5 completion (T045 통합 검증은 모든 US 완료 시 final pass).

### Critical-path within each story

- **US1 (P1)**: T015~T020 (RED tests parallel) → T021 (srv3_parser, blocks integration) → T022 (ytdlp_adapter caption) → T023 (CLI extend) → T024+T025+T026 (sequential CLI logic).
- **US2 (P2)**: T027~T032 (RED parallel) → T033 (audio_fingerprint module) → T034 (ytdlp_adapter audio) → T035 (CLI subcommands) → T036+T037+T038 (lifecycle/idempotent/boundary).
- **US3 (P3)**: T039~T041 (RED parallel) → T042 (alias gate) → T043 (signal handler) → T044 (audit columns).

### Parallel opportunities

- **Phase 1**: T002+T003+T004+T005 all `[P]` (different files), parallel with T001.
- **Phase 2**: After T007 lands errors, T008/T010/T012/T014 all `[P]` (different test files); T009/T011/T013 implementations parallelize after RED tests.
- **Phase 3 (US1)**: T015+T016+T017+T018+T020 all `[P]` (different test files); T021 parallel with T022 only after T015+T016 land + ytdlp_errors (T007) ready.
- **Phase 4 (US2)**: T027+T028+T030+T031+T032 all `[P]`; T033+T034 parallel after RED tests (different files).
- **Phase 5 (US3)**: T039+T040+T041 all `[P]`.
- **Phase 6**: T045+T046+T047+T048+T049+T050+T051 all `[P]` (different files / non-overlapping concerns).

### dev-squad team parallel strategy

After Phase 2 checkpoint, spawn dev-squad full team (`feedback_devsquad_full_team`):
- **developer-1** → US1 (P1, MVP) — T015~T026
- **developer-2** → US2 (P2) — T027~T038
- **developer-3** → US3 (P3) — T039~T044
- **pair-programmer** → boundary verification continuous (B-X1-1~9 trace as US1/US2 land)
- **adversary** → T047 매트릭스 작성 (parallel with developers)
- **auditor** → T048 (parallel, gate at Phase 6)

---

## Parallel Example: User Story 1 RED-first burst

```bash
# RED-first batch (write failing tests in parallel):
Task: "Write tests/unit/test_srv3_parser.py 7 scenarios (T015)"
Task: "Add tests/unit/test_srv3_parser.py 4 pick_priority scenarios (T016)"
Task: "Write tests/unit/test_ytdlp_adapter_caption.py 5 scenarios (T017)"
Task: "Write tests/unit/test_collect_transcripts_cli.py 6 scenarios (T018)"
Task: "Write tests/integration/test_boundary_spec_010_compat.py (T020)"

# pytest -k "test_srv3_parser or test_ytdlp_adapter_caption or test_collect_transcripts_cli or boundary_spec_010" → ALL FAIL (RED) ✓

# GREEN burst (implementations after RED locked):
Task: "Implement srv3_to_transcript_json + pick_priority_track in services/srv3_parser.py (T021)"
Task: "Implement fetch_caption_via_ytdlp in services/ytdlp_adapter.py (T022)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup (T001~T005) — environment ready.
2. Phase 2 Foundational (T006~T014) — exception types + cookies + audit + DB v3 ready.
3. Phase 3 US1 (T015~T026) — caption backfill working.
4. **STOP & VALIDATE**: 1 채널 dry-run (운영자 확인) — 22채널 백필 시간 / spec 010 호환 / quota 0 검증.
5. Deploy/demo MVP if ready (선택).

### Incremental Delivery (권장)

1. MVP (US1) → 운영자 1주일 dry-run + audit CSV 검증.
2. US2 음향 지문 → 운영자가 1 채널 fingerprint 검증 → spec Y 입력 형식 동결.
3. US3 ToS + 영구 보관 0 → adversary 매트릭스 통과.
4. Polish → v0.4.0 release.

### Parallel Team Strategy (dev-squad)

Phase 2 완료 직후 dev-squad 전원 spawn (Constitution: `feedback_devsquad_full_team` 정책):
- 3 developers parallel on US1/US2/US3
- pair-programmer boundary tracing throughout
- adversary 매트릭스 in parallel
- auditor 최종 게이트 Phase 6

---

## Notes

- **TDD NON-NEGOTIABLE** (Constitution I): 모든 implementation task 는 paired RED test task 가 먼저 commit 되어야 시작 가능. RED → GREEN → REFACTOR per task.
- **[P] tasks**: 다른 파일, 의존성 없음. 한 파일 동시 수정 금지.
- **[Story] label** US1/US2/US3 traceability: `git log --grep "US1"` 으로 backlog 추적 가능.
- **Constitution VII** (Cross-Spec Boundaries): T020 (B-X1-1) + T032 (B-X1-2) + T045 (B-X1-1~9 통합) 가 boundary test 1차 방어선.
- **`fix one issue per commit`** (`feedback_adv_fix_one_per_commit`): adversary P1 픽스는 commit 분리.
- **Commit convention**: `feat(spec012): ...`, `test(spec012): ...`, `fix(spec012): ...`, `docs(spec012): ...`. 세부 [TXXX] 태스크 ID를 commit body 에 포함 (`T015 GREEN`, `T015+T016 RED-first` 등).
- **dev-squad spawn 순서**: Phase 2 checkpoint 통과 → 6 agents 동시 spawn (developer×3 + pair-programmer + adversary + auditor) — 메모리 `feedback_devsquad_full_team` 정책.
- **Spike fixture 활용**: `_workspace/spike/ytdlp-fixtures/` 디렉터리에 spike 산출물 srv3 + mp3 + fp_test*.txt 복사하여 unit test fixture 로 활용. T015/T027 test 작성 시 이 경로 가정.
