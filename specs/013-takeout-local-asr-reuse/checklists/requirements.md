# Specification Quality Checklist: Takeout 기반 로컬 ASR + 강의 영상 재사용 판정 + 자막 KB Export

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-13
**Feature**: [spec.md](../spec.md)

## Content Quality

- [~] No implementation details (languages, frameworks, APIs)
  - **부분 통과**. spec은 일부 기술 식별자를 명시적으로 언급한다: `chromaprint`, `ffmpeg`, `faster-whisper`, `SQLite`, `cuda:0/1`, `int8_float16`. 이들 중 다수는 단순한 구현 선택이 아니라 운영자가 부과한 요구사항 자체다 — 예컨대 FR-048("no cloud STT API")은 정책 제약이며, `chromaprint`는 본 프로젝트의 음원 지문 알고리즘 그 자체로 spec 012/X에서 master에 들어가 있다. FR-016 / FR-022는 GPU·정밀도·디바이스 옵션이 운영자가 명시적으로 요구한 surface여서 그대로 둔다. **남는 사선 위반**: FR-022가 "Python worker processes"로 언어를 직접 명명한다 — 대체 표현 가능한가? 답: tube-scout가 단일 언어 codebase(Python 3.11 pinned)이므로 실용적으로 함의이지만 표현을 "worker processes" 로 완화 가능. 본 issue는 향후 plan 단계에서 다시 다듬을 수 있음.
- [x] Focused on user value and business needs
  - 3개의 사용자 스토리(P1: 교수 단위 재사용 보고서 / P2: KB export / P3: 레거시 제거)가 모두 운영자(DX센터장)의 명시 가치 명제와 직접 대응.
- [x] Written for non-technical stakeholders
  - 사용자 스토리·acceptance scenario는 교무 검토자가 읽을 수 있는 보류형 표현을 유지. FR / Edge Cases는 운영자(개발 보조 역할 겸함) 수준 기준.
- [x] All mandatory sections completed
  - User Scenarios & Testing, Requirements, Success Criteria 모두 작성. Assumptions section은 spec-template에서 mandatory가 아니지만 idea의 결정사항 보존을 위해 포함.

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
  - idea 문서가 §12에서 모든 미해결 결정을 운영자 confirmation으로 처리한 상태. spec 본문에는 [NEEDS CLARIFICATION] 미사용. Phase 1 측정 dependency(부록 임계 / fingerprint_input_policy / evidence score 가중치)는 [NEEDS CLARIFICATION]이 아니라 명시적 측정 약속으로 표현(FR-014, FR-038, SC-003 등).
- [x] Requirements are testable and unambiguous
  - 모든 FR이 검증 가능한 동사(MUST / MUST NOT)와 구체적 산출물(파일 경로, 컬럼명, enum 값)을 갖춤. 단 일부 임계·가중치는 Phase 1 측정 후 확정 — 이는 측정 대상 자체가 명시되어 있어 testable.
- [x] Success criteria are measurable
  - SC-001~SC-010 모두 측정 가능. SC-002 / SC-003 / SC-010은 "Phase 1·2 측정 후 확정"이라는 명시적 deferred-commit 형태 — 측정 자체는 spec follow-up에서 commit 강제.
- [~] Success criteria are technology-agnostic (no implementation details)
  - **부분 통과**. SC-009는 `ytdlp` 식별자를 직접 명명 — 이는 P3 가치 명제(legacy 식별자 제거 검증)의 본질이라 회피 불가. SC-010은 GPU 사용률 명시 — 운영자 하드웨어 제약을 반영. 이들은 user value를 검증하는 가장 직접적 표현이고, 이를 추상화하면 검증 가능성이 떨어진다.
- [x] All acceptance scenarios are defined
  - P1에 6개, P2에 3개, P3에 3개의 acceptance scenario. 각 시나리오는 Given/When/Then 형식.
- [x] Edge cases are identified
  - Ingestion / Audio extract / STT / 분석 / 보고서 / KB export / 기타 7개 카테고리로 25+ edge case 명시.
- [x] Scope is clearly bounded
  - FR-048 ~ FR-052의 negative requirement 5건 + Assumptions의 OS 제약 + 본 spec에 포함하지 않는 항목(`--force-asr`, cross-professor, OCR, 화자 분리, 댓글 분석, web admin 통합 등) 명시.
- [x] Dependencies and assumptions identified
  - Assumptions section에 acquisition 모델 · 환경 · spec 007/011/012 baseline · chromaprint 검증 상태 · GPU 정책 · evidence score 출발점 · 첫 입력 데이터 명시.

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
  - 각 FR이 P1/P2/P3 acceptance scenario 중 하나 이상에 대응. 일부 FR(예: FR-043 ~ FR-045 v4 마이그레이션)은 Edge Cases · Assumptions에서 보강.
- [x] User scenarios cover primary flows
  - P1: 4단계 파이프라인 + 결과 보고서. P2: 단일·bulk export. P3: 레거시 제거. 운영자 명시 4단계 워크플로우(`collect takeout` → `collect process-audio` → `analyze content-reuse` → `report content-reuse`)가 P1 시나리오 1에 정확히 매핑.
- [x] Feature meets measurable outcomes defined in Success Criteria
  - 각 SC가 1개 이상의 FR 또는 Acceptance Scenario에서 검증 가능.
- [~] No implementation details leak into specification
  - **위 "No implementation details" 항목과 동일 사유로 부분 통과**. 구현 세부가 새는 부분은 모두 운영자 정책 제약(local-only STT, 특정 음원 지문 알고리즘, GPU 환경)이거나 단일 언어 codebase 함의로 인한 것이며, 추상화하면 검증 가능성을 잃는다.

## Notes

- 본 spec은 idea 문서(`idea/idea-2026-05-12-takeout-knowledge-base.md`)의 §12에서 운영자가 명시 confirm한 7개 결정 사항(spec 명칭 · 부록 임계 정책 · spec 012 처리 · A6000 정책 · quota 트랙 · 신설 2패턴 우선순위 · 자막 출처 정책)을 모두 반영했다. 추가 clarification 라운드는 불필요.

- 구현 세부 누출(SC-009 `ytdlp` 식별자, FR-022 worker process 표현, FR-013 / FR-016의 특정 라이브러리 명시)은 검증 가능성 / 정책 제약 / 단일 언어 codebase 함의 등 정당한 사유로 잔존. plan 단계에서 표현을 다듬어볼 여지는 있으나 spec 단계에서는 의도 명확성을 우선했다.

- Phase 1 / Phase 2 측정 dependency(evidence score 가중치, fingerprint_input_policy 기본값, 부록 임계, runtime budget, auto-mapping 자동화율, hallucination defense 잔여율, worker pool GPU 사용률)는 spec 단계에서는 측정 약속만 둔다. plan / tasks 단계에서 측정 task로 명시 분리한다.

- spec 016 명칭 이슈: idea 문서 §12.1이 "016-takeout-local-asr-reuse"를 명시했으나 speckit-specify의 sequential numbering이 현재 가용한 가장 작은 번호 013을 할당했다. spec 013/014/015 디렉터리는 polluted yt-dlp 트랙 폐기 이후 비어 있으므로 sequential 정책과 일치한다. 운영자가 016 명칭을 재부여하려면 별도 결정 필요(branch rename + 디렉터리 rename).
