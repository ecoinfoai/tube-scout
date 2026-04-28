# Tube Scout idea4 — 강의 영상 재사용 탐지 및 콘텐츠 품질 관리

## 배경

학과별 강의 영상의 메타데이터 관리(idea3)를 넘어, 영상 **콘텐츠 자체**의 품질을 분석한다. 자막 텍스트를 중심으로 영상 동일성 탐지, 연도별 콘텐츠 업데이트 분석, 교육적 적절성 검사를 수행한다.

교수들이 매 학기 새로운 강의영상을 제작해야 하나, 전년도 영상을 재업로드하여 재활용하는 사례가 있다. 이를 콘텐츠 수준에서 자동 탐지하여 교무 부서의 관리 업무를 지원한다.

> **ytsubs(LVDDS) 프로젝트의 핵심 아이디어를 통합**: 이중 탐지, 처리 상태 추적, 관리자 리뷰 워크플로우.

## 핵심 목적

**자막 기반 강의 콘텐츠 재사용 탐지** — 다중 지표 복합 판정, 의심도 기반 우선순위 점검, 관리자 확인 워크플로우.

## 설계 원칙: C4R

| 원칙 | 적용 |
|------|------|
| **Comfortableness** | 단일 명령으로 전체 파이프라인 실행, 사용자 친화적 진행 표시 |
| **Continuity** | 영상 단위 처리 상태 추적, 중단 후 재개, 증분 업데이트 |
| **Conciseness** | 비교 대상 매칭으로 불필요한 비교 회피, LLM은 diff 있을 때만 호출 |
| **Consistency** | 기존 collect/analyze/report 3단계 패턴 준수, CLI 옵션 일관 |
| **Robustness** | 2단계 자막 수집 fallback, graceful degradation, 관리자 리뷰 단계 |

## 전제 조건

- idea3의 제목 파싱 데이터 활용 (교수/교과목/주차/차시 구조)
- idea3.1의 보고서 필터링/PDF 번들 기능 활용 (콘텐츠 품질 보고서 출력)
- 자막 추출 기능은 v1에서 이미 구현 (`youtube-transcript-api`)
- OAuth `youtube.force-ssl` scope 확보 (비공개 영상 자막 접근용)

## 실측 데이터 (2026-04-07 전수조사)

> 간호학과 채널(UCxxxxxxxxxxxxxxxxxxxxxx) 전체 2,550개 영상 조사 결과

| 구분 | 수치 | 비율 |
|------|------|------|
| 공개/미등록 (youtube-transcript-api 접근 가능) | 290 | 11.4% |
| 비공개 (OAuth Captions API 필요) | 2,259 | 88.6% |
| Phase 2 샘플 160개 중 ASR 자막 보유 | 159 | **99.4%** |
| 자막 없음 (대면강의 녹화본 등) | ~1% 추정 | |

### 핵심 발견사항

1. **YouTube Data API의 `has_captions` 필드는 수동 자막만 체크** — ASR(자동생성) 자막을 반영하지 않으므로 신뢰할 수 없음
2. **`youtube-transcript-api`는 OAuth를 사용하지 않음** — 비공개 영상에서 `VideoUnplayable` 발생
3. **Captions API(`youtube.force-ssl` scope)로 비공개 영상 자막 접근 확인됨** — list + download 모두 성공
4. **비공개 영상의 99.4%에 ASR 자막 존재** — Whisper STT는 극소수 예외에만 필요
5. **Captions API quota 제약**: list 50 + download 200 = 250 units/건, 일일 10,000 units → 하루 ~40건 다운로드

### 자막 수집 전략 (2단계)

```
Phase 1: youtube-transcript-api → 공개/미등록 영상 (quota 0, 수천 건도 가능)
Phase 2: Captions API (OAuth force-ssl) → 비공개 영상 (250 units/건, 일일 ~40건)
  └── 비교 대상 매칭 쌍에 해당하는 비공개 영상만 우선 처리 (quota 절약)
(Whisper STT → ASR도 없는 극소수 예외 시에만)
```

## 운용 규모

| 항목 | 규모 |
|------|------|
| 학과 수 | ~20개 |
| 학과당 영상 | 수백~2,550 (간호학과 기준) |
| 전체 영상 | 수천~수만 |
| 작업 주기 | 학기/월 단위, 며칠에 걸쳐 수백 건 분석 |
| 동시 작업 | 한 학과씩 순차 처리 |
| 비공개 비율 | ~88% (채널별 상이할 수 있음) |

## v0.1.1 감사 결과 반영 사항

> 2026-04-06 글로벌 감사(7 Layer, 1220 테스트)에서 발견된 사항 중 idea4에 영향을 주는 항목:

### 이미 해결된 문제 (idea4 착수 전 수정 완료)
- ✅ transcript.py 인덱싱 에러 수정 (H-06) — 자막 수집 정상 동작
- ✅ json_store default=str 제거 (M-03) — 직렬화 안전성 확보
- ✅ json_store UTF-8 BOM 지원 (M-04) — Windows 호환
- ✅ title_parser fallback 교수명 오추출 수정 (L-08) — 비교 쌍 매칭 정확도 향상
- ✅ API timeout 60초 추가 (H-03) — LLM 호출 포함 전 서비스
- ✅ YouTubeDataService rate limiter 적용 (L-05)
- ✅ GPU device 설정 인프라 (idea3.2에서 구현) — get_device() 활용 가능

### idea4 구현 시 반드시 포함할 사항

#### P-01: 임베딩 벡터 저장

sentence-transformers가 반환하는 numpy array를 Parquet에 저장 (JSON 아닌 Parquet).

구현 방안:
- `content/fingerprint.py`에서 임베딩 생성 후 polars DataFrame으로 저장
- SHA-256 해시는 별도 JSON (경량, Stage 1 비교용)

#### P-02: LLM 변경 요약 rate limiting

대량 영상 비교 시 LLM 변경 요약 반복 호출에 rate limiter 적용.

#### P-03: Excel formula injection 방어 (보고서)

`_sanitize_cell()` 방어를 콘텐츠 품질 보고서에도 적용. 변경 용어 목록, LLM 요약 텍스트 sanitize 필수.

## 주요 기능

### 1. 자막 수집 및 아카이브

모든 영상의 자막을 추출하여 구조화 저장한다. idea3의 메타데이터와 연계하여 교수/교과목/주차 단위로 조직한다.

- **공개/미등록 영상**: `youtube-transcript-api` (quota 0, 기존 구현)
- **비공개 영상**: Captions API + OAuth `youtube.force-ssl` scope (250 units/건)
- **자막 없는 영상**: Whisper STT fallback (로컬, 극소수 대상)
- 자막 텍스트 + 타임스탬프를 JSON으로 저장
- 교과목×주차 단위로 연도별 자막 아카이브 유지 (diff 분석 기반)
- 초기 1회 전량 수집 후 증분 업데이트

### 2. 영상 재사용 탐지 — 다중 지표 복합 판정

자막 텍스트를 기반으로 영상 재사용 여부를 **5가지 독립 지표**로 동시 평가한다.
단일 지표가 아닌 복합 증거 기반 판정으로 오탐을 최소화한다.

#### 2.1 5가지 독립 지표

| # | 지표 | 방법 | 비용 | 판정 기준 |
|---|------|------|------|----------|
| **I-1** | 자막 해시 일치 | SHA-256 | 0 | 해시 동일 = 글자 하나 안 바뀜 |
| **I-2** | 의미 유사도 | 임베딩 cosine similarity | 0 (로컬 추론) | 0.0~1.0 (높을수록 유사) |
| **I-3** | 텍스트 변경률 | difflib SequenceMatcher | 0 | 0~100% (낮을수록 유사) |
| **I-4** | 신규 용어 수 | set 차집합 | 0 | 0개 = 내용 갱신 없음 |
| **I-5** | 영상 길이 차이 | 메타데이터 비교 | 0 | ±10초 이내 = 의심 |

#### 2.2 의심도 종합 점수

각 지표를 0.0~1.0 정규화 → 가중 합산 → **종합 의심도(0~100)**

```
예시:
  감염미생물학 3주차 1차시 (2025 vs 2026)
  ┌─────────────────────────────────────────────┐
  │ I-1 해시 일치:     아니오                      │
  │ I-2 의미 유사도:   0.97  ██████████▌  매우 높음 │
  │ I-3 텍스트 변경률: 3%   █           거의 없음  │
  │ I-4 신규 용어:     0개                없음     │
  │ I-5 길이 차이:     +8초               거의 같음 │
  │─────────────────────────────────────────────│
  │ 종합 의심도:       92/100  🔴 최우선 점검 대상  │
  └─────────────────────────────────────────────┘
```

#### 2.3 우선순위 분류

| 등급 | 의심도 | 의미 | 행동 |
|------|--------|------|------|
| 🔴 최우선 | 80~100 | 5개 지표 대부분 일치 | 즉시 점검 |
| 🟠 높음 | 60~79 | 3~4개 지표 일치 | 금주 내 점검 |
| 🟡 참고 | 40~59 | 2개 지표 일치 | 부분 업데이트 가능성 |
| 🟢 정상 | 0~39 | 대부분 다름 | 신규 제작으로 판단 |

#### 2.4 비교 대상 매칭

idea3의 제목 파싱 결과를 활용하여 비교 쌍을 자동 매칭:

```
같은 교수 + 같은 교과목 + 같은 주차 + 같은 차시
  → 2024 vs 2025 vs 2026 연도별 비교
```

- 전수 비교(n×n)가 아닌, 교과목×주차 매칭으로 비교 쌍 최소화
- 2,550개 영상이라도 실제 비교 쌍은 수백 건 수준

> **슬라이드만 동일하고 음성을 새로 녹음한 경우**: 자막이 다르므로 "신규 제작"으로 판정됨. 교수가 같은 강의자료로 새로 설명한 것이므로 새로운 콘텐츠로 인정.

### 3. 관리자 리뷰 워크플로우 (ytsubs 통합)

자동 판정만으로 교수에게 통보하면 문제가 생긴다. **반드시 사람이 점검**해야 한다.

```
자동 분석 (의심도 산출)
  → 보고서 출력 (의심도 순 정렬, 🔴부터)
  → 교무과 담당자 점검
  → 상태 마킹: "확정 중복" / "오탐(정상)"
  → 결과 DB에 기록 (다음 분석에서 재알림 방지)
```

리뷰 상태:
- `UNREVIEWED` — 자동 분석 완료, 미점검
- `CONFIRMED_DUPLICATE` — 관리자 확인, 재사용 확정
- `FALSE_POSITIVE` — 관리자 확인, 오탐 (정상 영상)

### 4. 연도별 콘텐츠 업데이트 분석

같은 교과목+주차의 전년도 vs 올해 자막을 비교하여 콘텐츠 변경 내역을 추적한다.

#### 4.1 변경 분석 항목

| 분석 | 방법 | LLM 필요 |
|------|------|---------|
| 변경률 | difflib SequenceMatcher → 변경 문장 비율 (%) | 불필요 |
| 신규 용어 추출 | 올해 자막에만 등장하는 전공 용어 (set 차집합) | 불필요 |
| 삭제 용어 추출 | 전년도에만 등장했던 전공 용어 (제거된 내용) | 불필요 |
| 변경 요약 | diff 결과를 LLM으로 요약 | LLM 1회 (diff만 전송, 소량 토큰) |

> LLM 변경 요약은 의심도 🟡 이상일 때만 호출 (완전 동일이나 완전 신규는 불필요)

#### 4.2 보고서 출력 예시

```
감염미생물학 3주차 1차시 — 홍길동
├── 종합 의심도: 92/100 🔴
├── I-1 해시: 불일치
├── I-2 유사도: 0.97
├── I-3 변경률: 3% (2024 → 2025)
├── I-4 신규 용어: 0개
├── I-5 길이 차이: +8초
├── 리뷰 상태: UNREVIEWED
└── 변경 요약: (LLM) 인트로 문구만 "2024학년도"→"2025학년도"로 변경.
    나머지 내용 동일.
```

### 5. 교육 콘텐츠 품질 체크리스트

자막 텍스트와 메타데이터를 기반으로 영상의 교육적 기본 품질을 자동 검사한다.

#### 5.1 자동 검사 가능 항목

| 규칙 ID | 검사 항목 | 판단 기준 | 방법 |
|---------|----------|----------|------|
| Q-001 | 음성 존재 여부 | 자막 추출 가능 여부 | 자막 유무 확인 |
| Q-002 | 최소 영상 길이 | 재생시간 ≥ 5분 | 메타데이터 |
| Q-003 | 교과목 관련성 | 자막에 교과목 관련 용어 등장 비율 ≥ 10% | 로컬 키워드 매칭 |
| Q-004 | 무음/공백 비율 | 자막 세그먼트 간 갭 비율 < 30% | 타임스탬프 분석 |
| Q-005 | 말하기 밀도 | 분당 200~600자 범위 | 자막 길이 / 재생시간 |
| Q-006 | EQS 명료성 | RACED Clarity 점수 ≥ 0.3 | LLM (v2 구현) |

#### 5.2 자동 검사가 어려운 항목 (한계 명시)

| 항목 | 이유 |
|------|------|
| 설명의 정확성 | 전공 지식 없이 LLM도 오류 판단 불가 (hallucination 위험) |
| 슬라이드 품질 | 영상 프레임 분석 필요 — 비용 과다, 정확도 낮음 |
| 교수법 적절성 | 주관적 판단 영역 — 자동화 부적합 |
| 학습 목표 부합 | 실라버스가 시스템에 입력되어 있지 않은 한 대조 불가 |

### 6. 콘텐츠 품질 보고서

위 분석 결과를 종합하여 교수별/교과목별 콘텐츠 품질 보고서를 생성한다.

#### 6.1 보고서 구성

**1. 재사용 의심 현황** (의심도 순 정렬)
- 🔴🟠🟡🟢 등급별 영상 수
- 교수별 의심 영상 비율
- 최우선 점검 대상 목록

**2. 콘텐츠 업데이트 상세**
- 교과목×주차별 변경률 히트맵
- 신규/삭제 용어 목록
- LLM 변경 요약 (해당 시)

**3. 품질 체크리스트 결과**
- 교수별 Q-001~Q-006 통과율
- 미통과 항목 목록 (영상 ID, 규칙, 세부 사유)
- 전체 통과율 대시보드

**4. 관리자 리뷰 현황**
- UNREVIEWED / CONFIRMED_DUPLICATE / FALSE_POSITIVE 집계
- 리뷰 이력

#### 6.2 출력 형식

- **HTML**: 인터랙티브 차트 (plotly), 변경 diff 하이라이트
- **Excel (xlsx)**: 시트별 — 의심 현황, 업데이트 상세, 품질 체크, 리뷰 이력
- **JSON**: 프로그래밍적 접근용 구조화 데이터

## 데이터 저장 — 하이브리드 (SQLite + Parquet + JSON)

### 저장소 역할 분담

| 데이터 | 저장소 | 이유 |
|--------|--------|------|
| 영상별 처리 상태 | SQLite | 트랜잭션, 필터/정렬 쿼리, 중단 재개 |
| SHA-256 해시 인덱스 | SQLite | 빠른 조회, 누적 |
| 비교 결과 + 의심도 | SQLite | 관리자 리뷰 상태 업데이트, 조회 |
| 자막 업로드 대기열 | SQLite | 상태 추적 |
| 임베딩 벡터 | Parquet | polars 벡터 연산, 효율적 저장 |
| 자막 원본 | JSON | 기존 패턴 유지, 영상별 1파일 |
| 수집 메타데이터 | JSON/Parquet | 기존 패턴 유지 |

### 프로젝트 디렉터리 구조

```
projects/{project}/
├── tube_scout.db                    ← SQLite (신규)
│   ├── processing_status            (영상별 처리 단계)
│   ├── fingerprint_hashes           (SHA-256 인덱스)
│   ├── comparison_results           (비교 판정 + 의심도 + 리뷰 상태)
│   └── caption_upload_queue         (자막 업로드 대기열)
├── 01_collect/
│   └── channels/{channel_id}/
│       ├── videos_meta.json
│       └── transcripts/{video_id}.json    ← 자막 원본
├── 02_analyze/
│   └── content/
│       ├── embeddings.parquet             ← 임베딩 벡터
│       └── quality/{video_id}.json        ← Q-001~Q-006 결과
└── 03_report/
    └── content_quality/
        └── {channel_id}_{year}_{semester}.{html|xlsx|json}
```

### 벡터 검색 방식

학과 단위 작업이므로 비교 대상은 최대 2,000~3,000개. 이 규모에서는 polars cosine similarity 브루트포스가 수 밀리초 내 완료되므로, ChromaDB/LanceDB 등 벡터 DB는 불필요.

## OAuth scope 변경

```python
# 현재 (youtube.readonly)
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# 변경 (force-ssl 추가)
SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
```

> `youtube.force-ssl`은 `youtube.readonly`의 상위 호환 — 읽기 + 자막 CRUD 포함.
> scope 변경 시 기존 토큰 재인증 필요 (1회).

## 기술 스택 (추가)

| 기술 | 용도 | 비고 |
|------|------|------|
| sentence-transformers | 자막 임베딩 생성 (로컬 추론) | `get_device()` 활용 |
| jhgan/ko-sroberta-multitask | 한국어 특화 문장 임베딩 모델 | GPU 가속 지원 |
| difflib | 텍스트 diff, 변경률 계산 | stdlib |
| hashlib | SHA-256 자막 해시 | stdlib |
| sqlite3 | 처리 상태, 비교 결과, 리뷰 관리 | stdlib |
| Captions API | 비공개 영상 자막 접근 | `youtube.force-ssl` scope |
| LLMAdapter | 변경 요약 | rate limiter 적용 (P-02) |
| polars | 임베딩 벡터 Parquet 저장 + cosine 계산 | 기존 의존성 |

## CLI 명령 (신규)

```bash
# 단축 명령 — 전체 파이프라인 실행
tube-scout content scan --channel <별칭>
  --year-from 2025 --year-to 2026

# 개별 단계
tube-scout content fingerprint --channel <별칭>     # 자막 해시 + 임베딩 생성
tube-scout content compare --channel <별칭>          # 연도별 비교, 의심도 산출
tube-scout content quality --channel <별칭>          # 품질 체크리스트
tube-scout content review --channel <별칭>           # 리뷰 상태 조회/업데이트

# 보고서
tube-scout report content --channel <별칭>
  --format html|xlsx|json
  --year 2026 --semester 1
```

## 워크플로우

```
전제: idea3 파이프라인으로 메타데이터 수집 + 제목 파싱 완료

[초기 1회]
1. tube-scout collect transcripts --channel <학과명>     # 자막 전량 수집
   └── 공개분: 즉시 완료 / 비공개분: Captions API (며칠 소요 가능)

[주기적 (학기/월)]
2. tube-scout collect transcripts --channel <학과명>     # 신규 영상만 증분 수집
3. tube-scout content scan --channel <학과명> --year-from 2025 --year-to 2026
   └── fingerprint → compare → quality 자동 실행
4. tube-scout report content --channel <학과명> --format xlsx
5. 교무과 담당자: 🔴부터 점검 → tube-scout content review로 상태 마킹
```

## 향후 확장 가능성

- **자막 원격 업로드**: Whisper STT로 생성한 자막을 `captions.insert`로 YouTube에 업로드 (scope 이미 확보, 건당 400 units)
  - 학생 접근성 향상, 청각장애 학생 지원, 검색 가능성 증가
- **교과목별 최신 동향 키워드 대조**: 교무과가 키워드 목록 관리 → 자막 대조
- **실라버스 대조**: 학습목표와 주차별 자막 관련성 점수 산출
- **크로스모달 분석**: 영상 프레임(슬라이드)과 음성(자막) 정합도 분석

## 기대 효과

- 영상 재사용 여부를 **콘텐츠 수준에서 확정** (날짜 추정이 아닌 자막 비교)
- **다중 지표 복합 판정**으로 오탐 최소화, 관리자 부담 경감
- 교수별 콘텐츠 **업데이트 노력을 정량화** (변경률, 신규 용어 수)
- 교육 품질의 **기본 수준을 자동 검증** (무음, 최소 길이, 관련성)
- 비용 효율적: **5개 지표 중 4개가 비용 0**, LLM은 변경 요약에만 소량 사용
- YouTube API quota: 비교 대상 매칭 쌍만 Captions API 사용으로 **일일 quota 내 처리 가능**
