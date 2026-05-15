# Implementation Plan: Takeout 적재 모듈 재작성 및 운영자 등록 흐름 정합화

**Branch**: `016-takeout-ingest-rebuild` | **Date**: 2026-05-15 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/016-takeout-ingest-rebuild/spec.md`

## Summary

본 spec 은 v0.5.0 의 spec 013 가 도입한 Takeout 적재 모듈이 실데이터(`data/takeout-20260511T130817Z-3-001/`, 간호학과 9 mp4 + 채널 전체 2554 영상 메타) 검증 시 첫 1초 안에 차단되는 결함 11 개를 PATCH 단위로 수정한다. 동시에 신규 사용자 기능 0건 / 결함 수정 17 건 / 옵션 완화 2 건 / deprecation 2 건 / 멱등성 보강 2 건의 분포로 SemVer PATCH (v0.5.0 → v0.5.1) 가 적용된다.

기술 접근 요지는 다음 네 갈래로 묶인다.

1. **`services/takeout_ingest.py` 의 내부 파싱·매핑·검증 로직 재작성** — 외부 함수 시그니처(B-3, B-5)는 보존, csv 컬럼 실측 헤더 적용, privacy 한글-영어 매핑, glob 패턴 정확화, mp4 부재 영상 audit 으로 표현. `_parse_channel_csv()`, `parse_takeout_csv_metadata()`, `ingest_takeout()` 3 함수를 RED-GREEN-REFACTOR 로 재작성한다.
2. **`cli/admin.py` 의 `add-department` 와 `list` 의 흐름 정합화** — OAuth env 3 옵션을 모두 optional 로 변경, `list` 가 `channels.json` + `departments.json` union 출력 + consistency 컬럼 + JSON 필드 + stderr WARNING.
3. **`cli/collect.py` 의 `transcripts --source youtube` deprecation 차단** — exit 2 + 명확 메시지. 기본값을 ASR 단일 경로로.
4. **회귀 테스트 + 측정 의무화** — 결함 1·2·3·4·6·7·8·11 의 8 개 회귀 테스트(failing → passing) 작성. IngestResult 에 `elapsed_seconds`, audit row 에 `elapsed_ms` 추가하여 plan 첫 task 에서 baseline 측정 후 정량 임계는 별도 검증 기준으로 추가.

검증 환경은 NVIDIA RTX 3060 (6 GB) + faster-whisper 1.2.1 + CTranslate2 4.7.1 으로 이미 확인되었으며, large-v3 보다 작은 medium 모델까지 안전하다. 22 학과 × 수만 영상 단위 본격 적재는 별도 GPU 서버에서 수행하고 본 작업 머신은 검증·개발 용도로만 사용한다.

## Technical Context

**Language/Version**: Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`)
**Primary Dependencies**: typer, rich, pydantic v2, polars, faster-whisper (≥1.0.0, [asr] optional extra), CTranslate2 4.x, ffmpeg (chromaprint 패키지에 동봉). agenix 환경변수는 OAuth 흐름에서만 선택적 사용. **신규 PyPI 의존성 0건** — 기존 [asr] / [dev] / 기본 surface 안에서 모두 처리.
**Storage**: SQLite v4 (스키마 변경 없음 — spec 013 의 channel_metadata + video_metadata + processing_status + quality_results + comparison_results 보존), JSON atomic write (channel_meta.json, videos_meta.json, channels.json, departments.json), 적재 audit CSV (`audit_writer.py` 의 stage `takeout_ingest`).
**Testing**: pytest (TDD RED-GREEN-REFACTOR), pytest-asyncio, pytest-httpx (web admin), pytest-cov. 본 spec 의 회귀 테스트는 결함 8 개 × failing-then-passing 매트릭스 + 측정/audit 컬럼 존재 검증.
**Target Platform**: Linux (NixOS / Gentoo), Python 3.11 pinned. macOS 미지원, Windows 미지원. 검증 환경 = RTX 3060 (6 GB) + 표준 PC.
**Project Type**: CLI tool (Typer). `cli/`, `services/`, `models/`, `storage/`, `reporting/`, `visualization/`, `web/` 6 모듈 그룹. 본 spec 은 그중 `cli/admin.py`, `cli/collect.py`, `services/takeout_ingest.py`, `services/audit_writer.py`, `web/repo/departments_repo.py` 만 수정.
**Performance Goals**: 본 작업 머신(표준 PC + RTX 3060 6 GB) 기준 9 mp4 + 2554 메타 archive 적재 SLA = dry-run ≤ 1770 s (~30 분) · real ingest ≤ 1820 s (~30 분). 안전 마진 1.5× 가 baseline 평균(dry 1180 s, real 1213 s)에 곱해진 값. archive walk(mp4 본체 10 GB 디스크 read)가 wall clock 을 지배하며 SQLite INSERT 시간은 미미. 측정 근거 = `_workspace/spec016_polish_baseline.md` (T063). 가용성 기준은 SC-001 (간호학과 9 mp4 + 2554 메타 archive 적재가 처음부터 끝까지 0 exit code 로 완주).
**Constraints**: PATCH 범위 유지 (새 기능 0 건, 새 모듈 0 건, 새 SQLite 컬럼 0 건). 모든 변경은 spec 003/008/013 의 시그니처와 스키마를 보존. 변경 표면은 Cross-Spec Boundaries 표의 B-3, B-5, B-7 의 "본 spec 의 가정 / 새로 생산하는 것" 열에 한정.
**Scale/Scope**: 한 학과 = 2554 영상 (간호학과 실측). 22 학과 전체 = 수만 영상. archive part 1 묶음당 9 mp4 (검증 데이터 기준). 영상 본체와 메타 단위가 분리되어 한 archive 적재 단계의 데이터 크기는 메타 csv 약 400KB + mp4 본체 약 10 GB.

## Constitution Check

*GATE: Phase 0 research 진입 전 통과 의무. Phase 1 design 완료 후 재검증.*

### Pre-Phase 0 Constitution Check

| 원칙 | 결과 | 본 spec 의 준수 방식 |
|---|---|---|
| I. Test-First Development (NON-NEGOTIABLE) | PASS | SC-008 가 결함 8 개 모두에 대해 "failing → passing 회귀 테스트" 작성을 요구. 모든 FR 이 acceptance scenario 와 1:1 매핑되어 RED 단계 테스트가 spec 본문에서 직접 도출됨. tasks 단계에서 각 결함별로 "테스트 작성 (RED) → 코드 수정 (GREEN) → REFACTOR" 3 stage 로 분할. |
| II. Fail-Fast Discipline & Anti-Hallucination | PASS | FR-005 (알 수 없는 한글 privacy 값 → audit + skip), FR-006 (silent fail 금지), FR-013 (OAuth env 일부 명시 시 명시적 오류), FR-018 (`--source youtube` exit 2). 모든 에러 메시지는 English (Korean 은 user-facing CLI 출력에만). `_check_envs_present()` 기존 로직은 spec 003 호환 흐름에서 유지. |
| III. Type Safety & Single Responsibility | PASS | 본 spec 의 모든 코드 수정은 기존 Python 타입 어노테이션 + Google-style docstring 을 유지·강화. `ingest_takeout()` 의 단일 책임 (1 archive → IngestResult) 은 보존. `_parse_channel_csv()` 와 `parse_takeout_csv_metadata()` 가 각각 단일 csv 파일 / 단일 csv 폴더 책임. |
| IV. CLI-First Architecture | PASS | 모든 변경 표면이 Typer CLI 명령: `tube-scout collect takeout`, `tube-scout admin add-department`, `tube-scout admin list`, `tube-scout collect transcripts`. 웹 UI (spec 008) 는 thin layer 로 channels.json / departments.json 을 읽기만 하므로 본 spec 의 union 출력 + alias 검증 흐름이 동일하게 노출됨. |
| V. Local-First, External-DB-Free Persistence | PASS | SQLite v4 스키마 보존. JSON atomic write (channel_meta.json, videos_meta.json) 보존. 외부 DB 의존 0 건. |
| VI. Secrets via agenix Only (NON-NEGOTIABLE) | PASS | OAuth env 3 종 (TUBE_SCOUT_*) 은 spec 003 호환 흐름에서만 검증되고, Takeout 단독 흐름에서는 모두 optional. departments.json 에 env 변수 "이름" 만 저장되고 실제 값은 agenix 가 환경에 주입. 코드/저장소에 비밀이 들어가지 않음. |
| VII. Cross-Spec Boundary Discipline (NON-NEGOTIABLE) | PASS | spec.md 에 명시적 ## Cross-Spec Boundaries 섹션 (B-1 ~ B-8) 추가. 각 boundary 는 (1) prior spec 측 보장, (2) 본 spec 의 가정 / 새로 생산, (3) 경계 검증 acceptance scenario 의 3 열로 enumerate. 모든 boundary 가 적어도 하나의 User Story acceptance scenario 로 검증됨. |

**Verdict**: 7/7 원칙 모두 PASS. Complexity Tracking 절은 비어 있다 (해당 사항 없음).

### Post-Phase 1 Constitution Check

Phase 1 산출물 작성 후 재검증. 본 plan.md 의 §"Post-Design Constitution Check" (최하단) 에 기록한다.

## Project Structure

### Documentation (this feature)

```text
specs/016-takeout-ingest-rebuild/
├── plan.md              # 본 파일 (/speckit.plan output)
├── spec.md              # 사양 (/speckit.specify + /speckit.clarify output)
├── research.md          # Phase 0 output (모든 NEEDS CLARIFICATION 해소)
├── data-model.md        # Phase 1 output (Entity 7 + SQLite v4 보존 + state transition)
├── quickstart.md        # Phase 1 output (간호학과 9 영상 운영자 quickstart)
├── contracts/           # Phase 1 output (4 CLI 명령 contract)
│   ├── collect-takeout.md
│   ├── admin-add-department.md
│   ├── admin-list.md
│   └── collect-transcripts.md
├── checklists/
│   └── requirements.md  # /speckit.specify quality checklist
└── tasks.md             # /speckit.tasks 가 생성 (본 plan 단계 외)
```

### Source Code (repository root)

본 spec 은 PATCH 범위라 신규 모듈/디렉토리 생성 없음. 변경 표면만 다음 7 개 경로로 한정.

```text
src/tube_scout/
├── cli/
│   ├── admin.py             # 수정 — add-department OAuth env 3 옵션 optional 화 (FR-012/013), list union 출력 + consistency 컬럼 + stderr WARNING (FR-014/015)
│   └── collect.py           # 수정 — transcripts --source youtube exit 2 차단 (FR-018), --source asr 기본값 (FR-017)
├── services/
│   ├── takeout_ingest.py    # 사실상 재작성 — 결함 3·4·6·7·8 (FR-001~007, FR-009~011) + IngestResult elapsed_seconds (FR-022)
│   └── audit_writer.py      # 부분 수정 — reason 어휘 추가 (no_mp4_in_archive, unknown_privacy_value 등) + elapsed_ms 컬럼 (FR-023, B-5)
├── web/repo/
│   └── (없음 — departments_repo.py 수정 불필요. add-department 흐름 자체에서 OAuth env null 허용을 통해 자동 작동)
└── models/
    └── content.py            # 부분 수정 — VideoMetadata.privacy_status validator 가 영어 표준값만 허용, ChannelMetadata 동일

tests/
├── unit/
│   ├── test_takeout_ingest.py        # 신규/확장 — 결함 3·4·6·7·8 회귀 매트릭스
│   ├── test_admin_add_department.py  # 신규/확장 — 결함 2·11 + alias 일관성 (FR-016)
│   ├── test_admin_list_union.py      # 신규 — 결함 1 + FR-014/015
│   └── test_privacy_mapping.py       # 신규 — FR-005 + unknown 값 처리
├── integration/
│   ├── test_takeout_e2e_nursing.py   # 신규 — SC-001/002/005/007 cross-stack 검증
│   ├── test_idempotent_part_load.py  # 신규 — US 3 멱등성 (FR-009/020)
│   └── test_asr_single_source.py     # 신규 — US 4 / FR-017/018/019
└── contract/
    ├── test_collect_takeout_contract.py
    ├── test_admin_add_department_contract.py
    ├── test_admin_list_contract.py
    └── test_collect_transcripts_contract.py
```

**Structure Decision**: spec 013 의 기존 단일-프로젝트 구조 (`src/tube_scout/{cli,services,models,storage,reporting,visualization,web}`) 를 보존. 본 spec 의 모든 변경은 그중 4 파일 (cli/admin.py, cli/collect.py, services/takeout_ingest.py, services/audit_writer.py, models/content.py) 에 한정되며, 새 디렉토리 / 새 모듈 / 새 의존성 0 건이다. tests/ 트리에는 결함 회귀 매트릭스를 unit/integration/contract 세 레이어로 분산 배치.

## Complexity Tracking

해당 사항 없음. Constitution Check 7/7 PASS, 위반 0 건.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| (없음) | — | — |

## Phase 0 — Research

Spec.md 의 Assumptions 7 건 + Clarifications 4 건이 모든 ambiguity 를 이미 해소했다. 본 spec 의 Technical Context 에는 NEEDS CLARIFICATION 마커 0 개. Phase 0 research 의 출력 `research.md` 는 각 결정사항을 Decision/Rationale/Alternatives 형식으로 정리하는 단계로 제한된다. 별도 외부 dependency 조사는 불필요.

## Phase 1 — Design & Contracts

Phase 1 산출물:

1. `data-model.md` — Key Entities 7 종 + SQLite v4 스키마 보존 확인 + privacy_status validator 의 영어 표준값 enum 제약 + state transition (`fresh → ingested → mp4_present|mp4_absent`).
2. `contracts/` — CLI 명령 4 개의 입력 옵션, 출력 형식, exit code, audit row, 에러 케이스 명시.
3. `quickstart.md` — 간호학과 9 영상 archive 적재의 운영자 quickstart (학과 등록 → archive 적재 → ASR → 비정합 검증).
4. agent context 갱신 — `.specify/scripts/bash/update-agent-context.sh claude` 가 `CLAUDE.md` 의 "Recent Changes" 와 "Active Technologies" 절을 자동 갱신.

## Post-Design Constitution Check

Phase 1 산출물 (`data-model.md`, `contracts/collect-takeout.md`, `contracts/admin-add-department.md`, `contracts/admin-list.md`, `contracts/collect-transcripts.md`, `quickstart.md`, `CLAUDE.md` 갱신) 작성 완료 후 재검증 결과.

| 원칙 | 결과 | Phase 1 산출물에서의 확인 |
|---|---|---|
| I. Test-First Development (NON-NEGOTIABLE) | PASS | quickstart §4 가 회귀 테스트 8 개 (`test_takeout_ingest.py` 등) 의 실행 명령을 명시. 각 contract 의 acceptance scenario 가 그대로 pytest test case 로 1:1 매핑됨. tasks 단계 진입 시 RED 단계 테스트가 즉시 작성 가능. |
| II. Fail-Fast Discipline & Anti-Hallucination | PASS | contracts/collect-takeout.md 의 "Error cases" 표 8 개 케이스 모두 명확한 영어 stderr 메시지 + exit 1. data-model.md 의 ChannelMetadata/VideoMetadata validator 가 silent fail 금지 명시. contracts/collect-transcripts.md 의 `--source youtube` deprecation 도 silent fallback 없이 exit 2. |
| III. Type Safety & Single Responsibility | PASS | data-model.md 의 모든 Pydantic 모델이 명시적 type 어노테이션 + enum 제약 + Google-style docstring 가능 형태. 변경 표면 4 파일 (`cli/admin.py`, `cli/collect.py`, `services/takeout_ingest.py`, `services/audit_writer.py`, `models/content.py`) 각각 단일 책임 유지. |
| IV. CLI-First Architecture | PASS | 4 개 contract 파일이 모두 Typer CLI 명령 진입점. 웹 UI 흐름이 별도 contract 로 갈라지지 않고 spec 008 의 thin layer 위에서 자연스럽게 작동. |
| V. Local-First, External-DB-Free Persistence | PASS | data-model.md §"SQLite v4 Schema 보존 확인" 가 외부 DB 미사용 + 스키마 변경 없음 명시. JSON atomic write 흐름 유지. |
| VI. Secrets via agenix Only (NON-NEGOTIABLE) | PASS | contracts/admin-add-department.md 의 조합 A (Takeout 단독, env 3 개 모두 생략) + 조합 B (spec 003 호환, env 3 개 모두 명시) 가 비밀 파일 직접 저장 없이 환경변수만 참조하는 흐름 보존. 코드/저장소에 비밀 0 건. |
| VII. Cross-Spec Boundary Discipline (NON-NEGOTIABLE) | PASS | spec.md §"Cross-Spec Boundaries" (B-1 ~ B-8) 의 모든 boundary 가 contracts/ 4 개 + data-model.md 의 해당 단락에서 인용되고, quickstart §0.5/§1/§3 의 acceptance scenario 가 boundary 검증 행위를 직접 수행. |

**Post-Design Verdict**: 7/7 PASS, Complexity Tracking 위반 0 건. Phase 0 의 PASS 결정이 Phase 1 산출물에서 모두 유지됨.

## Phase 2 진입 준비 완료

`/speckit.tasks` 명령으로 다음 산출물 진입 가능:

- `tasks.md` — TDD-ordered 구현 task 목록. 각 task 가 RED-GREEN-REFACTOR 3 stage + (필요시) auditor / pair-programmer / adversary hand-off 분기를 포함.

본 plan 의 §"Project Structure / Source Code" 의 변경 표면 (cli/admin.py + cli/collect.py + services/takeout_ingest.py + services/audit_writer.py + models/content.py 5 파일) 과 tests/ 트리의 회귀 매트릭스가 task 단위로 분해될 예정이다.
