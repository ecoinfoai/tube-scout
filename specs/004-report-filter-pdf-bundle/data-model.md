# Data Model: 보고서 필터링 및 PDF 종합 출력

## Entities

### VideoFilter

영상 선택 조건. 복수 조건은 AND로 조합된다.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| keyword | str \| None | No | 제목 부분 문자열 매칭 |
| published_after | date \| None | No | 게시일 시작 (inclusive) |
| published_before | date \| None | No | 게시일 종료 (inclusive) |
| video_ids | list[str] \| None | No | 직접 지정 영상 ID 목록 |

**Validation**:
- 최소 1개 필터 조건이 지정되어야 함 (전체 무필터 방지)
- published_after ≤ published_before (지정된 경우)
- video_ids 지정 시 다른 필터와 AND 조합

### BundleConfig

종합 보고서 생성 설정.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| filter | VideoFilter | Yes | - | 영상 선택 조건 |
| sort_by | str | No | "date" | 정렬 기준: "date", "course", "views" |
| title | str \| None | No | auto | 보고서 제목 (표지용) |
| output_path | Path | No | auto | PDF 출력 경로 |
| from_html | Path \| None | No | None | 기존 HTML 디렉터리 (수거 모드) |
| include_summary | bool | No | True | 채널/필터 통계 요약 포함 여부 |

### BundleReport

생성된 종합 보고서의 구조.

| Section | Description |
|---------|-------------|
| cover | 표지 — 채널명, 필터 조건, 영상 수, 생성일 |
| toc | 목차 — 영상 제목 + 페이지 번호 |
| summary | 통계 요약 — 영상 수, 총 재생시간, 평균 조회수 (optional) |
| video_sections[] | 영상별 상세 — 각각 새 페이지, 기존 video_report 내용 |

## Relationships

```
VideoFilter ──filters──▶ videos_meta.json ──produces──▶ filtered video list
                                                              │
BundleConfig ──uses──▶ filtered video list                    │
     │                                                        │
     ├── from_html=None ──▶ data → Jinja2 render → HTML → PDF
     └── from_html=path ──▶ existing HTML files → body extract → PDF
```

## Data Sources (read-only)

| Source | Path | Used by |
|--------|------|---------|
| videos_meta.json | data/raw/channels/{channel_id}/videos_meta.json | VideoFilter (title, published_at) |
| retention analysis | data/processed/retention/{video_id}.json | Video sections (hotspots, skip zones) |
| segments | data/processed/segments/{video_id}.json | Video sections (transcript segments) |
| existing HTML reports | data/reports/video/{video_id}.html | --from-html mode |
