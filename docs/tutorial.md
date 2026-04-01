# Tutorial: Tube Scout 전체 기능 가이드

## 목차

1. [프로젝트 구성](#1-프로젝트-구성)
2. [설정 관리](#2-설정-관리)
3. [데이터 수집 (collect)](#3-데이터-수집-collect)
4. [데이터 분석 (analyze)](#4-데이터-분석-analyze)
5. [리포트 생성 (report)](#5-리포트-생성-report)
6. [상태 확인 (status, list)](#6-상태-확인-status-list)
7. [데이터 디렉토리 구조](#7-데이터-디렉토리-구조)
8. [환경변수 참조표](#8-환경변수-참조표)
9. [CLI 명령어 전체 참조](#9-cli-명령어-전체-참조)

---

## 1. 프로젝트 구성

### 설치

```bash
uv sync     # 의존성 설치
uv run tube-scout --version    # 버전 확인
```

### 전체 명령 구조

```
tube-scout
├── init                    # 프로젝트 초기화
├── status                  # 수집/분석 현황
├── list                    # 영상 목록 표시
├── collect
│   ├── videos              # 영상 메타데이터 수집
│   ├── comments            # 댓글 수집
│   ├── transcripts         # 자막 수집
│   ├── retention           # 시청 유지율 수집
│   └── all                 # 전체 수집
├── analyze
│   ├── retention           # Rewatch Hotspot / Skip Zone 식별
│   ├── sentiment           # 댓글 감성/토픽/질문 분석
│   ├── transcript          # 챕터 분할 + 난이도 예측
│   ├── eqs                 # 교육 품질 점수 (RACED 5축)
│   ├── forecast            # 시계열 예측 + 이상 탐지
│   └── all                 # 전체 분석
└── report
    ├── video               # 영상별 리포트
    └── channel             # 채널 종합 리포트
```

---

## 2. 설정 관리

### init — 프로젝트 초기화

```bash
tube-scout init \
  --channel-id "UCxxxxxxxxxx" \
  --professor "홍길동" \
  --data-dir "./data"          # 기본값: ./data
```

`data/config.json`이 생성됩니다:

```json
{
  "channels": [
    {
      "channel_id": "UCxxxxxxxxxx",
      "professor_name": "홍길동"
    }
  ],
  "settings": {
    "data_dir": "./data",
    "sentiment_backend": "llm",
    "default_report_format": "html"
  }
}
```

### 채널 ID 유효성 검증

- `UC`로 시작해야 함
- 영숫자, 하이픈(`-`), 언더스코어(`_`)만 허용
- 공백이나 특수문자 포함 시 오류 발생

### 교수명 필터링

영상 제목에 교수명이 **부분 일치(substring)**하면 대상으로 선택됩니다:

| 제목 | 교수명 "홍길동" | 결과 |
|------|----------------|------|
| "해부학 - 홍길동 교수" | 포함 | 선택됨 |
| "홍길동교수 생리학 1강" | 포함 | 선택됨 |
| "2024 홍길동 특강" | 포함 | 선택됨 |
| "해부학 강의 3주차" | 미포함 | 제외 |

---

## 3. 데이터 수집 (collect)

### collect videos — 영상 메타데이터

```bash
tube-scout collect videos [--force-refresh] [--data-dir ./data]
```

**수집 항목**: video_id, 제목, 업로드일, 영상 길이, 조회수, 좋아요 수, 댓글 수

**동작 방식**:
1. 채널의 uploads 재생목록에서 전체 영상 열거 (playlistItems.list, 1 unit/call)
2. 교수명으로 필터링
3. 필터링된 영상의 상세 정보 batch 조회 (videos.list, 50개씩)
4. `data/raw/channels/{channel_id}/videos_meta.json` + `.parquet`로 저장

**API 비용**: 영상 1,000개 채널 기준 약 40 units (일일 10,000 중)

**옵션**:

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--force-refresh` | false | 체크포인트 무시, 처음부터 재수집 |
| `--data-dir` | `./data` | 데이터 저장 디렉토리 |

### collect comments — 댓글

```bash
tube-scout collect comments [--video-id VIDEO_ID] [--data-dir ./data]
```

영상별 댓글을 수집합니다 (commentThreads.list). `--video-id`를 지정하면 해당 영상만, 생략하면 전체 영상의 댓글을 수집합니다.

**저장 위치**: `data/raw/comments/{video_id}.json`

### collect transcripts — 자막

```bash
tube-scout collect transcripts [--video-id VIDEO_ID] [--data-dir ./data]
```

자막 수집 우선순위:
1. 수동 한국어 자막
2. 자동 생성 한국어 자막
3. (Whisper 설치 시) 음성 인식으로 자막 생성
4. 자막 없음 → skip + 로그 기록

**저장 위치**: `data/raw/transcripts/{video_id}.json`

> 자막 수집은 YouTube API 쿼터를 사용하지 않습니다 (별도 라이브러리 사용).

### collect retention — 시청 유지율

```bash
tube-scout collect retention [--video-id VIDEO_ID] [--data-dir ./data]
```

YouTube Analytics API를 통해 구간별 시청 유지율을 수집합니다.

**필수 조건**: 채널 소유자/관리자의 OAuth2 인증 (`YOUTUBE_OAUTH_TOKEN` 환경변수)

권한이 없으면 해당 영상을 skip하고 나머지를 계속 수집합니다 (graceful degradation).

**저장 위치**: `data/raw/retention/{video_id}.parquet`

### collect all — 전체 수집

```bash
tube-scout collect all [--force-refresh] [--data-dir ./data]
```

videos → comments → transcripts → retention 순서로 전체 수집을 실행합니다. 개별 단계에서 오류가 발생해도 다음 단계로 계속 진행합니다.

---

## 4. 데이터 분석 (analyze)

### analyze retention — 시청 패턴 분석

```bash
tube-scout analyze retention [--video-id VIDEO_ID] [--data-dir ./data]
```

시청 유지율 곡선에서 두 가지 구간을 자동 식별합니다:

- **Rewatch Hotspot**: 평균 대비 1.3배 이상 높은 시청률 구간 → 학생이 반복 시청하는 어려운 구간
- **Skip Zone**: 평균 대비 0.7배 이하 낮은 시청률 구간 → 학생이 건너뛰는 구간

결과는 터미널에 테이블로 표시되며, `data/processed/retention/{video_id}.json`에 저장됩니다.

### analyze sentiment — 댓글 분석

```bash
tube-scout analyze sentiment \
  [--video-id VIDEO_ID] \
  [--sentiment-backend llm|local|skip] \
  [--data-dir ./data]
```

각 댓글에 대해 3가지를 자동 분류합니다:

| 분류 | 설명 | 예시 |
|------|------|------|
| **감성(Sentiment)** | 긍정/부정/중립 | "설명 감사합니다" → positive |
| **토픽(Topic)** | 논의 주제 추출 | "근육 수축 부분이 헷갈려요" → ["근육 수축"] |
| **질문(Question)** | 질문 여부 식별 | "이 부분 시험에 나오나요?" → is_question: true |

**백엔드 옵션**:

| 백엔드 | 설명 | 필요한 환경변수 |
|--------|------|----------------|
| `llm` (기본) | LLM API로 분석 (정확도 높음) | `ANTHROPIC_API_KEY` 또는 `OPENAI_API_KEY` |
| `local` | 로컬 모델 사용 | 없음 (모델 다운로드 필요) |
| `skip` | 감성분석 건너뛰기 | 없음 |

동일 댓글의 재분석을 방지하기 위해 **content hash 캐싱**이 적용됩니다.

### analyze transcript — 자막 분석

```bash
tube-scout analyze transcript [--video-id VIDEO_ID] [--data-dir ./data]
```

자막을 분석하여 3가지를 산출합니다:

| 항목 | 설명 |
|------|------|
| **챕터 분할** | 영상을 의미론적 단위(Topic Segment)로 자동 분절 |
| **구간 요약** | 각 챕터의 핵심 내용 요약 |
| **난이도 점수** | 어휘/개념 밀도 기반 난이도 (0.0~1.0) |

시청 유지율 데이터가 있으면 **예측 난이도 vs 실제 Rewatch Hotspot 일치도** 비교도 수행합니다.

### analyze eqs — 교육 품질 점수

```bash
tube-scout analyze eqs [--video-id VIDEO_ID] [--data-dir ./data]
```

RACED 5축으로 교육 품질을 평가합니다:

| 축 | 영문 | 설명 | 점수 범위 |
|----|------|------|----------|
| 관련성 | Relevance | 학습 목표와의 정합도 | 0.0~1.0 |
| 정확성 | Accuracy | 내용의 사실적 정확성 | 0.0~1.0 |
| 명료성 | Clarity | 설명의 이해 용이성 | 0.0~1.0 |
| 참여도 | Engagement | 학생 집중 유지 능력 | 0.0~1.0 |
| 깊이 | Depth | 주제 다룸의 심층성 | 0.0~1.0 |

종합 점수(Overall)는 5축의 가중 평균입니다.

### analyze forecast — 시계열 예측

```bash
tube-scout analyze forecast [--data-dir ./data]
```

과거 시청 데이터(조회수)를 기반으로:

- **향후 30일 조회수 트렌드** 예측 (선형 회귀 + 신뢰 구간)
- **이상치 탐지** (z-score 기반, 시험 기간 급증/방학 급감 등)

최소 6개월(180일) 이상의 데이터가 필요합니다.

### analyze all — 전체 분석

```bash
tube-scout analyze all [--sentiment-backend llm] [--data-dir ./data]
```

sentiment → transcript → retention → eqs → forecast 순서로 전체 분석을 실행합니다.

---

## 5. 리포트 생성 (report)

### report video — 영상별 리포트

```bash
tube-scout report video \
  [--video-id VIDEO_ID] \
  [--format html|notebook] \
  [--output-dir ./custom-path] \
  [--data-dir ./data]
```

**HTML 리포트 포함 내용**:
- 영상 기본 정보 (제목, 업로드일, 조회수, 길이)
- 시청 유지율 차트 (Rewatch Hotspot/Skip Zone 하이라이트)
- 자막 챕터별 난이도 테이블
- 댓글 감성 요약
- 데이터 기반 **개선 제안** (영상 길이, 난이도 분배, 되감기 구간)

**Jupyter Notebook 리포트** (`--format notebook`):
- plotly 차트를 포함한 대화형 `.ipynb` 파일 생성
- Jupyter에서 열어서 직접 데이터를 탐색할 수 있음

### report channel — 채널 종합 리포트

```bash
tube-scout report channel \
  [--format html|notebook] \
  [--output-dir ./custom-path] \
  [--data-dir ./data]
```

**포함 내용**:
- 채널 개요 (총 영상 수, 평균 조회수, 평균 길이)
- 영상 간 비교 테이블
- 주제별 성과 분석
- 채널 운영 인사이트

### 개선 제안 엔진

리포트에 포함되는 개선 제안은 다음 데이터를 기반으로 자동 생성됩니다:

| 데이터 | 생성되는 제안 |
|--------|-------------|
| 영상 길이 > 10분 | "영상을 10분 이내로 분할하면 시청 완료율이 향상됩니다" |
| Rewatch Hotspot 다수 | "해당 구간의 보충 자료를 별도로 제공하세요" |
| Skip Zone 다수 | "해당 구간의 내용을 재구성하거나 축소를 고려하세요" |
| 난이도 점수 > 0.8 | "해당 구간에 시각 자료나 예시를 추가하세요" |

---

## 6. 상태 확인 (status, list)

### status — 수집/분석 현황

```bash
tube-scout status [--data-dir ./data]
```

채널 정보, 수집된 영상 수, 각 수집 단계의 완료 상태를 테이블로 표시합니다.

### list — 영상 목록

```bash
tube-scout list \
  [--sort published_at|view_count|like_count|duration_seconds] \
  [--limit 20] \
  [--data-dir ./data]
```

수집된 영상을 테이블로 표시합니다.

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--sort` | `published_at` | 정렬 기준 필드 |
| `--limit` | 20 | 표시할 영상 수 |

---

## 7. 데이터 디렉토리 구조

```
data/
├── config.json                          # 프로젝트 설정
├── raw/
│   ├── channels/{channel_id}/
│   │   ├── channel_meta.json            # 채널 정보
│   │   ├── videos_meta.json             # 영상 목록 (JSON)
│   │   └── videos_meta.parquet          # 영상 목록 (Parquet)
│   ├── comments/{video_id}.json         # 댓글 원본
│   ├── transcripts/{video_id}.json      # 자막 원본
│   └── retention/{video_id}.parquet     # 시청 유지율
├── processed/
│   ├── retention/{video_id}.json        # Hotspot/Skip 분석 결과
│   ├── sentiment/{video_id}.parquet     # 감성분석 결과
│   ├── segments/{video_id}.json         # 챕터 분할 결과
│   ├── eqs/{video_id}.json              # 교육 품질 점수
│   └── forecast/{channel_id}_*.json     # 시계열 예측 결과
├── reports/
│   ├── video/{video_id}.html            # 영상별 리포트
│   └── channel/{channel_id}.html        # 채널 종합 리포트
└── checkpoints/
    └── {channel_id}_{phase}.json        # 수집 진행 상태
```

---

## 8. 환경변수 참조표

| 변수 | 필수 여부 | 용도 |
|------|----------|------|
| `YOUTUBE_API_KEY` | 필수 | YouTube Data API v3 인증 |
| `YOUTUBE_OAUTH_TOKEN` | 선택 | YouTube Analytics API (시청 유지율 수집) |
| `ANTHROPIC_API_KEY` | 선택 | Claude API (감성분석, 자막분석, EQS) |
| `OPENAI_API_KEY` | 선택 | OpenAI API (ANTHROPIC 대안) |

> 코드 내에 API 키를 하드코딩하지 않습니다. 모든 인증은 환경변수를 통해서만 참조됩니다.

---

## 9. CLI 명령어 전체 참조

| 명령어 | 설명 | 주요 옵션 |
|--------|------|----------|
| `tube-scout init` | 프로젝트 초기화 | `--channel-id`, `--professor`, `--data-dir` |
| `tube-scout status` | 현황 표시 | `--data-dir` |
| `tube-scout list` | 영상 목록 | `--sort`, `--limit`, `--data-dir` |
| `tube-scout collect videos` | 영상 메트릭 수집 | `--force-refresh`, `--data-dir` |
| `tube-scout collect comments` | 댓글 수집 | `--video-id`, `--data-dir` |
| `tube-scout collect transcripts` | 자막 수집 | `--video-id`, `--data-dir` |
| `tube-scout collect retention` | 유지율 수집 | `--video-id`, `--data-dir` |
| `tube-scout collect all` | 전체 수집 | `--force-refresh`, `--data-dir` |
| `tube-scout analyze retention` | 유지율 분석 | `--video-id`, `--data-dir` |
| `tube-scout analyze sentiment` | 감성 분석 | `--video-id`, `--sentiment-backend`, `--data-dir` |
| `tube-scout analyze transcript` | 자막 분석 | `--video-id`, `--data-dir` |
| `tube-scout analyze eqs` | 교육 품질 평가 | `--video-id`, `--data-dir` |
| `tube-scout analyze forecast` | 시계열 예측 | `--data-dir` |
| `tube-scout analyze all` | 전체 분석 | `--sentiment-backend`, `--data-dir` |
| `tube-scout report video` | 영상 리포트 | `--video-id`, `--format`, `--output-dir`, `--data-dir` |
| `tube-scout report channel` | 채널 리포트 | `--format`, `--output-dir`, `--data-dir` |
