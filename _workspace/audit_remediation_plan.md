# Tube Scout v0.1.0 — Audit Remediation Plan

> ⚠️ **이 문서는 사용자 승인 대상입니다.** 승인 후 Phase 9(수정 실행)에 진입합니다.

## 감사 실행 요약

| Phase | Layer | 결과 |
|-------|-------|------|
| 1 | L1 정적 분석 | mypy 37건, 포매팅 71건, 데드코드 248건(대부분 FP), bandit 3건(FP) |
| 2 | L5 일관성 | 매직넘버 7건, 타입힌트 1건. 전반적 매우 양호 |
| 3 | L2 모듈 계약 | WARNING 5건 (models-services 계약 갭, 미사용 API, 내부 API 노출) |
| 4 | L7 보안 | High 2건, Medium 2건, Low 2건 |
| 5 | L6 Adversary | 157/157 PASS, 취약점 5건 발견 |
| 6 | L3 통합 | 75/75 PASS, checkpoint thread-safety 발견 |
| 7 | L4 E2E | 14/14 PASS, checkpoint 경로 이중 중첩 발견 |

**신규 테스트**: 246건 추가 (기존 1,067 → 1,313)
**기존 실패**: test_forecaster_ext.py 11건 (prophet/statsmodels pre-existing)

---

## 발견사항 종합 — 심각도별 분류

### Critical: 0건

### High: 6건

| ID | 출처 | 내용 | 영향 |
|----|------|------|------|
| **H-01** | Phase 1 | `cli/report.py:473` — `**kwargs` unpacking on string | 런타임 크래시 |
| **H-02** | Phase 4 | OAuth 토큰 파일 권한 0644 (auth.py 4곳) | 공유 서버에서 토큰 타인 접근 가능 |
| **H-03** | Phase 4 | 네트워크 타임아웃 미설정 (YouTube API, Transcript, LLM) | CLI 무한 대기 |
| **H-04** | Phase 5 | 손상된 체크포인트 파일 시 JSONDecodeError 미처리 (checkpoint.py:47) | 전원 차단 후 크래시, 수동 삭제 필요 |
| **H-05** | Phase 5 | 체크포인트 스키마 변경 시 무음 데이터 손실 (checkpoint.py:54) | 업그레이드 후 수집 처음부터 재시작 |
| **H-06** | Phase 1 | `services/transcript.py` FetchedTranscriptSnippet 인덱싱 에러 6건 | transcript 수집 실패 가능 |

### Medium: 7건

| ID | 출처 | 내용 | 영향 |
|----|------|------|------|
| **M-01** | Phase 4 | Excel formula injection 미방어 (excel_export.py) | 악의적 제목 시 수식 실행 |
| **M-02** | Phase 4 | `--channel` alias path 미검증 | path traversal 가능 (CLI라 실질 위험 제한) |
| **M-03** | Phase 5 | `json_store.py:40` default=str로 비직렬화 객체 무음 변환 | 데이터 무결성 위반 |
| **M-04** | Phase 5 | `json_store.py:20` UTF-8 BOM 미지원 | Windows 복사 JSON 읽기 실패 |
| **M-05** | Phase 1 | `services/validator.py:225` 잘못된 tuple로 set.add | 검증 로직 오류 |
| **M-06** | Phase 1 | `reporting/video_report.py:104`, `bundle_report.py:326` 반환 타입 불일치 | 타입 불일치로 예기치 않은 동작 |
| **M-07** | Phase 1 | `services/youtube_analytics.py:98` None 체크 누락 | 특정 조건에서 AttributeError |

### Low: 10건

| ID | 출처 | 내용 |
|----|------|------|
| **L-01** | Phase 1 | ruff format 71개 파일 포매팅 불일치 |
| **L-02** | Phase 2 | 매직넘버 7건 (batch_size, max_week, max_tokens, retry) |
| **L-03** | Phase 2 | `cli/search_cli.py:153` 반환 타입 `list` → `list[ParsedTitle]` |
| **L-04** | Phase 3 | models/analytics.py 7개 모델 미사용 (서비스가 dict 반환) |
| **L-05** | Phase 3 | YouTubeDataService에 rate_limiter 미적용 |
| **L-06** | Phase 3 | cli/report.py에서 `_` prefix 내부 API 4곳 직접 호출 |
| **L-07** | Phase 4 | auth.py 토큰 쓰기 non-atomic |
| **L-08** | Phase 5 | title_parser fallback이 잘못된 교수명 추출 |
| **L-09** | Phase 6 | checkpoint 파일 thread-safety 미비 (파일 잠금 없음) |
| **L-10** | Phase 7 | checkpoint 경로 이중 중첩 (`checkpoints/checkpoints/`) |

### INFO (향후 개선)

| ID | 내용 |
|----|------|
| **I-01** | Pydantic model_config에 `extra="forbid"` 추가 고려 |
| **I-02** | 커스텀 예외 계층 (`TubeScoutError`) 도입 고려 |
| **I-03** | models-services 계약 통일 (dict → Pydantic 반환) — 대규모 리팩터링, 현재 동작에 문제 없음 |
| **I-04** | mypy --strict 단계적 도입 계획 수립 |
| **I-05** | vulture 데드코드 248건 수동 검증 (대부분 Pydantic false positive) |
| **I-06** | test_forecaster_ext.py 11건 기존 실패 수정 (prophet/statsmodels) |

---

## 수정 계획

### 의존관계 분석

```
H-04, H-05 → 둘 다 checkpoint.py 수정 → 함께 수정
H-02, L-07 → 둘 다 auth.py 토큰 쓰기 → 함께 수정
M-03, M-04 → 둘 다 json_store.py → 함께 수정
H-01, M-06 → 둘 다 reporting 반환 타입 → 함께 수정
```

### 수정 순서 (우선순위)

| 순서 | ID | 파일 | 수정 내용 | 예상 영향 |
|------|-----|------|----------|----------|
| **1** | H-01 | cli/report.py | `**kwargs` unpacking 버그 수정 | 런타임 크래시 제거 |
| **2** | H-04+H-05 | storage/checkpoint.py | JSONDecodeError 처리 + 스키마 변경 시 경고/복구 | 체크포인트 견고성 |
| **3** | H-06 | services/transcript.py | FetchedTranscriptSnippet 인덱싱 수정 | transcript 수집 정상화 |
| **4** | H-02+L-07 | services/auth.py | 토큰 파일 0600 권한 + atomic write | 보안 강화 |
| **5** | H-03 | services/ 전체 | API 호출에 timeout 파라미터 추가 | 무한 대기 방지 |
| **6** | M-01 | reporting/excel_export.py | 셀 값 prefix 이스케이핑 | Excel injection 방어 |
| **7** | M-03+M-04 | storage/json_store.py | default=str 제거 + utf-8-sig 지원 | 데이터 무결성 |
| **8** | M-05 | services/validator.py | tuple→적절한 타입 수정 | 검증 정확성 |
| **9** | M-06 | reporting/video_report.py, bundle_report.py | 반환 타입 통일 | 타입 안전성 |
| **10** | M-07 | services/youtube_analytics.py | None 체크 추가 | 에러 방지 |
| **11** | L-01 | src/ 전체 | `uv run ruff format src/ tests/` | 포매팅 통일 |
| **12** | L-02+L-03 | 여러 파일 | 매직넘버 상수 추출 + 타입힌트 수정 | 코드 품질 |
| **13** | L-05 | services/youtube_data.py | rate_limiter 적용 | API 안정성 |
| **14** | L-08 | services/title_parser.py | fallback 교수명 추출 로직 개선 | 파싱 정확도 |
| **15** | L-10 | checkpoint 경로 | 이중 중첩 제거 | 경로 정리 |
| **16** | I-06 | tests/unit/test_forecaster_ext.py | prophet/statsmodels 기존 실패 수정 | 테스트 전수 통과 |

### 수정하지 않는 항목 (사유)

| ID | 사유 |
|----|------|
| L-04 | models-services dict→Pydantic 전환은 대규모 리팩터링. 현재 동작 문제 없음. INFO I-03으로 이관 |
| L-06 | 내부 API 호출은 리팩터링 범위. 현재 동작 정상 |
| L-09 | checkpoint thread-safety는 현재 single-thread 사용이므로 실질 위험 없음. 병렬 수집 구현 시 함께 해결 |
| M-02 | CLI 도구이므로 path traversal 실질 위험 제한적. alias 검증은 향후 개선 |
| I-01~I-05 | 향후 개선 사항으로 별도 관리 |

---

## 수정 후 검증 계획

1. 각 수정마다 해당 테스트 실행
2. 전체 수정 완료 후 전체 테스트 스위트 실행: `uv run pytest`
3. 목표: **기존 1,067 + 신규 246 + forecaster 11건 = 1,324건 전부 PASS**
4. ruff check + ruff format 0 violations 확인

---

## 승인 요청

위 수정 계획(16건 수정, 5건 보류)을 검토해 주세요.

- 수정 범위 조정이 필요하면 알려주세요
- 보류 항목 중 포함할 것이 있으면 알려주세요
- 승인하시면 Phase 9(수정 실행)에 진입합니다
