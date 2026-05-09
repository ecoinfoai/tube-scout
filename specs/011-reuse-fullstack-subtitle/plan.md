# Implementation Plan: Subtitle Full-Stack Reuse Detection (nC2 + Time-axis + 4-Layer Defense)

**Branch**: `011-reuse-fullstack-subtitle` | **Date**: 2026-05-09 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/011-reuse-fullstack-subtitle/spec.md`

## Summary

spec 007의 default 매칭(같은 교수·교과목·주차·차시)을 보존하면서, (1) 같은 교수의 caption pool을 채널 경계를 넘어 통합하고 nC2 모든 쌍을 비교하는 `M-nC2` 매칭 모드, (2) 시간축 지표 I-6(최장 연속 일치)/I-7(분포)/I-8(위치 다양성), (3) 4계층 false-positive 방어(Layer A 길이 컷 / Layer B per-professor stylistic baseline / Layer C 점진 진화 등급 demote / Layer D pair+phrase whitelist), (4) 4 재활용 패턴 분류(통째/분산 × 동일주/다른주)를 추가한다. 모든 분석은 100% 로컬 처리이며, 영속은 spec 007 SQLite·Parquet·JSON 패턴을 확장한다(외부 DB 금지). 대규모 nC2 분석(200 영상 ≈ 19,900 쌍)은 per-pair checkpoint로 야간 무인 실행을 가능하게 한다.

## Technical Context

**Language/Version**: Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`)
**Primary Dependencies**: typer, rich, pydantic v2, polars, sentence-transformers (spec 007 인계), jinja2, plotly, openpyxl. **신규 0건** — 기존 의존성 surface 안에서 충분.
**Storage**: 기존 spec 007 `02_analyze/content/content_reuse.db`(SQLite) + `embeddings.parquet`(polars) + caption JSON. 신규 테이블 6개(`professor_pool`, `professor_pool_membership`, `baseline_corpus`, `phrase_whitelist`, `pair_checkpoint`, `match_spans`) + 메타 1개(`_schema_version`) 추가, 기존 `comparison_results` ALTER 10개 컬럼, 신규 storage 엔진 도입 없음. 정책 임계는 `02_analyze/content/policy.yaml` 외부 파일.
**Testing**: pytest (TDD 의무 — Constitution Principle I). 단위·integration·adversary 3계층.
**Target Platform**: Linux (NixOS), CLI tool (운영자 워크스테이션 + cron). Spec 014 web UI는 후속 spec; 본 spec은 service 계층까지만 노출.
**Project Type**: Single project (CLI). `src/tube_scout/` 기존 트리에 모듈 추가.
**Performance Goals**:
- 한 교수 200 영상 / 19,900 쌍 nC2 분석: 30분 (SC-001)
- 22채널 ≈ 4,000 영상 풀 분석: 야간 무인 1회 실행 (SC-006)
- 4 패턴 분류 정확도 95% (SC-002), Layer B 흡수 ≥90% (SC-004), composite score 인간 판단 일치 90% (SC-007)
**Constraints**:
- Layer A 사전 필터로 시간축 지표 계산 대상 쌍 수 축소 (200C2 = 19,900 → 1차 후보 수천)
- Per-pair checkpoint로 어떤 중단 시점에서도 재개 (FR-031)
- 활성 admin 1인 가정, 동시 쓰기 시 advisory lock으로 두 번째 거부 (FR-033)
- Caption 수집 자체는 spec 010의 `--prefer-captions-api` + skip-existing 인계 (본 spec은 caption acquisition 비포함)
**Scale/Scope**:
- 22채널, 약 4,000 영상, 약 30 교수, 5년 누적
- 한 교수 평균 ≈ 130 영상, 최대 ≈ 200 영상 (위 SC-001 budget 산정 기준)
- 운영 1인 (DX센터장) — Constitution Principle 5 + spec 007 inheritance

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.0 — 7 principles. 본 plan의 적합성 평가:

| 원칙 | 적합성 | 평가 |
|---|---|---|
| I. Test-First (NON-NEGOTIABLE) | ✅ PASS | tasks 단계에서 RED→GREEN→REFACTOR 순서 강제. 새 33 FR (FR-001~FR-033) 각각에 대응되는 contract / unit / integration 테스트가 구현 전 작성된다. |
| II. Fail-Fast & Anti-Hallucination | ✅ PASS | 모든 신규 service 함수는 Pydantic 모델 입력 검증, fail-fast 분기, 영문 에러 메시지. caption pool에 등록되지 않은 professor 매핑이면 명시적 ValueError. `# [VERIFY]` 마커는 plan 시점 0건 — 모든 의존성은 기존 surface 내. |
| III. Type Safety & SRP | ✅ PASS | 신규 함수 전원 Python type hints + Google-style English docstrings. `services/` 모듈은 단일 책임(matcher, time_axis_indicators, layer_defense, whitelist, baseline_corpus 분리). cross-layer leakage 방지를 위해 storage 호출은 service 내부에서만. |
| IV. CLI-First Architecture | ✅ PASS | 모든 신규 능력은 `tube-scout content` 하위 명령(`scan --mode nc2`, `whitelist`, `baseline`)으로 노출. spec 014 web UI는 동일 service 함수를 호출 (재구현 금지). |
| V. Local-First, External-DB-Free | ✅ PASS | 신규 storage 엔진 0개. 기존 SQLite (`content_reuse.db`) + Parquet + JSON 안에서 테이블 추가. PostgreSQL/MongoDB/Redis 도입 없음. |
| VI. Secrets via agenix Only (NON-NEGOTIABLE) | ✅ PASS | 본 spec은 신규 secret 0개. OAuth 토큰은 spec 009 device flow의 `~/.config/tube-scout/tokens/{alias}.json` 인계, 본 spec에서 caption acquisition 호출 0회 (spec 010 산출물만 소비). 코드 / 테스트 / 산출물에 plaintext secret 없음. |
| VII. Cross-Spec Boundary Discipline (NON-NEGOTIABLE) | ⚠ ACTION REQUIRED | spec.md 현재 "Cross-Spec Boundaries" section 부재. **Phase 1에서 spec.md에 해당 section 추가 의무** (constitution 1.1.0 mandate). 본 plan의 §"Cross-Spec Boundaries"에 boundary catalog 사전 정리 후 spec.md 반영. |

**Gate 결과 (Phase 0 pre-research)**: I~VI PASS, VII는 Phase 1에서 spec.md에 boundary section 추가로 충족 예정. Phase 0 research 진행 가능.

**Gate 결과 (Phase 1 post-design)**: I~VI 변경 없이 PASS 유지. **VII PASS** — spec.md `### Cross-Spec Boundaries` section이 추가되어 B-1~B-10 10개 경계가 모두 (a) 사전 측 보장, (b) 신규 가정/산출, (c) 검증 acceptance 매핑으로 명시됨. data-model.md, contracts/(cli_content.md, service_layer.md, db_schema.md), quickstart.md 모두 동일 boundary 표를 ground truth로 인용. Phase 2 (`/speckit.tasks`) 진행 가능.

### Cross-Spec Boundaries (Principle VII 사전 카탈로그)

| # | 상대 spec / 시스템 | 공유 자산 | 사전 측 보장 | 본 spec 가정 / 신규 산출 | 검증 acceptance |
|---|---|---|---|---|---|
| B-1 | spec 003 multichannel-admin | `channels.json` 별칭 레지스트리, `--channel <alias>` CLI flag | 별칭 → channel_id 매핑은 spec 003이 권위 | 본 spec은 별칭만 받아 spec 003 레지스트리에서 channel_id 해석 (직접 조회 금지). 신규: 같은 alias 풀에 여러 교수 공존 시 `(channel_alias, author/professor)` → professor_id 매핑 테이블 추가 | US1 #5 + boundary 시나리오: 새 alias 등록 → professor mapping 자동 prompt → nC2 풀 산정 |
| B-2 | spec 007 content-reuse-detection | `content_reuse.db` (processing_status, fingerprint_hashes, comparison_results, quality_results), `embeddings.parquet`, `02_analyze/content/` 디렉터리 | spec 007 schema·indicator 산출은 권위. fingerprint·embedding은 변경 금지 | 본 spec은 (a) `comparison_results`에 컬럼 ALTER (i6/i7/i8/pattern/baseline_subtracted/layer_attribution), (b) 신규 테이블 4개(`baseline_corpus`, `phrase_whitelist`, `professor_pool`, `pair_checkpoint`) 추가. spec 007 review_status enum 확장(PENDING 추가) | FR-026 backward 호환: spec 007 데이터로 spec 011 분석 실행 시 caption 재수집·embedding 재산출 0건 (US1 #3 + SC-009) |
| B-3 | spec 010 prefer-captions-resume | `01_collect/transcripts/{video_id}.json` JSON 자막, `transcripts_audit.csv` | spec 010이 자막 수집 idempotent 보장 | 본 spec은 자막 수집 호출 0회 (read-only consume). 누락 자막 발견 시 `transcripts_audit.csv` 참조 + 명확한 메시지("run `tube-scout collect transcripts --channel <alias>`")로 fail-fast | quickstart 시나리오: 자막 미수집 영상 포함된 풀에서 nC2 실행 → 명시적 메시지 + non-zero exit |
| B-4 | spec 002/004/006 reporting | `03_report/` 출력 트리, `bundle_report.py`, plotly/jinja2 templates | 기존 report bundling은 권위 | 본 spec은 (a) `03_report/content/` 하위에 4 패턴 분리 HTML, (b) Excel 탭 추가(whitelist sheet, baseline sheet), (c) 시간축 visualization는 plotly-static. 기존 보고서는 변경 금지 | US5 acceptance: 단일 `tube-scout report content` 명령으로 spec 007 + spec 011 결과를 한 번에 번들 |
| B-5 | spec 008 admin-web-ui | `tube-scout-admin` web 서비스 service-layer 호출 | 본 spec의 service 함수 시그니처 안정 | 신규 service-layer 공개 함수 명세를 contracts/ 에 동결. spec 008 (그리고 후속 spec 014) 은 CLI 레이어 우회하지 않고 동일 service 호출 | contract 테스트: spec 008 web 라우트가 직접 import해서 호출하는 모든 함수가 contracts/ 와 서명 일치 |
| B-6 | spec 009 runtime-auth-fix | `~/.config/tube-scout/tokens/{alias}.json`, `resolve_channel_alias()` | 별칭 인증 권위 | 본 spec은 자막 수집 호출 0이므로 token 사용 0. 다만 nC2 풀 정의 시 `resolve_channel_alias()` 재사용 (직접 channels.json 파싱 금지) | 모든 신규 CLI는 `--channel <alias>` flag만 받고 내부에서 spec 009 helper 사용 |
| B-7 | 출력 디렉터리 컨벤션 | `projects/{job-id}/{01_collect,02_analyze,03_report}` (`{job-id} = YYYYMMDD-HHMMSS[-N]`) | Constitution Principle V | 본 spec은 `02_analyze/content/v2/` 하위 subdir 사용 (v2 = spec 011 schema). 기존 spec 007 산출물(`02_analyze/content/`)은 그대로 유지 | quickstart: 같은 project_dir에서 spec 007 분석 + spec 011 분석 모두 실행, 두 디렉터리 공존 |
| B-8 | spec 014 UI redesign (future) | spec 011 service 계층 + DB schema | 본 spec은 backend 산출물 안정 | (a) review state mutation API, (b) phrase whitelist mutation API, (c) baseline phrase mutation API 함수 시그니처는 `contracts/web_service_layer.md` 에 정의 → spec 014가 binding | spec 014 specify 시 본 contracts 파일 직접 인용 |
| B-9 | agenix secret store | (해당 없음) | — | 본 spec 신규 secret 0개 | — |
| B-10 | Constitution Principle II 영문 에러 | 모든 신규 에러 메시지 영문 | — | 모든 신규 raise 영문 + 운영자 actionable instruction (예: 누락 baseline corpus → `"No baseline corpus for professor <id>; run \`tube-scout content baseline bootstrap --professor <id>\` first"`) | adversary 테스트: 누락 자막·누락 매핑·누락 baseline에 대한 모든 에러 메시지 영문 + actionable 검증 |

위 10건 중 B-1, B-2, B-3, B-4, B-5, B-6, B-7, B-8, B-10 은 이행 의무. **Phase 1에서 spec.md에 "Cross-Spec Boundaries" section 추가 시 이 표를 ground truth로 사용**.

## Project Structure

### Documentation (this feature)

```text
specs/011-reuse-fullstack-subtitle/
├── plan.md                  # This file
├── research.md              # Phase 0 output
├── data-model.md            # Phase 1 output
├── quickstart.md            # Phase 1 output
├── contracts/               # Phase 1 output
│   ├── cli_content.md       # Typer CLI contract: tube-scout content scan/whitelist/baseline subcommands
│   ├── service_layer.md     # Service-layer functions consumed by spec 008/014 web UIs
│   └── db_schema.md         # SQLite ALTER + new tables (baseline_corpus, phrase_whitelist, professor_pool, pair_checkpoint)
├── checklists/
│   └── requirements.md      # already created by /speckit.specify
└── tasks.md                 # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/tube_scout/
├── models/
│   ├── content.py                              # MODIFIED: extend ComparisonResult with i6/i7/i8/pattern/layer_attribution; add Pydantic models for BaselinePhrase, WhitelistEntry, ProfessorPool, PairCheckpoint
│   └── reuse_v2.py                             # NEW: nC2-specific entities (CaptionPool, MatchSpan, ReusePatternLabel)
├── services/
│   ├── nc2_matcher.py                          # NEW: caption pool generation per professor, nC2 pair enumeration, layer A length filter
│   ├── time_axis_indicators.py                 # NEW: I-6 longest contiguous, I-7 distribution, I-8 position diversity, segment alignment
│   ├── layer_defense.py                        # NEW: orchestrates Layer A→B→C→D pipeline, attaches Layer Attribution Record per pair
│   ├── baseline_corpus.py                      # NEW: per-professor stylistic phrase corpus bootstrap + incremental update
│   ├── phrase_whitelist.py                     # NEW: phrase normalization (whitespace/punctuation/case/full-half), match calculation
│   ├── pair_checkpoint.py                      # NEW: per-pair persistence + resume scan
│   ├── professor_resolver.py                   # NEW: (channel_alias, author) → professor_id mapping; cross-channel pool unification
│   ├── pattern_classifier.py                   # NEW: 4-pattern classification rule (whole vs scattered × same-week vs diff-week)
│   ├── advisory_lock.py                        # NEW: file-based fcntl advisory write lock for content_reuse.db Layer D mutations
│   └── content_comparator.py                   # MODIFIED: extend pipeline to call layer_defense + time_axis_indicators; preserve M-default fast path
├── storage/
│   ├── content_db.py                           # MODIFIED: ALTER comparison_results + create new tables (baseline_corpus, phrase_whitelist, professor_pool, pair_checkpoint, layer_attribution)
│   └── checkpoint.py                           # MODIFIED (or reuse): pair-level checkpoint integration
├── cli/
│   └── content.py                              # MODIFIED: add `tube-scout content scan --mode nc2`, `content whitelist add/list/export`, `content baseline bootstrap/update`, `content review --pattern <label>`, `content professor map`
├── reporting/
│   ├── content_report.py                       # MODIFIED: 4-pattern grouped HTML sections, time-axis bar visualization, Layer D suppression header summary
│   └── templates/
│       └── content_v2.html.j2                  # NEW: spec 011 report template extending spec 007 template
└── visualization/
    └── time_axis_chart.py                      # NEW: plotly bar/heatmap for match-span positions

tests/
├── contract/
│   ├── test_cli_content_v2_contract.py         # NEW: Typer command argument schema tests
│   ├── test_service_layer_contract.py          # NEW: spec 008/014 facing service signatures
│   └── test_db_schema_v2_contract.py           # NEW: ALTER + new tables, idempotent migration
├── unit/
│   ├── test_nc2_matcher.py                     # NEW
│   ├── test_time_axis_indicators.py            # NEW: I-6/I-7/I-8 fixtures
│   ├── test_layer_defense.py                   # NEW: Layer A/B/C/D unit
│   ├── test_baseline_corpus.py                 # NEW
│   ├── test_phrase_whitelist.py                # NEW: normalization edge cases
│   ├── test_pair_checkpoint.py                 # NEW: resume from arbitrary mid-pair state
│   ├── test_professor_resolver.py              # NEW: cross-channel mapping + missing-mapping fallback
│   ├── test_pattern_classifier.py              # NEW: 4-pattern + tie-break rules
│   ├── test_advisory_lock.py                   # NEW: concurrent write rejection
│   └── test_content_report_v2.py               # NEW: pattern grouping, baseline subtraction display, Layer D summary
├── integration/
│   ├── test_nc2_pipeline.py                    # NEW: end-to-end M-nC2 on synthetic caption pool
│   ├── test_layer_d_persistence.py             # NEW: review/whitelist actions persist + reload behavior
│   ├── test_overnight_resume.py                # NEW: simulate interruption mid-pair, resume completes
│   ├── test_cross_channel_pool.py              # NEW: same professor on 2 channels → unified pool (B-1)
│   └── test_spec007_compatibility.py           # NEW: spec 007 schema project, run spec 011 → no caption / embedding recompute (B-2 + SC-009)
└── adversary/
    └── test_reuse_v2_adversary.py              # NEW: malformed timestamps, empty pool, single-video pool, ASR noise, mixed-language, ultra-long capture
```

**Structure Decision**: 기존 tube-scout single-project 구조를 그대로 따른다. 모든 신규 파일은 기존 `src/tube_scout/{models,services,storage,cli,reporting,visualization}/` 트리에 추가된다. SQLite는 spec 007의 `content_reuse.db` 단일 파일을 그대로 사용하고 ALTER + new table만 적용한다 — 별도 DB 파일을 만들지 않음으로써 spec 007 데이터와의 backward compatibility (FR-026, SC-009) 를 자연스럽게 보장. 보고서는 spec 007 산출물 옆에 새 디렉터리(`02_analyze/content/v2/`) + 새 보고서 템플릿(`content_v2.html.j2`) 으로 분리해 기존 보고서를 변경하지 않는다.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | Phase 0 gate에서 모든 NON-NEGOTIABLE 원칙 PASS. Principle VII는 Phase 1에서 spec.md boundary section 추가로 자연스럽게 충족 — 별도 justification 불필요. |
