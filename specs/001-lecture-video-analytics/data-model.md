# Data Model: Tube Scout

**Branch**: `001-lecture-video-analytics` | **Date**: 2026-04-01

## Entity Relationship Overview

```
Channel (1) ──< Video (N) ──< Comment (N)
                  │
                  ├──< ViewingPattern (1)
                  ├──< TranscriptSegment (N)
                  ├──< QualityScore (1)
                  └──< Forecast (N)

Video (N) ──> Report (N)
Channel (1) ──> Report (N)
```

## Entities

### Channel

분석의 최상위 단위. v1은 단일 채널/단일 교수.

| Field | Type | Description |
|-------|------|-------------|
| channel_id | string | YouTube 채널 고유 ID (UC로 시작) |
| channel_name | string | 채널 표시명 |
| uploads_playlist_id | string | 업로드 재생목록 ID (UU로 시작) |
| professor_name | string | 필터링 대상 교수명 |
| total_video_count | integer | 채널 전체 영상 수 |
| filtered_video_count | integer | 교수명 필터 후 영상 수 |
| last_collected_at | datetime | 마지막 수집 시각 |

**Uniqueness**: `channel_id`
**Storage**: `data/raw/channels/{channel_id}/channel_meta.json`

### Video

채널 내 개별 영상. 교수명 필터링의 대상.

| Field | Type | Description |
|-------|------|-------------|
| video_id | string | YouTube 영상 고유 ID |
| channel_id | string | 소속 채널 ID (FK) |
| title | string | 영상 제목 |
| published_at | datetime | 업로드 일시 |
| duration_seconds | integer | 영상 길이 (초) |
| view_count | integer | 조회수 |
| like_count | integer | 좋아요 수 |
| comment_count | integer | 댓글 수 |
| has_transcript | boolean | 자막 존재 여부 |
| transcript_type | string | "manual" / "auto_generated" / null |
| has_analytics | boolean | Analytics API 접근 가능 여부 |
| collected_at | datetime | 메트릭 수집 시각 |

**Uniqueness**: `video_id`
**Storage**: `data/raw/channels/{channel_id}/videos_meta.json` (목록), `data/raw/channels/{channel_id}/videos_meta.parquet` (분석용)

### ViewingPattern

영상의 구간별 시청 데이터. Analytics API 필수.

| Field | Type | Description |
|-------|------|-------------|
| video_id | string | 대상 영상 ID (FK) |
| elapsed_ratio | float | 영상 진행률 (0.0~1.0) |
| audience_watch_ratio | float | 절대 시청 유지율 (0.0~1.0) |
| relative_retention | float | 유사 영상 대비 상대 유지율 |
| is_rewatch_hotspot | boolean | Rewatch Hotspot 여부 |
| is_skip_zone | boolean | Skip Zone 여부 |
| collected_at | datetime | 수집 시각 |

**Uniqueness**: `(video_id, elapsed_ratio)`
**State transitions**: N/A (immutable snapshot, 재수집 시 전체 교체)
**Storage**: `data/raw/retention/{video_id}.parquet`

### Comment

영상에 달린 댓글과 분석 결과.

| Field | Type | Description |
|-------|------|-------------|
| comment_id | string | YouTube 댓글 고유 ID |
| video_id | string | 대상 영상 ID (FK) |
| author | string | 작성자 표시명 |
| text | string | 댓글 원문 |
| published_at | datetime | 작성 일시 |
| like_count | integer | 댓글 좋아요 수 |
| sentiment | string | "positive" / "negative" / "neutral" |
| topics | list[string] | 추출된 토픽 목록 |
| is_question | boolean | 질문 여부 |
| analysis_backend | string | "llm" / "local" / null |
| analyzed_at | datetime | 분석 시각 |

**Uniqueness**: `comment_id`
**Storage**: `data/raw/comments/{video_id}.json` (원본), `data/processed/sentiment/{video_id}.parquet` (분석 결과)

### TranscriptSegment

자막 기반 의미론적 구간 분절.

| Field | Type | Description |
|-------|------|-------------|
| video_id | string | 대상 영상 ID (FK) |
| segment_index | integer | 구간 순서 (0-based) |
| start_seconds | float | 구간 시작 시간 (초) |
| end_seconds | float | 구간 종료 시간 (초) |
| title | string | 구간 제목 (LLM 생성) |
| text | string | 구간 전체 자막 텍스트 |
| summary | string | 구간 요약 (LLM 생성) |
| difficulty_score | float | 난이도 점수 (0.0~1.0) |
| tags | list[string] | 주제 태그 목록 |

**Uniqueness**: `(video_id, segment_index)`
**Storage**: `data/processed/segments/{video_id}.json`

### QualityScore (EQS)

영상의 교육 품질 평가. RACED 5축.

| Field | Type | Description |
|-------|------|-------------|
| video_id | string | 대상 영상 ID (FK) |
| relevance | float | 관련성 점수 (0.0~1.0) |
| accuracy | float | 정확성 점수 (0.0~1.0) |
| clarity | float | 명료성 점수 (0.0~1.0) |
| engagement | float | 참여도 점수 (0.0~1.0) |
| depth | float | 깊이 점수 (0.0~1.0) |
| overall | float | 종합 점수 (5축 가중 평균) |
| evaluated_at | datetime | 평가 시각 |

**Uniqueness**: `video_id`
**Storage**: `data/processed/eqs/{video_id}.json`

### Forecast

시계열 예측 결과.

| Field | Type | Description |
|-------|------|-------------|
| channel_id | string | 대상 채널 ID (FK) |
| metric_name | string | 예측 대상 메트릭 ("view_count", "watch_time") |
| date | date | 예측 날짜 |
| predicted_value | float | 예측값 |
| lower_bound | float | 신뢰 구간 하한 |
| upper_bound | float | 신뢰 구간 상한 |
| is_anomaly | boolean | 이상치 여부 (과거 데이터) |
| anomaly_reason | string | 이상치 추정 원인 (null 가능) |

**Uniqueness**: `(channel_id, metric_name, date)`
**Storage**: `data/processed/forecast/{channel_id}_{metric_name}.parquet`

### Report

분석 리포트 메타데이터.

| Field | Type | Description |
|-------|------|-------------|
| report_id | string | UUID |
| report_type | string | "video" / "channel" / "comment_insight" |
| target_id | string | video_id 또는 channel_id |
| generated_at | datetime | 생성 시각 |
| format | string | "html" / "notebook" |
| file_path | string | 출력 파일 경로 |

**Uniqueness**: `report_id`
**Storage**: 메타데이터는 `data/reports/index.json`, 실제 파일은 `data/reports/video/` 또는 `data/reports/channel/`

### CollectionState (체크포인트)

수집 진행 상태. Resume 패턴 지원.

| Field | Type | Description |
|-------|------|-------------|
| channel_id | string | 수집 대상 채널 |
| phase | string | "videos" / "comments" / "transcripts" / "retention" |
| last_page_token | string | 마지막 페이지 토큰 |
| last_video_id | string | 마지막 처리 영상 ID |
| total_expected | integer | 예상 총 항목 수 |
| total_collected | integer | 수집 완료 항목 수 |
| started_at | datetime | 수집 시작 시각 |
| updated_at | datetime | 마지막 갱신 시각 |
| status | string | "in_progress" / "completed" / "interrupted" |

**Uniqueness**: `(channel_id, phase)`
**State transitions**: `in_progress` → `completed` | `in_progress` → `interrupted` → `in_progress` (resume)
**Storage**: `data/checkpoints/collection_state.json`

## Validation Rules

- `channel_id`는 `UC`로 시작하는 24자 문자열
- `video_id`는 11자 영숫자+하이픈+언더스코어
- 모든 점수(difficulty_score, EQS 각 축)는 0.0~1.0 범위
- `elapsed_ratio`는 0.0~1.0 범위, 단조 증가
- `start_seconds` < `end_seconds` (TranscriptSegment)
- `professor_name`은 비어있지 않은 문자열
