# tube-scout v0.4~v1.0 로드맵 — 자막 풀스택 출시 + 다중 신호 점진 보완

**작성일**: 2026-05-09
**상태**: 초안 (다음 세션에서 spec 011/014 작업 시 입력 문서로 사용)
**선행**: spec 007 (재사용 탐지), spec 008 (admin web UI), spec 010 (--prefer-captions-api + skip-existing — 직전 세션 완료)
**계기**: 2026-05-08~09 세션에서 운영자(홍길동/DX센터장)와 진행한 도구 본질 재검토. 자막 acquisition의 인프라 의존성 + 재사용 탐지 알고리즘 한계 + UI 책임 분리 + 데이터 acquisition 전략 + 문제 상황 카탈로그 도출.

---

## Executive Summary

세 줄 요약:

1. **v0.4는 자막 기반 영상 재활용 분석을 단순 UI에 담아 교무과에 즉시 인계** — spec 011(자막 풀스택) + spec 014(UI 재설계)를 묶어서 출시.
2. **v0.5+는 자막의 4가지 한계(부재·노이즈·시각만 동일·속도 변화)를 다른 신호(Whisper STT, 음향 지문, 프레임 hash, DTW)로 점진 보완**.
3. **자막 수집은 관리자(CLI + cron) 책임, 교무과는 분석 트리거+검토만** — 학과 조교 손작업·외장 HDD 운영은 영구 제외.

---

## §1. 운영 책임 분리 원칙

| 역할 | 인터페이스 | 책임 |
|---|---|---|
| **관리자** (DX센터장) | CLI + shell script + cron + nix systemd timer | 자막 백필, baseline corpus 관리, 정책 임계 조정, OAuth 토큰 운영, 시스템 모니터링, 음원 다운로드(향후), Whisper 인프라 |
| **교무과 직원** | **단순 web UI (3-메뉴)** | 분석 시작 + 의심 쌍 검토 + 이력 조회 (오직 3가지) |
| **학과 조교** | (없음) | 손작업·외장 HDD 운영은 **영구 제외** |

원칙:
- 교무과 직원에게 "관리" 메뉴를 노출하지 않는다.
- 자막 수집·임계 조정·corpus 관리는 모두 관리자 CLI로.
- 22채널 백필은 관리자 1인 자동화로 처리 (cron + shell script). 학과 조교 협조 = OAuth onboarding 1회 외엔 불필요.

---

## §2. v0.4 출시 대상 — 자막으로 할 수 있는 모든 분석 + 단순 UI

### 2.1 포함 spec

| Spec | 상태 | 내용 |
|---|---|---|
| spec 007 | 구현 완료 | 5 지표(I-1~5) + M-default 매칭 |
| spec 010 | 직전 세션 완료 | `--prefer-captions-api` + skip-existing |
| **spec 011** | **신규** | 자막 기반 nC2/cross-prof 매칭 + 시간축 지표(I-6/I-7/I-8) + 4계층 정규화(Layer A/B/C/D) |
| **spec 014** | **신규** | web UI 전면 재설계 (3-메뉴 + 라디오 모드 + 검토 화면) |

### 2.2 출시 후 즉시 가능한 분석

- 다년 동일 과목 비교 (정광석 2025 vs 2026 감염미생물학)
- 같은 학기 다른 과목 nC2 (A 4주 vs B 10주)
- 다년 다른 과목 nC2
- 4가지 재활용 패턴(통째 동일주 / 분산 동일주 / 통째 다른주 / 분산 다른주) 모두 검출 + 구별
- 교수 stylistic recurrence(대티역 비유 등) 자동 무시 (Layer B baseline)
- 의심 쌍 검토 + 화이트리스트 누적 (Layer D)

### 2.3 작업량 추산

| 항목 | 작업량 |
|---|---|
| spec 011 (자막 풀스택) | 4~6주 dev-squad 1회 |
| spec 014 (UI 재설계) | 2~3주 dev-squad 1회 |
| **합계 v0.4 추가** | **6~9주** |

쿼터 증액 승인(외부 1~3일) + 22채널 OAuth(외부 1~2주) 끝나면 본 v0.4 작업이 critical path.

---

## §3. v0.5+ — 자막 한계 점진 보완

자막의 4가지 한계와 그에 대응하는 신호:

| 자막 한계 | 보완 신호 | spec | 버전 |
|---|---|---|---|
| 자막 부재 영상 (무자막 강의) | yt-dlp + Whisper STT | spec X | v0.5 |
| ASR 자막 노이즈로 정확도 저하 | 음향 지문 (chromaprint) | spec Y | v0.6 |
| 자막은 다른데 시각만 동일 | 프레임 perceptual hash (OCR 아님) | spec Z | v0.7 |
| 속도 변화로 자막 정렬 왜곡 | chromagram + DTW | (미정 spec) | v0.8 |

추가 잔여 (v1.0+):
- spec 012 cross-professor 매칭 (협력 강의 사례 발생 시)
- spec 013 외부 corpus index (외부 자료 인용 처리, 정책 결정 후)
- I-9 discourse marker 지표 (자기 복습 인용 false positive 줄이기)
- Q-006 자막 품질 게이트 (ASR 노이즈 사전 필터)

---

## §4. 분석 신호 3-Tier 캐스케이드 아키텍처 (장기 비전)

**v0.4 출시 시점에는 자막만으로 모든 Tier를 커버. v0.5+에서 다른 신호로 Tier 1을 강화하며 자막은 Tier 2 보조로 자연스럽게 강등.**

```
모든 영상 (예: 22채널 × 1,000)
   │
   ├─ Tier 1 — 빠른 1차 필터 (CPU, 영상당 ~1초)
   │   v0.4: 자막 cosine + 메타시그널
   │   v0.6+: 음향 지문 (chromaprint) + 프레임 pHash
   │   → 의심 쌍 후보 5,000건
   │
   ├─ Tier 2 — 중간 정밀도 (CPU/GPU, 쌍당 ~5초)
   │   v0.4: 자막 chunk 매칭 + I-6/I-7/I-8
   │   v0.5+: + 음향 fingerprint chunk 매칭
   │   → 의심 쌍 500건
   │
   └─ Tier 3 — 고정밀 (GPU/API, 쌍당 ~30초)
       v0.5+: chromagram DTW + Whisper encoder embedding
       v1.0+: 멀티모달 LLM (특수 케이스만)
       → 등급 부여 + 인간 검토 큐
```

---

## §5. 데이터 acquisition 전략 + 저장 정책

### 5.1 YouTube API 가용성 인정

| 데이터 | 공식 API | yt-dlp |
|---|---|---|
| 메타데이터·자막 | ✅ | ✅ |
| 음원·영상 파일 | ❌ 공식 미제공 | ✅ |
| 프레임 캡처 | ❌ | ✅ (영상 다운 후 ffmpeg) |
| Studio bulk download | ⚠ 1회 5개 한도, UI 전용 | — |

→ 음향·시각 신호에 필요한 raw media는 yt-dlp가 유일한 경로 (자교 콘텐츠 자기 백업 정당성).

### 5.2 운영 모델 (영구 결정)

**관리자가 institutional 서버에서 yt-dlp 자동 실행**:

```bash
# scripts/weekly-backfill.sh — cron으로 매주
ALIASES=(nursing dental pharmacy ...)
for alias in "${ALIASES[@]}"; do
  tube-scout collect videos --channel "$alias"
  tube-scout collect transcripts --channel "$alias" --prefer-captions-api
done
# v0.5+에서 음원 단계 추가
```

학과 조교 손작업·외장 HDD = **영구 제외**.

### 5.3 저장 3계층

| 계층 | 보관 | 크기 |
|---|---|---|
| 영구 | 자막 + 메타 + 음향 지문(v0.6+) | 수 GB |
| 임시 | 처리 중 음원 (fingerprint 추출 후 폐기) | 수십 GB |
| On-demand | 의심 쌍 영상 (검토용 일시) | 수~수십 GB |

---

## §6. 자막의 두 갈래 재배치

자막은 두 가지 가치를 가진다. 기존 spec 007은 둘을 섞어 다뤘으나, 이번 재배치에서 분리.

### 6.1 영상 재활용 탐지 (강등 예정)

- v0.4 출시 시점: 1차 신호로 사용
- v0.5+: 다른 신호(음향 지문 등)가 강해지면 자연스럽게 보조 신호로 강등
- ASR 노이즈·자막 부재 등의 한계 인정

### 6.2 커리큘럼·도메인 분석 (격상)

자막의 본연 가치 — 대학본부 강의 품질 관리 데이터.

- 학과 강의가 도메인 지식의 어느 정도를 커버하는가
- 핵심 용어·개념 추출
- 학생 학습 성과 지표와 매칭
- 다년 누적 시 강의 진화 추적

이 트랙은 **별도 spec(미래 spec 020+)**으로 분리. v0.4 출시와 무관하게 진행 가능.

---

## §7. 문제 상황 카탈로그

본 도구가 마주칠 모든 시나리오. PS-U는 운영자 본인 제시, PS-A는 adversarial 검토에서 도출.

### 7.1 PS-U — 운영자(홍길동) 제시 시나리오

| ID | 상황 | v0.4 처리 | 비고 |
|---|---|---|---|
| PS-U-1 | 정광석 자기 분석: 2026 vs 2025 감염미생물학 | ✅ M-default + I-1~5 | spec 007 기존 |
| PS-U-2 | 다른 학기 다른 과목 nC2 (A 4주 vs B 10주) | ✅ M-nC2 + I-1~8 | spec 011 |
| PS-U-3a | 20분 통째 → 같은 주차 (case 1) | ✅ I-6 연속 일치 | spec 011 |
| PS-U-3b | 5분×4 분산 → 같은 주차 (case 2) | ✅ I-7 분포로 (3a)와 구별 | spec 011 |
| PS-U-3c | 20분 통째 → 다른 주차 (case 3) | ✅ M-nC2 + I-6 | spec 011 |
| PS-U-3d | 5분×4 분산 → 다른 주차 (case 4) | ✅ M-nC2 + I-7/I-8 | spec 011 |
| PS-U-4 | 교수 stylistic 비유 (대티역 등) | ✅ Layer A 길이 + Layer B baseline | spec 011 |
| PS-U-5 | 정책 임계 의문 (전체 N% / 연속 N초 / 흩어진 일치) | ✅ Layer A 임계 + 등급 컷 + Layer D 화이트리스트 | spec 011 + 정책 결정 |

### 7.2 PS-A — Adversarial 시나리오 (해결 가능)

| ID | 상황 | 처리 |
|---|---|---|
| PS-A-2 | 자막 OCR 오류 (부분) | I-2 cosine 흡수 (부분), v0.6+ 음향 지문으로 완전 해결 |
| PS-A-6 | 무자막 강의 | Q-001~005 사전 제외, v0.5 Whisper STT로 보완 |
| PS-A-10 | 코드 스위칭 (한·영 혼용) | multilingual embedding |
| PS-A-14 | 즉흥 응답 5분 차이 | Layer A 흡수 |
| PS-A-17 | 순서 뒤바꾸기 (A→B→C ↔ C→B→A) | I-6 짧음 + I-7 분포 ↑ |
| PS-A-18 | 어휘 트렌드 변화 | I-2 의미 + I-3 변화 적정 |
| PS-A-19 | HQ 재촬영 (같은 내용) | reviewer FALSE_POSITIVE 누적 |

### 7.3 PS-A — Adversarial 시나리오 (도구 확장 필요)

| ID | 상황 | 보완 spec / 버전 |
|---|---|---|
| PS-A-1 | 다른 교수 간 협력 자료 재활용 | spec 012 cross-prof / v1.0 |
| PS-A-4 | 속도 변화 (1.5배속) | DTW / v0.8 |
| PS-A-8 | 표준 정의 인용 | 정의 사전 화이트리스트 / 정책 결정 |
| PS-A-9 | 명시적 자기 인용 ("지난 주 말씀드린 대로") | I-9 discourse marker / v1.0+ |
| PS-A-11 | ASR 자막 노이즈 누적 | Q-006 자막 품질 게이트 / v1.0+ |
| PS-A-15 | 외부 자료 인용 (Khan academy 등) | spec 013 외부 corpus index / v1.0+ |

### 7.4 PS-A — 정책 결정 필요 (도구 외)

| ID | 상황 | 결정 사항 |
|---|---|---|
| PS-A-13 | 3년 점진 진화 (30% 갱신) | "70% 동일은 정상 진화" 등 등급 컷 |
| PS-A-16 | 슬라이드 낭독 강의 (매년 동일) | "낭독형 강의 별도 카테고리" 또는 평가 제외 |

→ 교무과·DX센터·학사정책 합의 필요. spec 011 작업 전 정책 문서 작성.

### 7.5 영구 scope OUT

| ID | 상황 | 정책 |
|---|---|---|
| PS-A-5 | 슬라이드 시각 재활용 (자막 다름) | OCR 영구 제외 (memory: project_scope_decisions_20260506) |
| PS-A-7 | 게스트 강의 한 영상 두 교수 | 화자분리 영구 제외 |
| PS-A-12 | 외부(타교) 강의 재활용 | 자교 채널만 분석 |
| PS-A-20 | 자막은 다른데 슬라이드만 동일 | 자막+음향만 사용 (OCR 외) |

---

## §8. UI 전면 재설계 (spec 014, v0.4 출시 필수)

### 8.1 현재 (v0.3.3) 한계

- 단일 페이지: 학과·교수·과목·기간 4-tuple **강제**
- 단일 워크플로우만 지원 (단일 과목 분석)
- "관리" 메뉴를 교무과에 노출 (책임 분리 위반)
- 검토 화면 부재 (Layer D 화이트리스트 누적 불가)

### 8.2 v0.4 재설계

```
┌─ 헤더 (메뉴 3개) ──────────────────────┐
│ [새 분석 ▾]  [검토]  [이력]            │
└─────────────────────────────────────────┘

[새 분석] 페이지
┌──────────────────────────────────┐
│ 학과 *      [드롭다운            ▾]│
│ 교수 *      [____________]        │
│                                    │
│ 분석 범위 *                        │
│  ◉ 단일 과목 (한 학기 깊이 분석)  │
│  ◯ 교수 전수 (다년·다과목 nC2)    │
│  ◯ 학과 전수 (cross-prof)         │
│                                    │
│ [모드별 조건부 필드]               │
│  단일: 과목 *, 기간 *              │
│  교수전수: 기간 (선택)             │
│  학과전수: 기간 (선택), ⚠ 시간경고│
│                                    │
│           [분석 시작]              │
└──────────────────────────────────┘

[검토] 페이지 — Layer D 화이트리스트 누적
- 의심 쌍 정렬 (suspicion_score 내림차순)
- 클릭 → 두 영상 segment alignment 시각화
- [중복 확정] / [오탐] / [보류]

[이력] 페이지 — 과거 분석 결과 재열람
```

### 8.3 관리 메뉴는 web에서 영구 제거

정책 임계, baseline corpus, 시스템 상태, OAuth 토큰 health, 쿼터 모니터링, 자막 수집 트리거 — **모두 CLI + admin script에서만**.

### 8.4 작업량

- 메뉴 3개 + 라디오 모드 폼: 0.5주
- 검토 화면 (segment alignment 시각화): 1.5주
- 백엔드 라우트 (새 분석 모드 호출): 0.5주
- 테스트 + 검증: 0.5주
- **합계 2~3주**

기존 5주 추정에서 "관리 메뉴" 등 비핵심 기능 제거로 단축.

---

## §9. 추가 결정사항

| 항목 | 결정 |
|---|---|
| 버전 번호 정책 | idea 번호 ≠ 제품 버전. 제품 버전은 pyproject.toml 기준 (memory: feedback_version_policy) |
| 익명화 정책 | public 저장소이므로 모든 spec에 PII 검토 의무. 익명화 매핑(memory: project_public_repo_transition) 준수 |
| GPG 서명 | 사람 commit은 서명, 자동화 commit은 bypass 허용 |
| 출시 전 외부 의존 작업 | YouTube API 쿼터 증액 승인 + 22채널 OAuth onboarding + 자막 백필 |
| 자막 수집 책임 | 관리자 (CLI + cron + shell script). 교무과 비관여 |
| 학과 조교 손작업 | 영구 제외 |
| OCR / 화자분리 / 외부강의 | 영구 scope OUT (PS-A-5/7/12/20) |
| 정책 결정 사전 작업 | spec 011 작업 전 교무과 정책 문서(점진 진화 임계 + 낭독형 강의) 작성 |

---

## 다음 액션

| 순서 | 작업 | 의존성 | 시점 |
|---|---|---|---|
| 1 | YouTube API 쿼터 증액 승인 | Google 검토 | 진행 중 (1~3 영업일) |
| 2 | 22채널 OAuth onboarding | 학과 협조 | 쿼터 승인 후 1~2주 |
| 3 | 22채널 자막 백필 (관리자 cron) | OAuth 완료 + spec 010(✓) | 백필 자체 ~1주 |
| 4 | 교무과 정책 문서 (점진 진화 임계 등) | DX센터·교무과·학사 합의 | 병렬 진행 가능 |
| 5 | spec 011 (자막 풀스택 nC2 + 시간축 + 4계층) | 정책 문서 + 백필 | 4~6주 dev-squad |
| 6 | spec 014 (UI 전면 재설계) | spec 011 백엔드 | 2~3주 dev-squad (병렬 가능) |
| 7 | **v0.4 출시 + 교무과 인계** | 5+6 완료 | 약 9~12주 후 |
| 8+ | v0.5~v1.0 점진 보완 | 운영 데이터 누적 | 출시 이후 |

---

## 참조 메모리

- `project_dev_status.md` — 전체 개발 현황
- `project_reuse_detection_design.md` — 4계층 layered defense
- `project_reuse_methods_inventory.md` — 8 지표 + 20 adversarial 시나리오 매트릭스
- `project_ui_simplification_and_audio_fallback.md` — 3-메뉴 분리 + Whisper 백업
- `project_data_acquisition_strategy.md` — yt-dlp 운영 모델, v0.4~v1.0 로드맵
- `project_public_repo_transition.md` — 익명화 매핑
- `project_scope_decisions_20260506.md` — OCR·화자분리 영구 제외
- `feedback_version_policy.md` — 버전 정책

