# Implementation Plan: unified_ingest 영구화 + 멱등 가드 (spec 017 PATCH)

**Branch**: `018-ingest-persist-idempotent` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/home/kjeong/localgit/tube-scout/specs/018-ingest-persist-idempotent/spec.md`

## Summary

spec 017 의 `collect ingest` 통합 명령이 T043 walkthrough 실측에서 **두 번째 호출도 14m36s** 가 소요됨이 확인되었다 — SC-004 멱등 약속의 절반 ("DB 영상 행 추가 0") 만 통과하고 자막·지문 재처리가 매 호출마다 반복되는 결함이다. 근본 원인은 `services/unified_ingest.py` 에서 (A) `transcribe_audio` 반환값 폐기 (line 100), (B) `extract_chromaprint_fingerprint` 반환값 폐기 (line 113), (C) 영상 루프의 멱등 가드 부재 (line 72) 라는 3 가지 휘발 결함이며, 세 결함이 사슬로 묶여 "결과를 어디에도 저장 안 함 → skip 결정도 못 함" 의 구조적 누락을 형성한다.

본 PATCH 는 spec 013 의 분리 명령 `collect transcripts` / `collect fingerprint` 가 이미 보유한 표준 영구화 패턴 (transcript json atomic write + `INSERT OR REPLACE` 지문 영구화 + DB SELECT 가드) 을 `unified_ingest.py` 에 이식하여 통합/분리 명령 산출물 schema 동치성을 회복하고, 멱등 호출 wall clock 을 14m36s → ≤ 2 초 로 단축한다. 22 학과 운영 환산 시 약 5 시간 24 분의 누적 GPU 시간 절감 효과가 직접 측정 가능하다.

설계 원칙은 "**신규 로직 도입 최소화**" 다 — ASR 정상성 점검 6 종 flag 는 `services/asr.py:detect_quality_flags` 가 이미 산출하므로 별도 검증 layer 를 추가하지 않고 단지 FR-018A 의 영구화 경로에 quality flag 가 자연스럽게 포함되도록 보장한다. 임시 WAV 정리는 `audio_extract.WavLifecycle` 가 보장 중이며 본 PATCH 는 손대지 않는다 (개인정보 보호 정책 유지). 영상 본체 (mp4) 의 `--delete-source` 두 단계 prompt 도 spec 017 의 동작을 그대로 인계한다.

## Technical Context

**Language/Version**: Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`).
**Primary Dependencies**: typer, rich, pydantic v2, polars, faster-whisper (≥1.0.0, `[asr]` optional extra), CTranslate2 4.x, ffmpeg/fpcalc (chromaprint). **신규 PyPI 의존성 0 건** — spec 013/017 의 기존 surface 안에서 완결.
**Storage**: SQLite v4 (스키마 변경 없음 — `audio_fingerprint`, `processing_status`, `quality_results`, `comparison_results`, `channel_metadata`, `video_metadata` 보존), JSON atomic write (`02_analyze/transcripts/<video_id>.json` 신규 적재 경로, `retry_pending.json` 보존), 감사 CSV (`audit_writer.py` 의 stage `ingest_orchestrator` 보존 + 신규 sub-reason `already_transcribed` / `already_fingerprinted`).
**Testing**: pytest 9.x + pytest-asyncio + pytest-cov + ruff. 단위 / 통합 / contract / 회귀 매트릭스 분리. 핵심 신규 회귀: `tests/integration/test_ingest_idempotent.py` (mock-only 한계 청산, real archive fixture 기반).
**Target Platform**: Linux (NixOS / Gentoo). 실측 baseline = RTX 3060 6 GB + 표준 PC, 간호학과 archive 9.9 GB / 9 mp4 / 2554 메타. 22 학과 환산은 선형 비례 가정.
**Project Type**: CLI 도구 (단일 프로젝트, `src/tube_scout/` + `tests/`).
**Performance Goals**: 본 PATCH 의 핵심 성능 목표는 멱등 호출 wall clock ≤ 2 초 (SC-018-1). 첫 호출 (fresh archive) 의 wall clock 은 spec 017 baseline (간호학과 9 mp4 / RTX 3060 / 약 14m36s) 을 그대로 유지하며 본 PATCH 가 회귀시키지 않는다. 멱등 hot path 의 ≤ 2 초 달성은 (i) 처리 대상 사전 평가로 faster-whisper 모델 로딩 자체 skip (FR-018E), (ii) WAV 디코딩 skip (FR-018E), (iii) DB SELECT + 파일 존재 체크 2 회의 시스템 콜만 발생 — 의 3 단 최적화로 보장한다.
**Constraints**: spec 017 의 SC-001 (적재 ≤ 60s), SC-005 (영상당 디코딩 1 회), C-1 (임시 WAV 즉시 정리), 멱등성 (spec 016 FR-009), 감사 append-only, 영상 삭제는 `--delete-source` + 두 단계 prompt 후에만 — 모두 회귀 없이 유지 (SC-018-7). 분리/통합 명령 산출물 schema-for-schema 동치성 유지 (SC-018-5 / FR-018H — top-level 키 + asr_quality_flags 6 종 + segment 객체 키 일치).
**Scale/Scope**: 자교 22 학과 × 평균 약 2,500 영상 메타 = 약 55,000 영상 메타. 본 PATCH 의 직접 측정은 1 학과 단위 (representative sample = 간호학과 9 mp4), 22 학과 환산은 SC-018-4 의 acceptance 조건이지만 22 학과 모두 실측을 강제하지 않음 (Assumption 명시).

## Constitution Check

*GATE: Phase 0 research 진입 전 + Phase 1 design 완료 후 두 번 점검.*

| Principle | Gate | 평가 | 비고 |
|---|---|---|---|
| I. Test-First (NON-NEGOTIABLE) | 모든 task RED → GREEN → REFACTOR 보장 | ✅ Pass | tasks.md 에서 각 FR 마다 failing 테스트 선행 작성. 핵심 회귀 `test_ingest_idempotent.py` 는 T013 의 mock-only 한계를 청산하여 real archive fixture 로 자막 json mtime + DB row count 둘 다 검증 (FR-018F) |
| II. Fail-Fast & Anti-Hallucination | `except: pass` 금지, `# [VERIFY]` 마커 해소 | ✅ Pass | DB schema 호환 검사 실패 시 자동 생성 금지 (Edge case 명시), `transcript_dir` 부재 시 mkdir -p 후 진입. `# [VERIFY]` 마커는 본 plan 에 0 건 (모든 표준 패턴이 spec 013 의 분리 명령 코드 위치 cli/collect.py:1931 + 2250 에서 그대로 검증됨) |
| III. Type Safety + Single Responsibility | 모든 public 함수 type annotation + Google docstring + 단일 책임 | ✅ Pass | `_run_transcript_and_fingerprint` 의 시그니처에 `force: bool` 파라미터 추가, 영구화 helper 와 멱등 가드 helper 를 단일 책임 함수 2 개로 분리 (`_persist_transcript` / `_check_already_processed`) |
| IV. CLI-First | 통합 흐름이 CLI 명령으로 노출 | ✅ Pass | `collect_ingest_command` 에 `--force` Typer 옵션 1 개만 신규 추가 (spec 013 `collect_fingerprint_command` 시그니처 일관) |
| V. Local-First Persistence | 외부 DB 서버 0, SQLite + JSON + Parquet 만 | ✅ Pass | 신규 영구화 위치 = `data/<alias>/02_analyze/transcripts/<video_id>.json` (JSON atomic write) + 기존 SQLite v4 `audio_fingerprint` 테이블 (`INSERT OR REPLACE`). 외부 store 도입 없음 |
| VI. Secrets via agenix (NON-NEGOTIABLE) | 시크릿 0건 신규 | ✅ Pass | 본 PATCH 는 OAuth / API key / 토큰 surface 를 전혀 건드리지 않음. spec 003 / 009 의 secrets 흐름 그대로 보존 |
| VII. Cross-Spec Boundary (NON-NEGOTIABLE) | Cross-Spec Boundaries 섹션 명시 + 각 경계에 acceptance | ✅ Pass | 본 plan 의 §Cross-Spec Boundaries 가 B-1 ~ B-6 enumerate. 각 boundary 에 spec 013 분리 명령 또는 spec 017 통합 명령 흐름과 함께 실행되는 acceptance scenario 가 명시됨 |

모든 gate 통과. Complexity Tracking 비움.

## Project Structure

### Documentation (this feature)

```text
specs/018-ingest-persist-idempotent/
├── plan.md              # 본 파일
├── research.md          # Phase 0 출력 (기술 결정 정리 + 표준 패턴 인용)
├── data-model.md        # Phase 1 출력 (entity 정의 — transcript artifact / idempotency guard / audit entry)
├── quickstart.md        # Phase 1 출력 (운영자 quickstart — 1 학과 walkthrough + 멱등 회귀 검증)
├── contracts/           # Phase 1 출력 (CLI / 데이터 schema contracts)
│   ├── collect-ingest-force.md   # `--force` 옵션 contract + retry_pending 상호작용
│   ├── transcript-artifact.md    # transcript json schema (분리/통합 명령 동치 검증)
│   └── idempotency-guard.md      # 영상별 멱등 가드 contract (자막 / 지문 독립 평가)
├── checklists/
│   └── requirements.md  # spec.md 작성 단계의 quality checklist (이미 작성됨)
└── tasks.md             # Phase 2 출력 (/speckit.tasks 단계 — 본 plan 의 범위 밖)
```

### Source Code (repository root)

```text
src/tube_scout/
├── models/
│   └── content.py                    # 변경 (선택) — TranscriptStageResult 에 skip_count 필드 추가
├── services/
│   ├── unified_ingest.py             # 변경 — _run_transcript_and_fingerprint 보강 (결함 A/B/C 해소)
│   │                                 #         + _persist_transcript, _check_already_processed 신규 helper
│   │                                 #         + 처리 대상 사전 평가로 model loading skip (FR-018E)
│   │                                 #         + Rich Table 5-row × 5-col 확장 (자막/지문 행에 skip 열, FR-018F)
│   ├── asr.py                        # 보존 — transcribe_audio 반환 surface 그대로 사용
│   ├── audio_extract.py              # 보존 — WavLifecycle 그대로 사용 (자막·지문 둘 다 skip 시 진입 안 함)
│   ├── audio_fingerprint.py          # 보존 — extract_chromaprint_fingerprint 그대로 사용
│   ├── audit_writer.py               # 변경 (선택) — ingest_orchestrator stage 에 `already_transcribed` / `already_fingerprinted` reason 어휘 추가
│   └── retry_manifest.py             # 보존 — `--force` 시 add_or_update_failures / resolve_successes 의 동작 변화 없음 (호출 입력만 다름)
├── storage/
│   └── content_db.py                 # 보존 — `audio_fingerprint` insert 함수 (`insert_audio_fingerprint`) 의 `INSERT OR REPLACE` 동작 확인 후 그대로 사용
└── cli/
    └── collect.py                    # 변경 — `collect_ingest_command` 에 `--force` Typer 옵션 추가 + help text 보강

tests/
├── unit/
│   ├── test_unified_ingest_persist.py        # 신규 — FR-018A/B 영구화 단위 테스트 (transcript json + DB row)
│   ├── test_unified_ingest_idempotent.py     # 신규 — FR-018C 멱등 가드 단위 (각 단계 독립 평가)
│   └── test_unified_ingest_force.py          # 신규 — FR-018D `--force` 단위 (가드 우회 + retry 자동 해소)
├── integration/
│   ├── test_ingest_idempotent.py             # 변경 — spec 017 의 mock-only 회귀를 real archive fixture 로 보강 (FR-018F)
│   ├── test_ingest_persist_schema_equiv.py   # 신규 — FR-018H 분리/통합 schema 동치 (SC-018-5)
│   ├── test_ingest_model_load_skip.py        # 신규 — FR-018E faster-whisper 모델 로드 skip (SC-018-1 의 ≤ 2 초)
│   └── test_ingest_force_full_cycle.py       # 신규 — `--force` + retry_pending 상호작용 (SC-018-3)
└── contract/
    ├── test_collect_ingest_force_contract.py # 신규 — `--force` CLI contract (exit code / help text)
    ├── test_transcript_artifact_contract.py  # 신규 — transcript json schema contract (분리/통합 schema 동치)
    └── test_idempotency_guard_contract.py    # 신규 — 자막/지문 가드 독립 평가 contract
```

**Structure Decision**: 단일 프로젝트 구조 (Option 1) 유지. **신규 모듈 0 건** — 본 PATCH 는 `services/unified_ingest.py` 내부의 helper 함수 2 개 신규 + 기존 함수 1 개 보강 + `cli/collect.py` 의 옵션 1 개 추가로 완결된다. 모든 신규 코드는 기존 모듈 안에서 흡수되어 spec 017 의 구조를 유지하면서 결함 3 건만 surgical 하게 해소한다. 신규 테스트는 unit 3 + integration 4 + contract 3 = 총 10 개 (T013 의 mock-only 한계 청산용 integration 1 개는 변경, 나머지는 신규).

## Cross-Spec Boundaries (Principle VII)

본 PATCH 는 다음 prior spec / 시스템의 경계를 명시적으로 보존하거나 새로 정의한다.

| # | Boundary | Prior 측 | 본 PATCH 의 가정 / 신규 production | 검증 시나리오 |
|---|---|---|---|---|
| B-1 | spec 013 분리 명령 `collect transcripts` | transcript json 영구화 위치 = `data/<alias>/02_analyze/transcripts/<video_id>.json`, schema 키 = (video_id, source, language, duration, segments, asr_quality_flags, fetched_at), atomic write = `tempfile.mkstemp` + `os.replace` (cli/collect.py:2249-2295) | 통합 명령이 동일 위치·동일 schema·동일 atomic 패턴으로 영구화. schema-for-schema 동치 (FR-018H) | `test_ingest_persist_schema_equiv.py` — 분리 명령으로 1 학과 적재 + 통합 명령으로 다른 학과 적재 후 transcript json 키 집합 diff = 0 |
| B-2 | spec 013 분리 명령 `collect fingerprint` | `audio_fingerprint` 테이블 schema = (video_id PK, fingerprint blob, duration_seconds, fetched_at), `INSERT OR REPLACE` upsert 패턴 + `SELECT 1 FROM audio_fingerprint WHERE video_id=?` 멱등 가드 (cli/collect.py:1931-1956) | 통합 명령이 동일 SQL 패턴 + 동일 테이블 사용. row 컬럼셋 schema-for-schema 동치 (FR-018H) | `test_idempotency_guard_contract.py` — 분리/통합 명령 양쪽이 같은 video_id 에 대해 PK 단일성 유지 (`SELECT COUNT(*) WHERE video_id=?` = 1) |
| B-3 | spec 017 `WavLifecycle` (`services/audio_extract.py:72-104`) | context manager 가 `__exit__` 에서 무조건 `cleanup_wav` 호출 (성공/실패 무관), `keep=False` 기본값 | 본 PATCH 는 `WavLifecycle` 자체를 손대지 않음. 단 멱등 가드 도입으로 자막·지문 둘 다 skip 인 영상은 context 진입 자체를 회피 → WAV 디코딩 0 회 (SC-005 강화) | `test_ingest_model_load_skip.py` — 멱등 hot path 에서 `wav_dir` 디렉토리 내 `*.wav` 파일이 호출 시점·종료 시점 양쪽 모두 0 개 |
| B-4 | spec 017 `retry_manifest.py` (`add_or_update_failures` / `resolve_successes`) | retry_pending.json 의 entries 가 video_id 단위 키, attempts 카운터, last_failure_reason 보존. `select_retry_targets(max_attempts=5)` 가 우선 재시도 ID 반환 | 일반 호출 (no `--force`): 멱등 가드를 통과한 영상만 매니페스트 갱신 대상. `--force` 호출: 전체 영상이 대상 — 성공한 영상은 자동 해소, 새 실패는 추가/유지 (FR-018D) | `test_ingest_force_full_cycle.py` — fresh + retry entries 9 개 있는 archive 에 `--force` 호출 후 retry_pending.json 의 (a) 신규 실패 row 갱신 (b) 성공 row 제거 양쪽 검증 |
| B-5 | spec 017 `audit_writer.py` (stage `ingest_orchestrator`) | append-only 감사 CSV, video_id 별 1 row, reason 어휘 통제 | 본 PATCH 는 reason 어휘에 `already_transcribed`, `already_fingerprinted` 2 개 신규 추가. action 컬럼은 기존 `success` / `fail` 외에 `skip` 가 사용됨 (이미 spec 013 분리 명령에서 사용 중) | `test_collect_ingest_force_contract.py` — 멱등 호출 후 CSV 의 reason 컬럼에서 두 어휘 등장 횟수 = (자막 skip 수 + 지문 skip 수) |
| B-6 | spec 011 (재사용 탐지) 입력 reader | transcript json + `audio_fingerprint` row 를 입력 권위로 소비. `asr_quality_flags` 6 종 flag 는 후속 신뢰도 평가에 사용 (spec 013 FR-018) | 본 PATCH 는 spec 011 의 입력 reader 가 분리·통합 어느 경로의 산출물이든 분기 없이 소비하도록 schema 동치 보장 (FR-018H) | `test_transcript_artifact_contract.py` — spec 011 의 reader 가 분리/통합 산출물 양쪽을 분기 없이 로드 (`json.load` + dict 키 비교) |

모든 boundary 에 1 개 이상의 acceptance 시나리오가 매핑되어 있다 (Principle VII 충족).

## Complexity Tracking

> Constitution Check 모든 gate 통과 (Pass × 7). Complexity Tracking 항목 없음.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (없음) | — | — |
