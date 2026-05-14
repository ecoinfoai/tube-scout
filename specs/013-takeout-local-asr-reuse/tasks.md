---
description: "Task list for spec 013 — Takeout 기반 로컬 ASR + 강의 영상 재사용 판정 + 자막 KB Export"
---

# Tasks: Takeout 기반 로컬 ASR + 강의 영상 재사용 판정 + 자막 KB Export

**Branch**: `013-takeout-local-asr-reuse`
**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Data Model**: [data-model.md](./data-model.md) · **Research**: [research.md](./research.md) · **Quickstart**: [quickstart.md](./quickstart.md)
**Tests**: REQUIRED (Constitution I — TDD NON-NEGOTIABLE).
**Organization**: 6 phases (Setup → Foundational → US1 → US2 → US3 → Polish). idea 문서의 "Phase 1~4" 명명과 본 tasks.md phase 번호 대응: idea Phase 1 (Takeout/audio/fingerprint) = tasks Phase 3.1+3.2 / idea Phase 2 (ASR+Normalizer) = tasks Phase 3.3 / idea Phase 3 (분석+보고서) = tasks Phase 3.4+3.5 / idea Phase 4 (yt-dlp 삭제 + KB export) = tasks Phase 4 (US2) + Phase 5 (US3). plan.md §Cross-Spec Boundaries B-8이 idea Phase 4를 참조하면 tasks Phase 5 (US3, T087-T095)와 동일.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 다른 파일·독립 task → 병렬 가능.
- **[Story]**: US1=per-professor M-nC2 reuse report (P1), US2=KB transcript export (P2), US3=yt-dlp legacy removal (P3).
- Setup/Foundational/Polish tasks는 Story 라벨 없음.

## Path Conventions

- 소스: `src/tube_scout/{cli,services,storage,models,reporting,visualization}/`
- 테스트: `tests/{contract,unit,integration,perf,adversary,fixtures}/`
- 측정 산출물: `_workspace/measurement/`
- 모든 경로는 repo root 기준 상대.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 신규 의존성 추가 + devShell 보강. 모든 후속 phase의 import 성공을 보장.

- [ ] T001 Add `faster-whisper>=1.0.0,<2.0.0` to `pyproject.toml` `[project.optional-dependencies]` as new `asr` extra; also append to `all` aggregate. Touch only `pyproject.toml`.
- [ ] T002 Add `cudnn`, `cuda-nvrtc` to `flake.nix` devShell `buildInputs`. Touch only `flake.nix`.
- [ ] T003 [P] Update `CLAUDE.md` §Install Profiles table — add `asr` profile row (`uv sync --extra asr` → `+ faster-whisper (~1.5 GB int8 quantized weights via huggingface-hub)`). Touch only `CLAUDE.md`.
- [ ] T004 Run `uv sync --extra asr --extra dev` in devShell + create `tests/contract/test_devshell_asr_import.py` that asserts `from faster_whisper import WhisperModel` import succeeds. Phase 1 smoke test.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: v4 migration + audit_writer 일반화 + progress reporter + Pydantic 모델 확장 + 공통 fixture. 본 phase 미완 상태에서는 어느 user story도 진행 불가.

**⚠️ CRITICAL**: 모든 user story가 본 phase 산출에 의존.

### 2.1 SQLite v4 Migration

- [ ] T005 [P] Write RED contract test `tests/contract/test_v4_migration_contract.py` — `test_migrate_to_v4_signature_matches_contract`, `test_migrate_raises_when_version_below_3`. Per `contracts/v4_migration_contract.md`.
- [ ] T006 [P] Write RED unit test `tests/unit/test_add_column_if_missing.py` — `test_adds_column_when_missing`, `test_no_op_when_column_exists`, `test_returns_correct_boolean`.
- [ ] T007 [P] Write RED integration test `tests/integration/test_v4_migration.py` — `test_migrate_v3_to_v4_creates_two_new_tables`, `test_migrate_v3_to_v4_adds_7_columns`, `test_migrate_v3_to_v4_preserves_existing_rows`, `test_migrate_idempotent_two_calls`, `test_pragma_user_version_set_to_4`.
- [ ] T008 [P] Write RED integration test `tests/integration/test_v4_auto_ensure.py` — `test_ensure_v4_auto_migrates_from_v3`, `test_ensure_v4_noop_on_v4`, `test_ensure_v4_raises_on_v2`.
- [ ] T009 Implement `_add_column_if_missing` helper + `migrate_to_v4(db_path)` + `_ensure_v4(db_path)` in `src/tube_scout/storage/content_db.py`. Add `_V4_SCHEMA_SQL` constant with `channel_metadata` + `video_metadata` CREATE TABLE. Touch only `src/tube_scout/storage/content_db.py`. Make T005-T008 pass.

### 2.2 Pydantic 모델 확장

- [ ] T010 [P] Write RED unit test `tests/unit/test_processing_status_v4_enum.py` — `test_valid_processing_statuses_includes_asr_in_progress`, `test_valid_processing_statuses_includes_asr_failed`, `test_valid_match_confidences_3_values`.
- [ ] T011 [P] Write RED unit test `tests/unit/test_asr_quality_flags_model.py` — `test_asr_quality_flags_defaults_to_safe_values`, `test_asr_quality_flags_serializes_to_json`, `test_asr_quality_flags_accepts_extra_keys` (extensible schema).
- [ ] T012 [P] Write RED unit test `tests/unit/test_channel_video_metadata_models.py` — `test_channel_metadata_round_trip_json`, `test_video_metadata_match_confidence_literal`, `test_video_metadata_privacy_status_literal`.
- [ ] T013 [P] Write RED unit test `tests/unit/test_reuse_pattern_label_v4.py` — `test_re_recorded_same_content_label_exists`, `test_tail_update_label_exists`, `test_existing_4_patterns_still_present`.
- [ ] T014 Implement enum extension + `ChannelMetadata` + `VideoMetadata` + `AsrQualityFlags` Pydantic models in `src/tube_scout/models/content.py`. Add `VALID_MATCH_CONFIDENCES = frozenset({"high", "medium", "ambiguous"})`. Touch only `src/tube_scout/models/content.py`. Make T010-T012 pass.
- [ ] T015 Add `RE_RECORDED_SAME_CONTENT` + `TAIL_UPDATE` to `ReusePatternLabel` StrEnum in `src/tube_scout/models/reuse_v2.py`. Touch only `src/tube_scout/models/reuse_v2.py`. Make T013 pass.

### 2.3 audit_writer 8-stage 일반화

- [ ] T016 [P] Write RED contract test `tests/contract/test_audit_writer_v2_contract.py` — `test_stage_fieldnames_has_8_entries`, `test_append_row_rejects_unknown_stage`, `test_append_row_rejects_invalid_result`, `test_append_row_drops_extra_keys`, `test_append_row_writes_header_on_first_call_only`, `test_append_row_atomic_tempfile_rename_pattern`.
- [ ] T017 [P] Write RED integration test `tests/integration/test_audit_log_pipeline.py` — 4단계(takeout_ingest → audio_extract → transcripts → analyze) 시뮬레이션 → 4개 별도 CSV 파일 생성 + frozen fieldnames 일치 검증.
- [ ] T018 Extend `src/tube_scout/services/audit_writer.py` — add `STAGE_FIELDNAMES` dict (8 stages), `VALID_RESULTS` frozenset, generalized `AuditWriter.append_row(stage, row)`. Preserve existing `append_transcript_row` / `append_fingerprint_row` as backward-compat shims. Touch only `src/tube_scout/services/audit_writer.py`. Make T016-T017 pass. Ensure spec 012 회귀 테스트 (`tests/unit/test_audit_writer.py` 등) 도 통과.

### 2.4 Progress Reporter

- [ ] T019 [P] Write RED contract test `tests/contract/test_progress_reporter_contract.py` — `test_make_progress_reporter_returns_tty_when_stdout_is_tty`, `test_make_progress_reporter_returns_nontty_when_stdout_is_not_tty`, `test_progress_reporter_signature_matches_protocol`.
- [ ] T020 [P] Write RED unit test `tests/unit/test_progress_reporter_nontty.py` — `test_nontty_throttle_emits_every_n_items`, `test_nontty_throttle_emits_every_k_seconds`, `test_nontty_eta_not_shown_in_first_3_items`, `test_nontty_force_emit_on_final_item`, `test_nontty_log_line_format_regex`.
- [ ] T021 [P] Write RED integration test `tests/integration/test_progress_reporter_force_tty.py` — `force_tty=True/False` 각각 instantiation + 100 update() 호출 — exception 0.
- [ ] T022 Implement `src/tube_scout/services/progress_reporter.py` — `ProgressReporter` Protocol + `TTYProgressReporter` (rich.progress) + `NonTTYProgressReporter` (structured log + throttle) + `make_progress_reporter(stage, total, ...)` factory. Touch only `src/tube_scout/services/progress_reporter.py`. Make T019-T021 pass.

### 2.5 공통 Test Fixture

- [ ] T023 [P] Create `tests/fixtures/takeout_sample/` — anonymized mini Takeout fixture: 1 channel.csv (1 row), 1 동영상.csv (9 sanitized video rows with fake video_ids `aaaaaaaaaaa` ~ `iiiiiiiiiii`, fake titles, real-ish duration/timestamps), 9 fake mp4 files (1 KB each with valid ffprobe-readable header — use ffmpeg to generate 1-second silent mp4 with H.264 + AAC). Document fixture in `tests/fixtures/takeout_sample/README.md`.
- [ ] T024 [P] Create `tests/fixtures/v3_db_fixture.py` — pytest fixture function that creates a v3 content_reuse.db with spec 007/012 baseline rows (9 audio_fingerprint rows, 3 sample processing_status rows, 2 sample comparison_results rows) for use across v4 migration tests.

**Checkpoint**: Foundation 완료. T005-T024 모두 GREEN. 모든 user story 구현 진입 가능.

---

## Phase 3: User Story 1 — 교수 단위 M-nC2 강의 영상 재사용 판정 보고서 (Priority: P1) 🎯 MVP

**Goal**: 운영자가 4단계 파이프라인(`collect takeout` → `collect process-audio` → `analyze content-reuse` → `report content-reuse`)을 통해 한 교수 단위 영상 풀의 M-nC2 PDF/HTML 재사용 판정 보고서를 받는다.

**Independent Test**: 운영자가 1차 Takeout fixture(9 video) + 1명 교수 alias로 4단계 명령을 차례 실행 → PDF + HTML 1부씩 생성, SQLite에 channel_metadata + video_metadata + comparison_results + match_spans 모두 영속, 단정적 라벨 어휘 0건.

### 3.1 Takeout Ingestion (Phase 1 of idea — sub-phase 3.1)

- [ ] T025 [P] [US1] Write RED contract test `tests/contract/test_takeout_ingest_contract.py` — `test_parse_takeout_csv_metadata_returns_dedup_video_list`, `test_assemble_channel_work_dir_creates_symlinks`, `test_ingest_takeout_rejects_unknown_alias`, `test_ingest_takeout_idempotent_two_runs`, `test_ingest_takeout_dry_run_no_db_write`, `test_ignored_categories_audit_logged`.
- [ ] T026 [P] [US1] Write RED unit test `tests/unit/test_takeout_ingest_csv_parser.py` — 분할 CSV 통합 + dedup, ms→s 변환, channel_id 추출 from `채널.csv`.
- [ ] T027 [P] [US1] Write RED contract test `tests/contract/test_evidence_score_contract.py` — `test_score_mp4_candidates_returns_per_candidate_signals`, `test_decide_mapping_signature`.
- [ ] T028 [P] [US1] Write RED unit test `tests/unit/test_evidence_signals.py` — `test_exact_title_match_full_string`, `test_normalized_title_match_handles_spaces_and_punctuation`, `test_normalized_title_match_prefix_50_chars`, `test_duration_match_within_tolerance`, `test_size_ratio_plausible_range`, `test_mtime_match_within_1d`, `test_score_computation_all_signals` (40+25+5+5=75), `test_score_computation_normalized_replaces_exact` (+30 not +70).
- [ ] T029 [P] [US1] Write RED unit test `tests/unit/test_decide_mapping.py` — `test_high_confidence_when_score_above_65`, `test_medium_confidence_when_40_to_65`, `test_no_mapping_when_below_40`, `test_ambiguous_when_two_top_candidates_tie`.
- [ ] T030 [US1] Implement `src/tube_scout/services/evidence_score.py` — `EvidenceSignals` Pydantic model, `score_mp4_candidates`, `decide_mapping`, helper functions `_exact_title_match`, `_normalized_title_match`, `_duration_match`, `_size_ratio_plausible`, `_mtime_match`. Touch only `src/tube_scout/services/evidence_score.py`. Make T027-T029 pass.
- [ ] T031 [US1] Implement `src/tube_scout/services/takeout_ingest.py` — `parse_takeout_csv_metadata`, `assemble_channel_work_dir`, `ingest_takeout`, `IngestResult` Pydantic model. Use `evidence_score.decide_mapping` for mp4↔video_id, `audit_writer.append_row("takeout_ingest", ...)` for audit. Touch only `src/tube_scout/services/takeout_ingest.py`. Make T025-T026 pass.
- [ ] T032 [US1] Wire `tube-scout collect takeout` CLI in `src/tube_scout/cli/collect.py` — Typer command with `--takeout-dir`, `--channel`, `--copy`, `--dry-run` flags. Calls `takeout_ingest.ingest_takeout`. Validate alias via spec 003 resolver before any DB write. Exit codes per `contracts/cli_contract.md` §1.
- [ ] T033 [US1] Write RED integration test `tests/integration/test_takeout_ingest_e2e.py` — fixture `tests/fixtures/takeout_sample/` + tmp_path → `ingest_takeout` 실행 → channel_metadata 1 row + video_metadata 9 rows + processing_status 9 rows (status=collected) + symlinks in `<work_dir>/videos/` + audit CSV 검증.
- [ ] T034 [US1] [Measurement] Create `_workspace/measurement/evidence_score_phase1.md` template + write RED integration test `tests/integration/test_evidence_score_takeout_9_videos.py` (`@pytest.mark.slow`) that runs decide_mapping on the 9-video sanitized fixture, measures automation rate (high+medium)/9, writes results to `_workspace/measurement/evidence_score_phase1.md`. Threshold tuning recommendations are commit-ready output.

### 3.2 Audio Extract + Local Fingerprint (Phase 1 of idea — sub-phase 3.2)

- [ ] T035 [P] [US1] Write RED contract test `tests/contract/test_audio_extract_contract.py` — `test_extract_wav_16k_mono_creates_file_with_correct_specs`, `test_extract_force_overwrite`, `test_extract_no_force_skip_existing`, `test_extract_raises_on_missing_mp4`, `test_extract_raises_on_ffmpeg_failure`.
- [ ] T036 [P] [US1] Write RED unit test `tests/unit/test_wav_lifecycle.py` — `test_wav_lifecycle_deletes_on_normal_exit`, `test_wav_lifecycle_deletes_on_sigint`, `test_wav_lifecycle_preserves_when_keep_true`.
- [ ] T037 [US1] Implement `src/tube_scout/services/audio_extract.py` — `extract_wav_16k_mono`, `cleanup_wav`, `WavLifecycle` context manager (try/finally + SIGINT handler reusing spec 012 `build_signal_handler` pattern). Touch only `src/tube_scout/services/audio_extract.py`. Make T035-T036 pass.
- [ ] T038 [US1] Wire `tube-scout collect audio-extract` CLI in `src/tube_scout/cli/collect.py` — Typer command with `--channel`, `--video-ids`, `--all-takeout`, `--audio-cache-dir`, `--keep-audio`, `--sample-rate`, `--codec`, `--force` flags. Audit via `audit_writer.append_row("audio_extract", ...)`.
- [ ] T039 [US1] Write RED integration test `tests/integration/test_fingerprint_local_input.py` — uses fixture mp4 + spec 012's existing `extract_chromaprint_fingerprint` (B-7 reuse) — verifies wav_16k input produces deterministic hamming distance vs mp4 direct input.
- [ ] T040 [US1] Wire `tube-scout collect fingerprint --source local` CLI in `src/tube_scout/cli/collect.py` — extend existing `collect fingerprint` (spec 012) with `--source local` branch + `--input-kind {mp4, wav_16k, wav_22k}` option. Calls `services/audio_fingerprint.py::extract_chromaprint_fingerprint` (B-7). Audit `fingerprint_audit.csv` extended with `fingerprint_input_policy` column.
- [ ] T041 [US1] [Measurement] Create `_workspace/measurement/fingerprint_policy_phase1.md` template + integration test `tests/integration/test_fingerprint_input_policy_compare.py` (`@pytest.mark.slow`) that runs the same 9 videos through 3 policies (original_mp4, wav_16k, wav_22k), measures pairwise hamming distance, writes results. Commit-ready default-policy recommendation.

**Checkpoint 3.2**: Phase 1 of idea complete (Takeout ingestion + audio extract + fingerprint). End-to-end: `collect takeout` → DB; `collect audio-extract` → WAV cache; `collect fingerprint --source local --input-kind wav_16k` → `audio_fingerprint` rows.

### 3.3 ASR (faster-whisper) + Worker Pool + Text Normalizer (Phase 2 of idea — sub-phase 3.3)

- [ ] T042 [P] [US1] Write RED contract test `tests/contract/test_asr_contract.py` — `test_transcribe_audio_signature_matches_contract`, `test_preset_table_has_required_keys`, `test_caption_source_detail_format`.
- [ ] T043 [P] [US1] Write RED unit test `tests/unit/test_asr_quality_flags_detection.py` — `test_detect_repeat_n_finds_3_consecutive`, `test_detect_silence_filler_finds_common_patterns` ("구독과 좋아요", "시청해주셔서 감사합니다" 등 5+ 잔재 패턴), `test_language_mismatch_triggers_when_detected_differs`, `test_short_segments_excess_ratio_threshold`, `test_compression_ratio_violations_counter`.
- [ ] T044 [P] [US1] Write RED unit test `tests/unit/test_asr_importerror_actionable.py` — mock `faster_whisper` import failure → actionable message includes `uv sync --extra asr`.
- [ ] T045 [US1] Implement `src/tube_scout/services/asr.py` — `PRESET_TABLE` dict, `transcribe_audio` function (faster-whisper wrapper with hallucination defenses), `detect_quality_flags`, `_load_model` lru_cache singleton, ImportError fallback. Touch only `src/tube_scout/services/asr.py`. Make T042-T044 pass.
- [ ] T046 [P] [US1] Write RED contract test `tests/contract/test_text_normalizer_contract.py` — `test_normalize_transcript_text_is_idempotent` (n(n(x))==n(x)), `test_normalize_strips_meta_markers`, `test_normalize_strips_punctuation`, `test_normalize_nfc_handles_jamo_isolated`, `test_normalize_lowercases_latin_only`, `test_normalize_collapses_whitespace_and_newlines`, `test_normalize_transcript_json_writes_atomic`, `test_normalize_transcript_json_skips_when_version_matches`, `test_normalize_transcript_json_force_rewrites`.
- [ ] T047 [US1] Implement `src/tube_scout/services/text_normalizer.py` — `NORMALIZER_VERSION = "v1.0"`, `normalize_transcript_text`, `normalize_transcript_json`, `detect_source_conflict`. Touch only `src/tube_scout/services/text_normalizer.py`. Make T046 pass.
- [ ] T048 [P] [US1] Write RED contract test `tests/contract/test_worker_pool_contract.py` — `test_run_asr_worker_signature_matches_contract`, `test_run_pool_returns_pool_result_with_n_workers_entries`.
- [ ] T049 [P] [US1] Write RED unit test `tests/unit/test_atomic_claim.py` — `test_atomic_claim_returns_one_row_per_call`, `test_atomic_claim_updates_status_to_in_progress`, `test_atomic_claim_retry_failed_extends_predicate`, `test_concurrent_claim_two_threads_succeeds_for_one_only`.
- [ ] T050 [US1] Implement `src/tube_scout/services/worker_pool.py` — `run_asr_worker` (single-process worker loop with SQLite atomic claim per C-5), `run_pool` (multiprocessing spawn 2 workers with `CUDA_VISIBLE_DEVICES` env isolation), `_ensure_wal_mode`, `WorkerResult` + `PoolResult` Pydantic. Touch only `src/tube_scout/services/worker_pool.py`. Make T048-T049 pass.
- [ ] T051 [US1] Wire `tube-scout collect transcripts --source asr` CLI in `src/tube_scout/cli/collect.py` — extend existing `collect transcripts` (spec 010/012) with `--source asr` branch. Add `--preset {poc-laptop, prod-a6000, prod-a6000-pool, cpu-fallback}` (required), `--model`, `--compute-type`, `--device`, `--language`, `--beam-size`, `--vad-filter / --no-vad-filter`, `--retry-failed`, `--cleanup-audio`, `--auto-normalize / --no-auto-normalize`. Calls `asr.transcribe_audio` or `worker_pool.run_pool` based on preset. Audit `transcripts_audit.csv` extended with `caption_source_detail` column.
- [ ] T052 [US1] Wire `tube-scout process normalize-transcripts` CLI in new `src/tube_scout/cli/process.py` (or extend existing `cli/project.py` per plan flexibility) — Typer command with `--channel`, `--video-ids`, `--force`. Calls `text_normalizer.normalize_transcript_json` for each video. Audit `normalize_audit.csv`.
- [ ] T053 [US1] Wire `tube-scout collect process-audio` CLI in `src/tube_scout/cli/collect.py` — integrated mode command. Per-video loop using `WavLifecycle` context: extract WAV → fingerprint → ASR → auto-normalize → finally delete WAV. Calls all four services in sequence with progress reporting (`progress_reporter.make_progress_reporter("transcripts", total)`). `--preset`, `--skip-fingerprint`, `--skip-asr`, `--keep-audio`, `--retry-failed`, `--auto-normalize` flags.
- [ ] T054 [US1] Write RED integration test `tests/integration/test_asr_with_cached_model.py` (`@pytest.mark.slow`) — PoC video fixture (silent 1-second wav, faker model via monkeypatch returns deterministic segments) → segments output verified. Real-model variant gated by env `TUBE_SCOUT_POC_VIDEO_PATH`.
- [ ] T055 [US1] Write RED integration test `tests/integration/test_retry_failed_direct_transition.py` — pre-seed processing_status with 1 row `status='asr_failed'`. Run worker with `retry_failed=True`. Verify direct atomic transition to `asr_in_progress` (no intermediate `collected` reset), final state after success is `collected` with `caption_source='whisper'`.
- [ ] T056 [US1] Write RED integration test `tests/integration/test_worker_pool_dual_gpu.py` (`@pytest.mark.slow`) — monkeypatch CUDA env + fake faster-whisper → 2 processes spawn → 4-video queue distributed between workers, no double-processing. Asserts WorkerResult per-process counters sum to 4.
- [ ] T057 [US1] [Measurement] Create `_workspace/measurement/hallucination_baseline_phase2.md` template + integration test `tests/integration/test_hallucination_defense_baseline.py` (`@pytest.mark.slow`) — PoC video + 1 long-form fixture (or env-gated real video) → measure hallucination_repeat / silence_hallucination rates, write to `_workspace/measurement/hallucination_baseline_phase2.md`. SC-004 evidence.
- [ ] T058 [US1] [Measurement] Create `_workspace/measurement/asr_throughput_phase2.md` template + integration test `tests/integration/test_asr_throughput_poc.py` (`@pytest.mark.slow`, env-gated) — measure wall-clock per video on PoC GPU (RTX 3060 Laptop), write results. SC-002 PoC evidence.

**Checkpoint 3.3**: Phase 2 of idea complete. End-to-end: `collect process-audio --preset poc-laptop` runs full per-video lifecycle. `processing_status` transitions verified. Hallucination flags persisted.

### 3.4 nC2 Analysis + 4-Layer Defense + Pattern Classifier (Phase 3 of idea — sub-phase 3.4)

- [ ] T059 [P] [US1] Write RED contract test `tests/contract/test_nc2_matcher_contract.py` — `test_generate_nc2_pairs_returns_n_choose_2`, `test_generate_nc2_pairs_skips_layer_a_short`, `test_run_nc2_analysis_resumable_via_checkpoint`.
- [ ] T060 [P] [US1] Write RED unit test `tests/unit/test_time_axis_indicators.py` — `test_i6_longest_contiguous_single_span`, `test_i6_returns_zero_on_empty`, `test_i7_dispersion_balanced_vs_concentrated`, `test_i8_position_diversity_full_coverage_returns_1`, `test_i8_half_split_returns_two_values_summing_to_total`.
- [ ] T061 [P] [US1] Write RED unit test `tests/unit/test_pattern_classifier.py` — `test_classify_whole_same_week`, `test_classify_scattered_different_week`, `test_classify_re_recorded_same_content_when_audio_differs`, `test_classify_tail_update_when_i8_drops`.
- [ ] T062 [US1] Complete `src/tube_scout/services/time_axis_indicators.py` (spec 011 부분 구현 마무리) — implement `compute_i6_longest_contiguous`, `compute_i7_distribution_dispersion`, `compute_i8_position_diversity`, `compute_i8_half_split` per `contracts/nc2_analyze_contract.md` §B. Touch only this file. Make T060 pass.
- [ ] T063 [US1] Complete `src/tube_scout/services/layer_defense.py` (spec 011 부분 구현 마무리) — implement `apply_layer_a`, `apply_layer_b`, `apply_layer_c`, `apply_layer_d` per `contracts/nc2_analyze_contract.md` §C. Touch only this file.
- [ ] T064 [US1] Complete `src/tube_scout/services/pattern_classifier.py` — add `RE_RECORDED_SAME_CONTENT` + `TAIL_UPDATE` branches to `classify` function, including audio_fp_hamming threshold parameter + i8_half_split logic. Touch only this file. Make T061 pass.
- [ ] T065 [US1] Complete `src/tube_scout/services/nc2_matcher.py` (spec 011 부분 구현 마무리) — `generate_nc2_pairs` (Layer A culling + pair enumeration ordered by video_id), `run_nc2_analysis` (per-pair comparison driver with checkpoint/resume + progress reporter + audit). Touch only this file. Make T059 pass.
- [ ] T066 [US1] Wire `tube-scout analyze content-reuse` CLI in new `src/tube_scout/cli/analyze.py` (or extend `cli/content.py` per plan flexibility) — Typer command with `--channel`, `--professor`, `--mode {M-default, M-nC2}`, `--layer-a-seconds`, `--layer-b-threshold`, `--resume`, `--force`. Calls `nc2_matcher.run_nc2_analysis`. Audit `analyze_audit.csv` every 100 pairs.
- [ ] T067 [US1] Write RED integration test `tests/integration/test_nc2_analysis_full.py` (`@pytest.mark.slow`) — fixture 9-video professor → 36 pairs → `comparison_results` 36 rows + `match_spans` rows + 6 pattern label coverage check. **Additional assertions (G1/G2 coverage)**: (a) every row has non-NULL `audio_fp_hamming`, `audio_fp_best_offset`, `audio_fp_overlap_seconds` (FR-032 column-write verification), (b) every row has `source_type_pair` ∈ {`asr-asr`, `api-api`, `asr-api`, `manual-asr`} and the value correctly matches the actual transcript source types of source/target videos (FR-026 value-correctness verification — fixture should include at least 1 mixed-source pair).
- [ ] T068 [US1] Write RED integration test `tests/integration/test_layer_defense_e2e.py` — fixture baseline_corpus + sample match spans → apply_layer_b filters out high-frequency n-grams.
- [ ] T069 [US1] Write RED integration test `tests/integration/test_nc2_resume.py` — interrupt after 10/36 pairs (kill process mid-run) → re-run with `--resume` → continues from pair 11, final result identical to uninterrupted run.
- [ ] T070 [US1] [Measurement] Create `_workspace/measurement/audio_fp_threshold_phase3.md` template + integration test `tests/integration/test_audio_fp_hamming_distribution.py` (`@pytest.mark.slow`) — measure hamming distance distribution on known-same (re-rendered same audio) vs known-different (different audio) pairs, write cutoff recommendation. Phase 3 evidence for FR-031 audio_fp_hamming_threshold default.

### 3.5 Per-Professor M-nC2 Report (Phase 3 of idea — sub-phase 3.5)

- [ ] T071 [P] [US1] Write RED contract test `tests/contract/test_professor_report_contract.py` — `test_render_professor_nc2_report_signature_matches_contract`, `test_report_result_includes_pattern_distribution`.
- [ ] T072 [P] [US1] Write RED unit test `tests/unit/test_appendix_threshold_passes.py` — `test_passes_appendix_or_semantics_single_axis`, `test_passes_appendix_no_thresholds_admits_all`, `test_passes_appendix_5_metric_combinations`.
- [ ] T073 [P] [US1] Write RED integration test `tests/integration/test_report_tone.py` — render sample report → grep for definitive-verdict tokens ("재활용 확정", "위반", "표절", "복제") → 0 matches required (SC-007 regression guard).
- [ ] T074 [P] [US1] Create `src/tube_scout/reporting/templates/professor_nC2_report.html` — jinja2 template per `contracts/professor_report_contract.md` §Template structure. Header comment enforcing FR-037 tone. Include sections: cover, channel summary, per-metric histograms (5 axes), top-K table, pattern statistics, layer defense breakdown, appendix per-pair detail pages.
- [ ] T075 [US1] Implement `src/tube_scout/reporting/professor_nc2.py` — `AppendixThresholds` Pydantic, `passes_appendix` helper, `render_professor_nc2_report` (queries comparison_results+video_metadata+audio_fingerprint, sorts by `--sort-by`, renders jinja2, weasyprint PDF), `_render_pdf` lazy weasyprint import, `ReportResult`. Touch only this file. Make T071-T073 pass.
- [ ] T076 [US1] Wire `tube-scout report content-reuse` CLI in new `src/tube_scout/cli/report.py` extension (or existing `cli/report.py`) — Typer command with `--channel`, `--professor`, `--mode`, `--top-k` (default 50), `--sort-by`, `--appendix-threshold-i2-cosine`, `--appendix-threshold-i6-longest-contiguous`, `--appendix-threshold-i7-distribution-dispersion`, `--appendix-threshold-i8-position-diversity`, `--appendix-threshold-audio-fp-hamming`, `--format {pdf, html, both}`, `--output`. Audit `report_audit.csv`.
- [ ] T077 [US1] Extend `src/tube_scout/visualization/time_axis.py` — add `render_pair_alignment_view(pair, src_spans, tgt_spans) -> bytes` (matplotlib/plotly static PNG with colored match regions) + `render_time_axis_profile(pair) -> bytes` (per-bin match density chart). Touch only this file.
- [ ] T078 [US1] Write RED integration test `tests/integration/test_professor_nc2_report.py` (`@pytest.mark.slow`) — mini-nC2 fixture (9 videos = 36 pairs) → render report (format=both) → HTML file exists, PDF file exists, ReportResult.appendix_count + pattern_distribution populated.
- [ ] T079 [US1] Write RED integration test `tests/integration/test_report_pdf_optional_extra.py` — monkeypatch `weasyprint` ImportError → `_render_pdf` raises actionable message with `uv sync --extra pdf`.

### 3.6 US1 End-to-End Integration

- [ ] T080 [US1] Write RED integration test `tests/integration/test_us1_full_pipeline.py` (`@pytest.mark.slow`) — fixture 9-video Takeout → run all 4 CLI commands in sequence (collect takeout → collect process-audio --preset poc-laptop --skip-asr fake_asr_monkeypatch → analyze content-reuse → report content-reuse) → assert PDF + HTML generated, SQLite tables fully populated, audit CSV 8 files present.
- [ ] T081 [US1] Write RED adversary test `tests/adversary/test_us1_attack_surface.py` — attack scenarios: (a) malformed CSV bytes in metadata CSV, (b) duplicate video_id rows in CSV, (c) mp4 with truncated header, (d) ambiguous mapping CSV with unknown video_id, (e) concurrent invocations of `collect takeout` on the same channel, (f) SIGTERM during process-audio integrated mode. All scenarios MUST produce actionable English error messages, not silent failure.

**Checkpoint US1**: 사용자 스토리 1 완전 기능 + 독립 테스트 통과. MVP 자격 — 본 시점에 운영 검토 시작 가능.

---

## Phase 4: User Story 2 — KB Transcript Export (Priority: P2)

**Goal**: 운영자가 단일 또는 채널 전체 자막 JSON을 평문(txt/md/jsonl)로 export하여 외부 KB 도구의 입력으로 사용.

**Independent Test**: 운영자가 임의 video_id로 `transcript export` 실행 → UTF-8 평문 파일(BOM 없음) 출력. `transcript export-bulk --channel <alias>` → 채널 자막 N개를 한 디렉터리에 영상별 파일로 출력. ASR 출처와 API caption 출처 모두 동일 형식으로 처리.

- [ ] T082 [P] [US2] Write RED contract test `tests/contract/test_kb_export_contract.py` — `test_export_signature_matches_contract`, `test_export_result_byte_count_matches_file_size`.
- [ ] T083 [P] [US2] Write RED unit test `tests/unit/test_kb_export_formats.py` — `test_txt_format_strips_timestamps_by_default`, `test_txt_keep_timestamps_includes_brackets`, `test_md_with_meta_includes_header`, `test_md_without_meta_body_only`, `test_jsonl_per_segment_one_line`, `test_jsonl_with_meta_first_line_is_meta_object`, `test_clean_fillers_removes_korean_filler_patterns`, `test_output_utf8_no_bom`.
- [ ] T084 [P] [US2] Write RED integration test `tests/integration/test_kb_export_bulk.py` — 50 fixture transcripts → `export_bulk` → 50 output files. Mixed source types (asr + captions_api) produce identical format-agnostic results.
- [ ] T085 [US2] Implement `src/tube_scout/services/kb_export.py` — `ExportResult` + `BulkExportResult` Pydantic, `export_transcript` (single video), `export_bulk` (multi video with progress reporter). Format-specific writers: `_write_txt`, `_write_md`, `_write_jsonl`. `_FILLER_PATTERNS` regex list for Korean ASR fillers. UTF-8 no-BOM atomic write. Touch only this file.
- [ ] T086 [US2] Wire `tube-scout transcript export` + `transcript export-bulk` CLIs in new `src/tube_scout/cli/transcript.py` (or extend existing `cli/project.py`) — Typer commands with `--video-id` or `--channel`/`--video-ids-file`/`--all`, `--format {txt,md,jsonl}`, `--keep-timestamps`, `--clean-fillers`, `--with-meta`, `--output`/`--output-dir`. Register in `cli/main.py` `app.add_typer()`. Audit `kb_export_audit.csv`.
- [ ] T086a [P] [US2] Write integration test `tests/integration/test_no_force_asr_flag.py` (G3 coverage) — assert that `tube-scout collect transcripts --help` output does NOT contain `--force-asr` (FR-027 negative requirement verification). Also assert `--force-asr` is not a registered option name via Typer introspection.

**Checkpoint US2**: 사용자 스토리 2 완전 기능 + 독립 테스트 통과. P1과 독립적으로 출시 가능.

---

## Phase 5: User Story 3 — yt-dlp Legacy Removal (Priority: P3)

**Goal**: spec 012 yt-dlp surface 전체 코드 · CLI · 테스트 · devShell · 문서에서 제거. 공기관 운영 적합성 사유.

**Independent Test**: Phase 5 머지 후 codebase에서 `ytdlp`, `yt-dlp`, `--source ytdlp` 식별자 grep 결과 0건. P1·P2 회귀 테스트 전부 통과 유지.

- [ ] T087 [US3] Write RED integration test `tests/integration/test_phase4_legacy_removal.py` — assertions BEFORE removal pass GREEN after removal: (a) `from tube_scout.services.audit_writer import AuditWriter` import works, (b) `AuditWriter.append_row("transcripts", ...)` and `.append_row("fingerprint", ...)` work, (c) all 8 stage frozen fieldnames intact, (d) `tube_scout.cli.collect` has no `--source ytdlp` option, (e) `tube_scout.cli.collect._dispatch_ytdlp_transcripts` not importable, (f) ytdlp surface modules not importable.
- [ ] T088 [US3] Write RED adversary test `tests/adversary/test_us3_no_ytdlp_grep.py` — programmatically grep src/ + tests/ (excluding `_archive/` if any) + CLAUDE.md for tokens `ytdlp`, `yt-dlp`, `--source ytdlp`, `_dispatch_ytdlp_transcripts`, `srv3_parser` — assert 0 matches.
- [ ] T089 [US3] Delete `src/tube_scout/services/ytdlp_adapter.py`, `services/ytdlp_errors.py`, `services/srv3_parser.py`. Also delete corresponding unit tests under `tests/` (search for files importing these modules). One commit for these deletions.
- [ ] T090 [US3] Remove `--source ytdlp` branch + `_dispatch_ytdlp_transcripts` function + related imports from `src/tube_scout/cli/collect.py`. Preserve `--source api` (spec 010) and `--source asr` (this spec) branches.
- [ ] T091 [US3] Remove ONLY `yt-dlp` from `pyproject.toml` `dependencies`. **`pyacoustid` MUST NOT be removed** — `services/audio_fingerprint.py` (B-7 boundary) depends on it and this dependency persists post-Phase-5 (FR-046 retention clause). Touch only `pyproject.toml`. Verify post-edit with `grep -n yt-dlp pyproject.toml` (0 matches) and `grep -n pyacoustid pyproject.toml` (1+ matches).
- [ ] T092 [US3] Remove yt-dlp related packages from `flake.nix` devShell (`yt-dlp` if present; preserve `chromaprint`, `ffmpeg`, `zlib`, `stdenv.cc.cc.lib` which are spec 012 chromaprint deps still used by this spec). Touch only `flake.nix`.
- [ ] T093 [US3] Remove yt-dlp references from `CLAUDE.md` `Active Technologies` (spec 012 entry) and `Recent Changes` (preserve historical entries but mark spec 012 as "removed in spec 013" and add new spec 013 entry per Phase 5 cleanup). Touch only `CLAUDE.md`.
- [ ] T094 [US3] Delete `specs/012-ytdlp-adapter/` directory contents (preserved via git history per FR-046). One commit.
- [ ] T095 [US3] Run full test suite + verify T087-T088 pass + spec 007/010/011/this-spec tests still GREEN. If any regression, fix in same commit cycle.

**Checkpoint US3**: 사용자 스토리 3 완료. yt-dlp surface 0건, P1/P2 무회귀.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 문서 갱신, perf 테스트, adversary cross-cutting, follow-up 일정 등록.

- [ ] T096 [P] Update `quickstart.md` if any contract changed during implementation (likely small edits for actual CLI flag names finalized). Cross-check with `cli_contract.md`.
- [ ] T097 [P] Update `CLAUDE.md` Recent Changes section with final spec 013 milestone notes (v0.5.0 internal tag, all 9 CLI commands listed, v4 migration summary). (note: "release" 어휘는 2026-05-15 결정으로 제거)
- [ ] T098 [P] Write `tests/perf/test_nc2_runtime.py` (`@pytest.mark.slow`, env-gated by `TUBE_SCOUT_PERF_FIXTURE_200_VIDEO`) — measures wall-clock for 200-video M-nC2 analysis on production GPU server. Writes to `_workspace/measurement/nc2_runtime_phase3.md`. SC-002 evidence.
- [ ] T099 [P] Write `tests/perf/test_asr_throughput_prod_gpu.py` (`@pytest.mark.slow`, env-gated) — measures `prod-a6000-pool` GPU utilization over 30-min window. Writes to `_workspace/measurement/asr_throughput_prod_phase2.md`. SC-002 + SC-010 evidence.
- [ ] T100 [P] Run cross-spec boundary regression — execute `tests/integration/test_v3_to_v4_idempotent.py` + spec 007/010/011/012 (pre-removal) integration tests against v4 DB → ensure no regression on existing schema consumers.
- [x] T101 **REMOVED (2026-05-15)** — 당초 `_workspace/measurement/30day_followup_plan.md` 에 30일 시한부 trigger 를 기록하기로 했으나, 2026-05-15 결정으로 "출시" 개념 + 시한부 trigger 모두 폐기. C-3 / FR-036 / FR-038 의 weight commit 은 데이터 누적(`review_status` 라벨링) 자체가 trigger 이며 시한 없음. 30day plan 파일 삭제됨.
- [ ] T102 [P] Add `tests/adversary/test_cross_phase_attack.py` — adversary scenarios across all 3 stories: (a) concurrent worker pool + Ctrl+C cleanup, (b) corrupted Takeout CSV during ingestion with partial DB write, (c) race between `analyze content-reuse` and `report content-reuse` (analysis still running when report invoked), (d) malformed transcripts_normalized JSON during analysis, (e) KB export to read-only directory.
- [ ] T103 Run `quickstart.md` validation — walk through §0~§5 on real PoC environment, fix any CLI flag mismatch or path drift. Document remaining manual steps (if any) in `quickstart.md` itself.
- [ ] T104 Update version: `pyproject.toml` `version = "0.4.0"` → `"0.5.0"`. One dedicated commit per Constitution VIII Conventional Commits convention: `chore(release): bump version to v0.5.0 for spec 013 GA`. (note: "GA" 어휘는 2026-05-15 결정 이전 commit 이라 history 그대로 유지)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1, T001-T004)**: 즉시 시작 가능. T001-T003 모두 [P], T004는 T001 의존.
- **Foundational (Phase 2, T005-T024)**: Setup 완료 후 시작. 본 phase 미완 상태에서 어떤 user story도 진행 불가.
- **US1 (Phase 3, T025-T081)**: Foundational 완료 후. sub-phase 3.1→3.2→3.3→3.4→3.5→3.6 순차(3.1의 ingest → 3.2의 mp4 input → 3.3의 STT → 3.4의 분석 → 3.5의 보고서 → 3.6 e2e).
- **US2 (Phase 4, T082-T086)**: Foundational + US1.3 (transcripts 생성됨) 완료 후. raw transcripts JSON이 입력이라 US1.3 종속.
- **US3 (Phase 5, T087-T095)**: US1·US2 모두 GREEN 완료 + 운영 검증 후. **운영자 명시 승인 필요** — yt-dlp 삭제는 되돌리기 어려움.
- **Polish (Phase 6, T096-T104)**: 위 모두 완료 후.

### Within Each User Story

- 모든 RED 테스트(T0xx with "Write RED ...")는 대응 구현 task보다 먼저 GREEN 검증 후 진행.
- Models → services → CLI thin wrapper 순.
- 측정 task(T034, T041, T057, T058, T070)는 해당 sub-phase 마지막에 — 측정 결과로 spec follow-up amendment 생성.

### Parallel Opportunities

- **Setup**: T001, T002, T003 동시 가능. T004는 T001 의존.
- **Foundational**: T005-T008 (v4 migration RED 테스트) [P], T009 implementation 순차. T010-T013 (모델 RED 테스트) [P], T014-T015 implementation 순차. T016-T017 (audit RED) [P], T018 impl. T019-T021 (progress RED) [P], T022 impl. T023-T024 (fixtures) [P]. **Foundational 안에서 v4 migration / 모델 / audit_writer / progress reporter / fixture 4개 트랙은 서로 독립이라 동시 가능.**
- **US1 sub-phase 3.1**: T025-T029 (RED) [P], T030-T034 implementation 순차(같은 ingestion flow).
- **US1 sub-phase 3.2**: T035-T036 (RED) [P], T037-T041 순차.
- **US1 sub-phase 3.3**: T042-T049 (RED, 다른 파일) [P], T050-T053 순차 (CLI 같은 파일 collect.py 의 다중 command).
- **US1 sub-phase 3.4**: T059-T061 (RED) [P], T062-T064 [P] (different files: time_axis_indicators.py / layer_defense.py / pattern_classifier.py), T065-T066 순차.
- **US1 sub-phase 3.5**: T071-T074 (RED + template) [P], T075-T079 순차.
- **US2**: T082-T084 (RED) [P], T085-T086 순차.
- **US3**: T087-T088 (RED) [P], T089-T095 순차 (삭제는 안전을 위해 순서 보존).
- **Polish**: T096, T097, T098, T099, T100, T102 모두 [P]. T101, T103, T104는 순차.

---

## Parallel Example: User Story 1 sub-phase 3.3 (ASR + Worker Pool + Normalizer)

```bash
# Launch all RED tests for sub-phase 3.3 together (different test files):
Task: "Write tests/contract/test_asr_contract.py"                   # T042
Task: "Write tests/unit/test_asr_quality_flags_detection.py"        # T043
Task: "Write tests/unit/test_asr_importerror_actionable.py"         # T044
Task: "Write tests/contract/test_text_normalizer_contract.py"       # T046
Task: "Write tests/contract/test_worker_pool_contract.py"           # T048
Task: "Write tests/unit/test_atomic_claim.py"                       # T049

# After RED tests fail as expected, launch implementations for files
# that don't share file paths (T045, T047, T050 each touch different services/*.py):
Task: "Implement src/tube_scout/services/asr.py"                    # T045
Task: "Implement src/tube_scout/services/text_normalizer.py"        # T047
Task: "Implement src/tube_scout/services/worker_pool.py"            # T050

# Then sequentially wire CLI (all touch cli/collect.py):
Task: "Wire collect transcripts --source asr CLI"                   # T051
Task: "Wire process normalize-transcripts CLI"                      # T052 (cli/process.py)
Task: "Wire collect process-audio CLI"                              # T053 (cli/collect.py)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. **Phase 1 Setup** (T001-T004) — 의존성 + devShell.
2. **Phase 2 Foundational** (T005-T024) — v4 migration + 모델 + audit_writer + progress + fixtures. 본 phase 미완 시 후속 진행 불가.
3. **Phase 3 US1** (T025-T081) — 4단계 파이프라인 완성 + 보고서.
4. **STOP and VALIDATE**: T080-T081 통합·adversary 테스트 GREEN. 1차 Takeout fixture로 운영 검토 시작.
5. PoC 결과로 측정 산출 commit (`_workspace/measurement/` 5개 파일) → spec follow-up amendment에 evidence score · fingerprint_input_policy 기본값 commit.

### Incremental Delivery

1. Setup + Foundational 완료 → Foundation ready.
2. US1 완료 → Test independently → 운영자 PoC 진입 (mp4 9개 + 1 교수 가짜 분석).
3. US2 완료 → Test independently → KB export 사용 시작.
4. **운영 안정성 확인 (수주 ~ 수개월)** → 사용자 명시 승인 후 US3 진행.
5. US3 완료 → 기존 spec 012 운영 영향 0 확인 → v0.5.0 release.

### Parallel Team Strategy

여러 개발자 가용 시 (Foundational 완료 후):

- **Developer A (P1 분석 트랙)**: US1 sub-phase 3.4 + 3.5 (nC2 + 보고서). 3.4 → 3.5 순.
- **Developer B (P1 acquisition 트랙)**: US1 sub-phase 3.1 + 3.2 + 3.3 (Takeout + audio + ASR). 3.1 → 3.2 → 3.3 순.
- **Developer C (P2)**: US2 (KB export). 단일 모듈이라 분량 작음 — Developer A/B 보조 가능.
- **Developer D (measurement)**: T034, T041, T057, T058, T070 — 각 sub-phase 종료 시점에 측정 산출 작업. 본 트랙은 인프라 트랙과 약간의 동기화 필요(측정 대상 모듈 GREEN 상태).

US3는 운영 검증 후 단일 개발자가 일괄 처리(되돌리기 어려움 — 위험 최소화).

---

## Notes

- [P] = 다른 파일·의존 없음.
- [Story] 라벨이 task와 user story 1:1 매핑 — traceability 확보.
- 모든 RED 테스트는 구현 task 시작 전 GREEN 검증 + commit.
- 측정 산출(T034, T041, T057, T058, T070)은 spec follow-up amendment 입력. 가중치 공식 commit 은 T101 REMOVED 항목 참조 — 시한부 trigger 폐기, `review_status` 라벨링 누적 자체가 trigger.
- spec 012 코드 삭제(Phase 5)는 운영자 명시 승인 후 진행 — 본 spec에서는 기능적으로 완성된 상태에서만 진입.
- Constitution VII boundary 검증은 T100에서 일괄 — Phase 5 진행 전 prior spec(007/010/011/012) 회귀 0 확인 게이트.
- Task 총수: 104. US1=57(T025-T081), US2=5(T082-T086), US3=9(T087-T095), Setup=4, Foundational=20, Polish=9.
