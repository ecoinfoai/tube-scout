# Research: Tube Scout — 강의 영상 분석 플랫폼

**Branch**: `001-lecture-video-analytics` | **Date**: 2026-04-01

## 1. YouTube Data API v3 — 영상 목록 수집

**Decision**: `playlistItems.list` + `videos.list` batch 조합 사용

**Rationale**:
- 채널 ID의 `UC` → `UU` 변환으로 uploads 재생목록 ID를 얻고, `playlistItems.list`로 열거 (1 unit/call, 50개/페이지)
- `search.list`는 100 units/call로 100배 비효율적
- 영상 상세정보(duration, viewCount 등)는 `videos.list`에 videoId를 50개씩 batch 조회 (1 unit/call)
- 1,000개 영상 수집 시: playlistItems 20 units + videos 20 units = **40 units** (search.list 사용 시 2,000 units)

**Quota 비용 요약**:

| API Method | Cost/call | Max results/call |
|---|---|---|
| `playlistItems.list` | 1 unit | 50 |
| `videos.list` | 1 unit | 50 |
| `channels.list` | 1 unit | - |
| `commentThreads.list` | 1 unit | 100 |
| `search.list` | 100 units | 50 |

일일 기본 쿼터: 10,000 units/day

**Alternatives considered**: `search.list` (quota 과다), `activities.list` (deprecated 경향)

## 2. YouTube Analytics API — 시청 유지율

**Decision**: `reports.query` 엔드포인트, 채널 소유자 OAuth2 인증 필수

**Rationale**:
- `metrics`: `audienceWatchRatio` (절대 유지율 0~1), `relativeRetentionPerformance` (유사 영상 대비 상대 유지율)
- `dimensions`: `elapsedVideoTimeRatio` (0.0~1.0 영상 진행률)
- `filters`: `video==VIDEO_ID`
- 필수 OAuth2 scope: `https://www.googleapis.com/auth/yt-analytics.readonly`
- **핵심 제약**: 본인 소유/관리 채널만 조회 가능

**Graceful Degradation**: Analytics API 접근 불가 시 `videos.list`의 `statistics`로 간접 지표(engagement rate) 산출

**Alternatives considered**: YouTube Studio 스크래핑 (ToS 위반), 3rd-party 서비스 (유료, CLI 통합 복잡)

## 3. YouTube Transcript API — 자막 수집

**Decision**: `youtube-transcript-api` Python 패키지

**Rationale**:
- API 키 불필요, quota 소모 없음
- 자동생성 + 수동 자막 모두 지원
- 한국어(`ko`) 우선 조회, 수동 자막 우선 → 자동생성 fallback
- 에러: `TranscriptsDisabled`, `NoTranscriptFound`, `VideoUnavailable` → graceful skip

**Alternatives considered**: YouTube Data API captions (소유자 전용), `yt-dlp --write-auto-sub` (별도 프로세스 필요)

## 4. 데이터 저장 전략

**Decision**: JSON (메타데이터/설정) + Parquet (시계열/분석) + JSON (체크포인트)

**Rationale**:
- JSON: 스키마 유동적인 메타데이터, 사람이 읽을 수 있는 설정/상태 파일
- Parquet: 행 수가 많은 시계열 데이터, 컬럼 기반 분석 효율, 타입 보존
- 체크포인트: atomic write (temp → rename) 패턴으로 수집 진행 상태 기록

**디렉토리 구조**:
```
data/
├── raw/
│   ├── channels/{channel_id}/
│   │   ├── channel_meta.json
│   │   ├── videos_meta.json
│   │   └── videos_meta.parquet
│   ├── transcripts/{video_id}.json
│   ├── comments/{video_id}.json
│   └── retention/{video_id}.parquet
├── processed/
│   ├── sentiment/{video_id}.parquet
│   ├── segments/{video_id}.json
│   └── eqs/{video_id}.json
├── reports/
│   ├── video/{video_id}.html
│   └── channel/{channel_id}.html
└── checkpoints/
    └── collection_state.json
```

**Resume 패턴**: `collection_state.json`에 last_page_token, last_video_id, timestamp 기록. 재실행 시 checkpoint에서 재개. `--force-refresh` 옵션으로 전체 재수집 가능.

**Alternatives considered**: SQLite (단일 파일 DB, 이식성 낮음), DuckDB (대규모 확장 시 고려)

## 5. CLI 프레임워크

**Decision**: Typer

**Rationale**:
- Python 타입 힌트에서 CLI 인터페이스 자동 생성, 최소 보일러플레이트
- `rich` 통합으로 진행률 표시, 테이블 출력 간편
- 서브커맨드 자연스럽게 매핑: `tube-scout collect`, `tube-scout analyze`, `tube-scout report`
- 내부 click 기반으로 click 생태계 호환

**Alternatives considered**: `argparse` (장황한 코드), `click` (Typer가 상위호환)

## 6. 한국어 댓글 감성분석

**Decision**: LLM API 직접 호출 (기본) + 로컬 모델 옵션

**Rationale**:
- CLI 도구에서 KoBERT(370MB+)/KoELECTRA(130MB+) 다운로드는 사용자 경험 저하
- LLM API는 감성 + 주제 분류 + 질문 추출을 단일 프롬프트로 처리 가능
- 댓글 배치(10~20개/프롬프트)로 API 호출 최소화
- 비용: 댓글 1,000건 기준 Haiku $0.02 수준

**구현 패턴**: `--sentiment-backend` 옵션으로 `llm` (기본) / `local` / `skip` 선택. 응답 캐싱(content hash)으로 재분석 방지.

**Alternatives considered**: KoBERT (과중한 의존성), Naver CLOVA (별도 과금), TextBlob/VADER (한국어 미지원)
