# Implementation Plan: Takeout 통합 적재와 운영 효율화

**Branch**: `017-takeout-unified-ingest` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/home/kjeong/localgit/tube-scout/specs/017-takeout-unified-ingest/spec.md`

## Summary

spec 013 (Takeout local ASR + 재사용 탐지) 의 적재 모듈 안에서 mp4 1 개의 길이 정보를 영상 메타 후보 2,554 회마다 외부 도구 (ffprobe) 로 재측정하는 비효율 결함이 적재 시간을 약 17 배로 부풀리는 사실이 spec 016 closure 시점의 매뉴얼 검증에서 드러났다. 동시에 사용자 의도 6 단계 흐름 (정합성 확인 → DB 저장 → 영상→음원 1 회 추출 → 자막+지문 → 별도 저장 + DB 참조 → 분석) 이 분리 명령 5 개로 흩어져 있어 운영자가 한 학과 묶음을 처리하기 위해 명령을 4–5 회 호출해야 한다는 운영 부담도 함께 식별되었다. 본 spec 은 (A) mp4 길이 측정의 메모이즈로 적재 시간을 1 분 이내로 단축하고, (B) 적재·음원·자막·지문 흐름을 단일 신규 명령 (`collect ingest`) 으로 통합하며, (C) 처리 직후 영상 본체를 운영자 확인 후 정리하는 두 단계 prompt 흐름과 처리 실패 영상의 재시도 매니페스트를 도입한다.

## Technical Context

**Language/Version**: Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`)
**Primary Dependencies**: typer, rich, pydantic v2, polars, faster-whisper (≥1.0.0, `[asr]` optional extra), CTranslate2 4.x, ffmpeg (chromaprint 패키지에 동봉). 신규 PyPI 의존성 0 건 — 기존 `[asr]` / `[dev]` / 기본 surface 안에서 모두 처리.
**Storage**: SQLite v4 (스키마 변경 없음 — spec 013 의 channel_metadata + video_metadata + processing_status + quality_results + comparison_results 보존), JSON atomic write (channel_meta.json, videos_meta.json, channels.json, departments.json, **신규 retry_pending.json**), 감사 CSV (`audit_writer.py` 의 stage `takeout_ingest` + 신규 stage `ingest_orchestrator` / `source_video_cleanup`).
**Testing**: pytest 9.x + pytest-asyncio + pytest-cov. 단위/통합/contract/회귀 매트릭스 분리.
**Target Platform**: Linux (NixOS / Gentoo). 본 작업 머신 (RTX 3060 6GB + 표준 PC). 향후 22 학과 확장 시 GPU 서버 분리.
**Project Type**: CLI 도구 (단일 프로젝트, `src/tube_scout/` + `tests/`).
**Performance Goals**: 적재 단계 측정 평균 8.3s (실적재) / 1.64s (dry-run, 멱등 호출), SC-001 (≤ 60s) 충족 — T003 baseline 1061s 대비 약 644 배 개선 (RTX 3060 + 표준 PC, archive 9.9 GB / 9 mp4 / 2554 메타). 통합 명령 전체 (자막 + 지문 포함) 평균 64.26s (자막+지문 단계 ~54.7s 동시 처리, 동일 음원 1 회 디코딩 SC-005 충족). 측정 raw: `_workspace/spec017_t037_runs.log`, 분석: `_workspace/spec017_baseline_after_memoize.md`.
**Constraints**: 멱등성 보존 (spec 016 FR-009), 임시 음원 비영구화 (spec 013 C-1), 감사 로그 append-only (spec 013), 영상 삭제는 운영자 명시 옵션 + 두 단계 prompt 후에만 수행 (spec 017 FR-011/FR-012).
**Scale/Scope**: 자교 22 학과 × 평균 약 2,500 영상 메타 = 약 55,000 영상 메타. 본 spec 의 변경은 한 학과 단위 처리 효율 향상이며, 22 학과 누적 처리 모델은 본 spec 의 직접 범위 밖이지만 측정 baseline 을 본 spec 안에서 도출한다.

## Constitution Check

*GATE: Phase 0 research 진입 전 + Phase 1 design 완료 후 두 번 점검.*

| Principle | Gate | 평가 | 비고 |
|---|---|---|---|
| I. Test-First (NON-NEGOTIABLE) | 모든 task RED → GREEN → REFACTOR 보장 | ✅ Pass | tasks.md 작성 시 모든 변경에 failing 테스트 선행, 단위/통합/회귀 매트릭스 분리 |
| II. Fail-Fast & Anti-Hallucination | `except: pass` 금지, `# [VERIFY]` 마커 해소 | ✅ Pass | retry 매니페스트 파일 부재 시 명시적 에러 (FR-014 거부 흐름), `--delete-source` 미지정 시 prompt 자체 등장 안 함 (silent 금지) |
| III. Type Safety + Single Responsibility | 모든 public 함수 type annotation + Google docstring + 단일 책임 | ✅ Pass | `services/unified_ingest.py` 신규 orchestrator + `services/retry_manifest.py` 신규 단위 분리 |
| IV. CLI-First | 통합 흐름이 CLI 명령으로 노출 | ✅ Pass | `collect ingest` 신규 명령 (Typer subcommand), 기존 분리 명령 backward compat 유지 |
| V. Local-First Persistence | 외부 DB 서버 0, SQLite + JSON + Parquet 만 | ✅ Pass | 신규 retry_pending.json 도 JSON atomic write, SQLite 스키마 변경 없음 |
| VI. Secrets via agenix (NON-NEGOTIABLE) | 시크릿 0건 신규 | ✅ Pass | 본 spec 은 OAuth 흐름을 건드리지 않음 (spec 003/009 보존) |
| VII. Cross-Spec Boundary (NON-NEGOTIABLE) | Cross-Spec Boundaries 섹션 명시 + 각 경계에 acceptance | ✅ Pass | spec.md §Cross-Spec Boundaries 명시 + plan 의 §Cross-Spec Boundaries 표 보강 (B-1 ~ B-10 enumerate) + 본 spec 의 통합 흐름 시나리오가 spec 013 의 `WavLifecycle` + spec 016 의 적재 흐름을 모두 통과 |

모든 gate 통과. Complexity Tracking 비움.

## Project Structure

### Documentation (this feature)

```text
specs/017-takeout-unified-ingest/
├── plan.md              # 본 파일
├── research.md          # Phase 0 출력 (기술 결정 정리)
├── data-model.md        # Phase 1 출력 (entity 정의)
├── quickstart.md        # Phase 1 출력 (운영자 quickstart)
├── contracts/           # Phase 1 출력 (CLI / 데이터 schema contracts)
│   ├── collect-ingest.md
│   ├── retry-manifest.md
│   └── source-video-cleanup.md
├── checklists/
│   └── requirements.md  # spec.md 작성 단계의 quality checklist
└── tasks.md             # Phase 2 출력 (/speckit.tasks 단계)
```

### Source Code (repository root)

```text
src/tube_scout/
├── models/
│   └── content.py                    # 변경 — RetryManifestEntry 모델 추가 (선택)
├── services/
│   ├── evidence_score.py             # 변경 — mp4 duration 메모이즈 (FR-001, FR-002)
│   ├── takeout_ingest.py             # 변경 — orchestrator 가 호출하는 entry 점 보강
│   ├── unified_ingest.py             # 신규 — 통합 흐름 orchestrator (FR-005~FR-009)
│   ├── retry_manifest.py             # 신규 — 재시도 매니페스트 매니저 (FR-015, FR-018)
│   ├── source_video_cleanup.py       # 신규 — 영상 삭제 두 단계 prompt + unlink (FR-011~FR-014)
│   ├── audit_writer.py               # 변경 (선택) — stage 어휘에 `ingest_orchestrator`, `source_video_cleanup` 추가
│   ├── audio_extract.py              # 보존 — WavLifecycle 컨텍스트 그대로 사용
│   ├── asr.py                        # 보존
│   └── audio_fingerprint.py          # 보존
└── cli/
    └── collect.py                    # 변경 — `collect_ingest_command` 신규 Typer subcommand

tests/
├── unit/
│   ├── test_evidence_score_memoize.py    # 신규 — FR-001/FR-002 메모이즈 회귀
│   ├── test_retry_manifest.py            # 신규 — FR-015/FR-018 매니페스트 round-trip
│   ├── test_source_video_cleanup.py      # 신규 — FR-011~FR-014 두 단계 prompt + unlink
│   └── test_unified_ingest_orchestrator.py  # 신규 — FR-005~FR-009 단계별 흐름 모킹
├── integration/
│   ├── test_collect_ingest_e2e.py        # 신규 — US1/US2 end-to-end (실데이터 archive)
│   ├── test_ingest_idempotent.py         # 신규 — FR-009 + SC-004 멱등성 회귀
│   ├── test_ingest_partial_failure.py    # 신규 — US3 acceptance 4 + SC-007 부분 실패 흐름
│   └── test_ingest_retry_followup.py     # 신규 — FR-018 + SC-008 재시도 매니페스트 흐름
└── contract/
    ├── test_collect_ingest_contract.py        # 신규 — CLI contract (exit code, 옵션 매트릭스)
    ├── test_retry_manifest_contract.py        # 신규 — retry_pending.json 스키마 contract
    └── test_source_video_cleanup_contract.py  # 신규 — prompt 흐름 + audit row contract
```

**Structure Decision**: 단일 프로젝트 구조 (Option 1) 유지. 신규 모듈 3 개 (`unified_ingest.py`, `retry_manifest.py`, `source_video_cleanup.py`) 는 모두 `src/tube_scout/services/` 안에 신설하여 spec 013 / spec 016 의 기존 서비스와 동일 레벨에 둔다. CLI 진입점 `collect ingest` 는 `cli/collect.py` 안에 신규 Typer subcommand 로 추가하여 기존 분리 명령과 같은 파일에서 backward compatibility 가 한눈에 보이도록 한다.

## Cross-Spec Boundaries (Principle VII)

본 spec 의 변경은 다음 prior spec / 외부 시스템의 경계를 명시적으로 보존하거나 새로 정의한다.

| Boundary | Prior 측 | 본 spec 의 가정 / 신규 production | 검증 시나리오 |
|---|---|---|---|
| B-1 | spec 013 `WavLifecycle` 컨텍스트 매니저 | 임시 WAV 가 컨텍스트 종료 시 자동 삭제됨을 보존. 본 spec 의 unified_ingest 가 이 컨텍스트 안에서 자막+지문 두 단계를 호출 | `test_unified_ingest_orchestrator.py::test_wav_lifecycle_called` |
| B-2 | spec 013 `services/asr.py::transcribe_audio` | wav_path 입력 시그니처 보존. 본 spec 은 새 인자 추가 없음 | `test_collect_ingest_e2e.py::test_asr_invoked_with_wav_path` |
| B-3 | spec 013 `services/audio_fingerprint.py::extract_chromaprint_fingerprint` | wav_path / audio_path 입력 시그니처 보존 | `test_collect_ingest_e2e.py::test_fingerprint_invoked_with_audio_path` |
| B-4 | spec 013 SQLite v4 스키마 | `processing_status`, `quality_results`, `comparison_results` 컬럼 셋 그대로 유지. 본 spec 은 스키마 변경 0 건 | `test_v4_schema_invariant.py` (spec 016 의 회귀 테스트 재사용) |
| B-5 | spec 013 감사 CSV (stage `takeout_ingest`) | 기존 컬럼 셋 + append-only 보존. 본 spec 이 신규 stage `ingest_orchestrator`, `source_video_cleanup` 추가 (FR-017) | `test_audit_writer_stage_extension.py` (신규) |
| B-6 | spec 016 `services/takeout_ingest.py::ingest_takeout` | 시그니처 보존 (`takeout_dir`, `channel_alias`, `db_path`, `work_root`, `use_symlinks`, `dry_run`). 본 spec 의 unified_ingest 가 이 함수를 호출 | `test_unified_ingest_orchestrator.py::test_calls_ingest_takeout_with_existing_signature` |
| B-7 | spec 016 `IngestResult` 데이터 클래스 | 필드 보존 (`total_videos`, `new_videos`, `high/medium/ambiguous/unmapped_mappings`, `ignored_csv_count`, `mp4_present_count`, `mp4_absent_count`, `elapsed_seconds`). 본 spec 의 통합 처리 결과 요약이 IngestResult 를 그대로 포함 | `test_unified_ingest_orchestrator.py::test_summary_contains_ingest_result` |
| B-8 | spec 016 `data/<alias>/` 디렉토리 규약 | `channel_meta.json`, `videos_meta.json`, `동영상/` 심볼릭 링크 위치 보존. 본 spec 이 같은 디렉토리에 `retry_pending.json` 신규 추가 | `test_retry_manifest.py::test_manifest_file_under_alias_workdir` |
| B-9 | spec 003 alias 등록부 (`channels.json` + `departments.json`) | 두 등록부 union 검증 흐름 보존. 본 spec 의 `collect ingest` 도 alias 검증을 spec 016 의 `add-department` / `admin list` 와 같은 방식으로 진행 | `test_collect_ingest_contract.py::test_alias_mismatch_blocks_ingest` |
| B-10 | spec 009 OAuth 토큰 경로 (`~/.config/tube-scout/tokens/{alias}.json`) | 본 spec 은 OAuth 토큰을 사용하지 않음 (Takeout 단독 흐름). 토큰 부재가 통합 명령 실패 사유가 되지 않음 | `test_collect_ingest_contract.py::test_ingest_succeeds_without_oauth_token` |

각 boundary 의 검증 시나리오는 Phase 2 의 tasks.md 작성 시 실제 테스트 파일·메서드로 분해된다.

## Complexity Tracking

본 spec 은 Constitution Check 의 모든 gate 를 통과하며, justification 이 필요한 violation 0 건. Complexity Tracking 비움.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none)    | —          | —                                   |
