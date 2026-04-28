# Data Model: 006-report-filter-pdf-bundle

## Entities

### VideoFilter (기존 — 변경 없음)

**위치**: `models/video_filter.py`

| Field | Type | Description |
|-------|------|-------------|
| keyword | str \| None | 제목 substring 매칭 키워드 |
| published_after | datetime \| None | 게시일 시작 범위 (inclusive) |
| published_before | datetime \| None | 게시일 종료 범위 (inclusive) |
| video_ids | list[str] \| None | 특정 영상 ID 목록 |

Validator: 최소 1개 조건 필수, date range 유효성 검증.

### FilterResult (신규 — 경량 NamedTuple 또는 dict)

| Field | Type | Description |
|-------|------|-------------|
| videos | list[dict] | 필터된 영상 메타데이터 목록 |
| total_count | int | 필터 결과 영상 수 |
| total_duration_seconds | int | 필터 결과 총 재생시간 |
| filter_description | str | 적용된 필터 조건 요약 텍스트 |

### ChannelSummary (신규 — BundleReportGenerator 내부)

| Field | Type | Description |
|-------|------|-------------|
| channel_name | str | 채널명 (channel_meta.json에서) |
| total_videos | int | 채널 전체 영상 수 |
| professor_distribution | dict[str, int] | 교수별 영상 수 |
| course_list | list[str] | 교과목 목록 |
| semester_breakdown | dict[str, int] | 학기별 영상 수 |

### CoverPage (기존 template context 확장)

| Field | Type | Description |
|-------|------|-------------|
| channel_name | str | 채널명 (기존: channel_id) |
| filter_description | str | 적용된 필터 조건 |
| video_count | int | 포함된 영상 수 |
| total_duration_minutes | float | 총 재생시간 (분) |
| generation_date | str | 보고서 생성일 |
| title | str \| None | 사용자 지정 제목 |

## Relationships

```
VideoFilter ──filter──→ FilterResult
                            │
                    ┌───────┴───────┐
                    ▼               ▼
            ChannelSummary    BundleReport
                    │               │
                    └───────┬───────┘
                            ▼
                        CoverPage
```

## Sort Options (기존 + 1개 추가)

| Key | Description | Direction |
|-----|-------------|-----------|
| `date` | 게시일 | 내림차순 (기존) |
| `date_asc` | 게시일 | 오름차순 (**신규**) |
| `course` | 교과목→주차→차시 | 오름차순 (기존) |
| `views` | 조회수 | 내림차순 (기존) |
