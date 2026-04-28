# Tube Scout v2 — 추가 개발 기능

v1에서 구현되지 않은 기능과 신규 확장 기능을 정리한다.

## Phase 1: 데이터 수집 완성

### 1.1 YouTube Analytics API 전체 활용

현재 Retention 1개 리포트만 수집 중. OAuth 스코프(`yt-analytics.readonly`)로 접근 가능한 나머지 리포트를 모두 수집한다.

| 리포트 | dimensions | metrics | 용도 |
|--------|------------|---------|------|
| 일별 시계열 | `day` | views, estimatedMinutesWatched, averageViewDuration, averageViewPercentage | forecaster 입력 데이터 |
| 트래픽 소스 | `insightTrafficSourceType` | views, estimatedMinutesWatched | 검색/추천/외부 유입 분석 |
| 인구통계 | `ageGroup, gender` | viewerPercentage | 수강생 프로필 |
| 지역별 | `country` | views, estimatedMinutesWatched | 지역 도달률 |
| 디바이스 | `deviceType, operatingSystem` | views, estimatedMinutesWatched | 모바일 vs 데스크톱 학습 패턴 |
| 재생 위치 | `insightPlaybackLocationType` | views, estimatedMinutesWatched | YouTube vs 임베드 vs 외부 |
| 구독자 변동 | `day` | subscribersGained, subscribersLost | 채널 성장 추적 |
| 참여 지표 | `video` | shares, likes, comments, averageViewPercentage | 영상 간 비교 |

### 1.2 YouTube Data API 수집 확장

| 항목 | 현재 | 추가 |
|------|------|------|
| 채널 정보 | 이름, 영상 수 | 구독자 수, 총 조회수, 설명, 썸네일 |
| 영상 목록 | ID, 제목, 게시일 | 설명, 태그, 카테고리, 썸네일 URL, 기본 언어 |
| 영상 상세 | 재생시간, 조회/좋아요/댓글 수 | 비공개 상태, 토픽 카테고리, 캡션 유무 |
| 댓글 | 최상위 댓글만 | **대댓글(replies)** 수집, 답글 수 |

### 1.3 YouTube Reporting API (벌크 다운로드)

대량 데이터를 일괄 다운로드하는 비동기 리포트 API. 일별 시계열이 수천 건 이상인 채널에 유용하다.

- 리포트 작업 생성 → 완료 대기 → CSV 다운로드
- Analytics API 실시간 쿼리 대비 할당량 절약

### 1.4 신규 업로드 자동 감지

- `collect videos`를 재실행하면 기존 데이터와 diff하여 신규 영상만 추가 수집
- 선택적: cron/systemd timer를 통한 자동 실행

---

## Phase 2: 댓글 분석 도구

> 현재 대상 채널은 댓글 비활성화 상태이나, 범용 영상 분석 도구로 활용하기 위해 구현한다.

### 2.1 LLM 기반 감성 분석

- `sentiment.py`의 `backend="llm"` 구현 (현재 `NotImplementedError`)
- Claude / GPT-4o API 연동
- 배치 분석 + 콘텐츠 해시 캐싱 (기존 인프라 활용)

### 2.2 한국어 NLP 모델 감성 분류

- `backend="local"` 구현
- KoBERT 또는 KoELECTRA 기반 로컬 추론
- LLM 대비 비용 절감, 오프라인 실행 가능

### 2.3 토픽-감성 맵핑

- 댓글에서 논의 주제(Topic) 자동 추출
- 주제별 감성 분리: "어떤 내용에 대해 어떤 반응인지"
- BERTopic 또는 LLM 기반 클러스터링

### 2.4 질문 자동 추출 → Hotspot 교차 분석

- `cross_reference_questions_hotspots()` 실제 연동 (현재 stub)
- 댓글 질문과 Rewatch Hotspot 대조 → 난이도 구간 이중 검증

### 2.5 댓글 인사이트 리포트

- 주제별 학생 반응 요약
- 자주 묻는 질문(FAQ) 자동 추출
- HTML/Notebook 리포트 출력

---

## Phase 3: LLM 연동 분석

### 3.1 자막 챕터 분할 및 요약

- `segmenter.py`의 LLM 호출 구현 (현재 `NotImplementedError`)
- 의미론적 단위(Topic Segment)로 영상 자동 분절
- 각 구간 핵심 내용 요약 생성

### 3.2 난이도 사전 예측

- 트랜스크립트 복잡도 분석 (어휘 수준, 개념 밀도)
- 시청 데이터 없이도 난이도 구간 사전 추정
- Retention 데이터와 교차 검증

### 3.3 주제 자동 태깅 및 지식 그래프

- 강의 내용 자동 분류
- 주제 간 연결 관계 시각화 (예: plotly 네트워크 그래프)
- LlamaIndex 활용 가능

### 3.4 교육 품질 자동 스코어링 (EQS)

- `eqs.py`의 LLM 호출 구현 (현재 `NotImplementedError`)
- RACED 5축 평가: Relevance, Accuracy, Clarity, Engagement, Depth
- 조회수/좋아요가 아닌 인지적 가치(Cognitive Value) 추정

> 참고: JSR(2024), "An Assessment of YouTube Educational Video Quality Through Machine Learning"

---

## Phase 4: 시계열 예측 고도화

### 4.1 일별 시계열 데이터 수집

- Phase 1.1의 일별 리포트 데이터를 forecaster 입력으로 연결
- 현재 forecaster는 존재하지만 입력 데이터 수집 경로가 없음

### 4.2 ARIMA / Prophet 모델 연동

- 현재 선형 회귀만 구현됨 → statsmodels ARIMA, Prophet 추가
- MAE 7.2% 수준 목표 (선행 연구 기준)

### 4.3 학기 주기 패턴 분석

- 학기 초/중/말 시청 행동 차이 정량화
- 시험 기간, 과제 마감일 등 이벤트 기반 패턴 감지

> 참고: Springer(2025), "YouTube Video Performance: ARIMA Modeling"

---

## Phase 5: 고급 분석 (장기)

### 5.1 최적 세그먼트 길이 분석

- 의미론적 단위(Topic Segment) 기반 분절 분석
- 긴 영상의 자동 분절 제안
- 교육 영상 최적 길이 연구 반영 (6~10분)

> 참고: Springer(2024), "Short, Long, and Segmented Learning Videos"

### 5.2 크로스모달 정합 분석 (Cross-Modal Alignment)

- 음성-슬라이드-자막 간 정합도 분석
- 정합도가 낮은 구간 = 학생 혼란 유발 가능 구간

> 참고: MDPI(2025), "A Comprehensive Review of Multimodal Analysis in Education"

### 5.3 썸네일/제목 A/B 테스트 분석

- YouTube Test & Compare 기능 연동
- 테스트 결과 수집 → 효과적 제목/썸네일 패턴 도출

> 참고: Influencer Marketing Hub(2025), "YouTube Test & Compare: Native A/B for CTR Lift"

### 5.4 영상 간 성과 비교

- 주제/길이/형식별 성과 차이 분석
- 대시보드 형태의 비교 리포트

---

## Phase 6: 리포트 확장

### 6.1 채널 종합 리포트 완성

- 전체 강의 영상의 트렌드, 비교 분석 + 시계열 예측 통합

### 6.2 개선 제안 리포트

- 데이터 기반 강의 영상 제작 가이드라인 자동 도출
- 최적 길이, 구성 패턴, 난이도 분배 제안

---

## Phase 7: 인프라 (사용자 직접 설정)

### 7.1 agenix 시크릿 관리

```
~/.config/secrets/           ← 중앙 저장소 (agenix 암호화)
  ├── youtube-oauth.age      ← YouTube OAuth 토큰
  ├── openai-api-key.age     ← LLM API 키
  └── google-api-key.age     ← YouTube Data API 키

프로젝트 코드는 환경변수로만 참조 (경로 하드코딩 금지)
flake.nix devShell에서 agenix → 환경변수 주입
```

> 사용자가 직접 설정한다.

---

## 향후 확장 가능성

- LMS(학습관리시스템) 데이터와 연계하여 시청 데이터 ↔ 학습 성과 상관관계 분석
- 드롭아웃 위험 예측: 시청 로그 기반 이탈 위험 학생 조기 식별
- 인지 부하(Cognitive Load) 연구: EEG/시선 추적 데이터 연계
- 학생 설문 데이터와 결합한 복합 분석
- 자동화된 주간/월간 리포트 발송
- AI 기반 썸네일 변형 자동 생성 및 테스트

## 참고 문헌

- JSR(2024), "An Assessment of YouTube Educational Video Quality Through Machine Learning"
- arXiv(2026), "EduVQA: Benchmarking AI-Generated Video Quality Assessment for Education"
- ScienceDirect(2025), "Transformer-based models for sentiment analysis of YouTube video comments"
- SciencePubCo(2024), "Hybrid NLP framework for enhanced sentiment analysis and topic detection on YouTube"
- Springer(2024), "Short, Long, and Segmented Learning Videos"
- Springer(2025), "YouTube Video Performance: ARIMA Modeling"
- ScienceDirect(2025), "FPPEV: Contrastive Feature Decomposition for Engagement Prediction"
- MDPI(2025), "A Comprehensive Review of Multimodal Analysis in Education"
- Springer(2023), "Video Analytics in Digital Learning Environments"
- Retention Rabbit(2025), "YouTube Audience Retention Benchmark Report"
- ScienceDirect(2018), "Estimating the cognitive value of YouTube's educational videos"
- Towards Data Science(2024), "Using LLMs to Learn From YouTube"
