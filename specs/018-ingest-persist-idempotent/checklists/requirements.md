# Specification Quality Checklist: unified_ingest 영구화 + 멱등 가드 (spec 017 PATCH)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Validation Notes

본 spec 은 spec 017 의 SC-004 부분 실패에 대한 PATCH 다. 결함 위치 (line 100/113/72) 및 표준 fix 패턴 위치 (cli/collect.py:1931 + 2250) 는 **배경 섹션의 맥락 정보**로만 사용되었고, FR 본문은 구현 위치를 직접 명세하지 않는다 — 모든 FR 은 외부 관측 가능한 행동 (산출물 영구화, 멱등 skip, 강제 재처리, 단말 출력, 감사 기록) 으로 표현되었다.

3 가지 [NEEDS CLARIFICATION] 후보를 검토했고 모두 합리적 기본값으로 해소했다:

1. **자막 영구화 위치**: spec 013 의 `collect transcripts` 와 동일한 `data/<alias>/02_analyze/transcripts/<video_id>.json` 로 결정 (FR-018H 의 schema 동치 조건이 직접 요구).
2. **`--force` 시 행위**: spec 013 의 `collect fingerprint --force` 와 시그니처 일관 (사용자가 idea 시드에서 spec 013 패턴 차용을 명시).
3. **22 학과 환산 검증 방법**: 한 학과 실측 + 선형 환산으로 충분하다고 가정 (Assumptions 명시). 22 학과 모두 실측을 acceptance 조건으로 강제하지 않음.

### Cross-Spec / Existing-Surface 정합성 점검 (2026-05-16)

사용자 우려 — "분석 후 자막·지문이 남고, 음원은 정상 확인 후 삭제, 영상은 사용자 명시 시 삭제" — 4 가지 기대를 기존 surface 와 대조한 결과:

| 기대 | 기존 surface | spec 018 추가 필요 |
|---|---|---|
| 자막·지문 영구화 | 결함 A/B 가 폐기 중 | ✅ FR-018A / FR-018B |
| 결과 정상성 점검 | `asr.py:detect_quality_flags()` + `AsrQualityFlags` 모델로 이미 6 종 산출, transcribe_audio 반환값에 포함 | FR-018A 가 영구화하면 자동 포함 (별도 FR 불필요, 본문에 명시 추가됨) |
| 임시 WAV 정리 | spec 017 FR-007 + `audio_extract.WavLifecycle.__exit__` 가 무조건 cleanup | 불필요 (Assumptions 에 인계 명시) |
| mp4 보존·삭제 | spec 017 `--delete-source` 두 단계 prompt 가 unified_ingest:416-437 에 살아있음 | 불필요 (Assumptions 에 인계 명시) |

점검 fail 영상 흐름 결정: 분리 명령 `collect transcripts` 동작 인계 — quality flag 가 true 여도 RuntimeError 가 아니면 transcript json 영구화 + retry_pending 미등재 + 멱등 skip. 자동 재시도 정책 신규 도입은 본 PATCH 범위 밖.

본 spec 은 `/speckit.plan` 진행 준비 완료 상태다.

## Notes

- Check items off as completed: `[x]`
- Items marked incomplete require spec updates before `/speckit.clarify` or `/speckit.plan`
