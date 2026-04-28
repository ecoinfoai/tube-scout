# Tube Scout v1 — 강의 영상 분석 플랫폼 (구현 완료)

## 배경

대학 강의 영상이 업로드되는 YouTube 채널에서 특정 교수(예: 홍길동)의 영상을 자동으로 식별하고, 학생들의 시청 행동 데이터를 분석하여 강의 콘텐츠 제작 전략을 수립하는 도구이다.

## 핵심 목적

**강의 채널 운영 효과성 극대화** — 데이터 기반으로 강의 영상의 구성, 내용, 길이 등을 최적화한다.

## 구현 완료 기능

### 1. 영상 식별 및 수집

- YouTube 채널에서 특정 교수명(영상 제목 기준)으로 필터링
- 채널 정보 조회 (채널명, 업로드 플레이리스트, 영상 수)
- 전체 영상 목록 페이지네이션 수집
- 영상 상세 정보 배치 조회 (50건 단위)

### 2. 기본 메트릭 추출

| 카테고리 | 메트릭 | 설명 |
|----------|--------|------|
| **시청 활용도** | 조회수 | 영상별 학생 접근 빈도 |
| **시청 패턴** | 구간별 시청 유지율 곡선 | 어디서 이탈하는지 시각화 |
| | 되감기 빈도 구간(Rewatch Hotspot) | 반복 시청 = 어려운 구간 (threshold 1.3x) |
| | 건너뛰기 구간(Skip Zone) | 학생이 넘기는 구간 (threshold 0.7x) |
| **참여도** | 좋아요 수, 댓글 수 | 영상 품질에 대한 직접 피드백 |

### 3. 자막 수집

- `youtube-transcript-api`로 수동/자동 자막 수집
- 언어 우선순위: 한국어(ko) → 영어(en)
- Whisper STT 폴백 (오디오 파일 제공 시)

### 4. 시청 유지율 분석

- YouTube Analytics API를 통한 Retention 데이터 수집
- Rewatch Hotspot / Skip Zone 통계 감지

### 5. 댓글 수집

- `commentThreads.list` 페이지네이션 수집
- 댓글 ID, 작성자, 텍스트, 게시일, 좋아요 수

### 6. 시계열 예측 (기본)

- 선형 회귀 기반 예측 (95% 신뢰구간)
- Z-score 기반 이상치 탐지 (threshold 3.0σ)

### 7. 분석 리포트

- 영상별 HTML / Jupyter Notebook 리포트 생성
- 채널 종합 리포트 CLI 명령

### 8. 인프라

- **OAuth2 인증**: 토큰 캐싱/갱신, YouTube Data API + Analytics API 이중 클라이언트
- **CLI**: `typer` + `rich` 기반 (init, status, list, collect, analyze, report)
- **저장소**: JSON (atomic write) + Parquet (polars)
- **체크포인트**: 수집 중단/재개 지원
- **Pydantic v2**: 모든 데이터 모델 검증

## 데이터 소스 (v1)

- **YouTube Data API v3** — 영상 메타데이터 (제목, 조회수, 좋아요, 댓글 수, 재생시간)
- **YouTube Analytics API v2** — 구간별 시청 유지율 (OAuth 필수)
- **YouTube Transcript API** — 자막/트랜스크립트 추출

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 언어 | Python 3.11 |
| API 클라이언트 | google-api-python-client, google-auth-oauthlib |
| 자막 추출 | youtube-transcript-api (+ Whisper 폴백) |
| 데이터 처리 | pandas, polars |
| 시각화 | plotly |
| CLI | typer, rich |
| 리포트 | Jinja2 + HTML, nbformat |
| 데이터 검증 | pydantic v2 |
| 패키지 관리 | uv |

## 워크플로우

```
1. tube-scout init --channel-id <UC...> --professor <이름>
2. tube-scout collect videos          # 영상 목록 + 상세 정보
3. tube-scout collect retention       # 시청 유지율 (OAuth)
4. tube-scout collect comments        # 댓글
5. tube-scout collect transcripts     # 자막
6. tube-scout analyze retention       # Hotspot / Skip Zone
7. tube-scout analyze forecast        # 시계열 예측
8. tube-scout report video --video-id <ID>  # 리포트 생성
```

## 테스트

- 201개 테스트 (200 pass, 1 integration test 환경 의존)
- 단위 테스트, 통합 테스트, 적대적 테스트(44개 failure case) 포함

## 참고

> 구간별 시청 유지율(Retention), 되감기/건너뛰기 데이터는 YouTube Analytics API를 통해 채널 소유자 또는 관리자 권한으로만 접근 가능하다. 채널 소유자에게 OAuth 인증 협조가 필요하다.
