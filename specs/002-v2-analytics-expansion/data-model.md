# Data Model: Tube Scout v2 Analytics Expansion

**Date**: 2026-04-04

## Extended Existing Models

### Video (extended)

Existing fields preserved. New fields added:

| Field | Type | Notes |
|-------|------|-------|
| description | str \| None | Video description text |
| tags | list[str] | Video tags, empty list if none |
| category_id | str \| None | YouTube category ID |
| thumbnail_url | str \| None | Default thumbnail URL |
| default_language | str \| None | ISO 639-1 language code |
| privacy_status | str | "public", "unlisted", "private" |
| topic_categories | list[str] | Wikipedia topic URLs from topicDetails |
| has_captions | bool | Whether captions are available |

### Channel (extended)

Existing fields preserved. New fields added:

| Field | Type | Notes |
|-------|------|-------|
| subscriber_count | int | Channel subscriber count |
| total_view_count | int | Total channel views |
| description | str \| None | Channel description text |

### Comment (extended)

Existing fields preserved. New fields added:

| Field | Type | Notes |
|-------|------|-------|
| parent_comment_id | str \| None | None for top-level, parent ID for replies |
| reply_count | int | Number of replies (top-level only, 0 for replies) |

### CollectionState (extended)

Existing fields preserved. New fields added:

| Field | Type | Notes |
|-------|------|-------|
| analytics_last_dates | dict[str, str] | Map of report_type -> last collected ISO date |

### Settings (extended)

Existing fields preserved. New fields added:

| Field | Type | Notes |
|-------|------|-------|
| llm_provider | str | "claude" (default) or "openai" |
| analytics_start_date | str \| None | Override for default 2-year window, ISO date |

## New Models

### AcademicCalendar

User-provided academic calendar for forecasting annotations.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| events | list[CalendarEvent] | Non-empty | Academic events list |

### CalendarEvent

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| name | str | Non-blank | Event name (e.g., "midterm_exam") |
| start_date | str | ISO date format | Event start |
| end_date | str | ISO date format, >= start_date | Event end |
| event_type | str | One of: "semester_start", "semester_end", "exam", "assignment", "holiday", "other" | Categorization |

### AnalyticsReport

Base model for all analytics report types.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| report_type | str | One of: "daily", "traffic", "demographics", "geography", "device", "playback_location", "subscribers", "engagement" | Report identifier |
| channel_id | str | UC-prefix validated | Source channel |
| video_id | str \| None | None for channel-level | Per-video scope (optional) |
| start_date | str | ISO date | Query range start |
| end_date | str | ISO date | Query range end |
| collected_at | str | ISO datetime | Collection timestamp |
| rows | list[dict] | Non-empty for valid report | Dimension-metric data rows |

### DailyMetrics

One row from the daily time-series report.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| date | str | ISO date | Day |
| views | int | >= 0 | Daily views |
| estimated_minutes_watched | float | >= 0.0 | Watch time in minutes |
| average_view_duration | float | >= 0.0 | Average view duration in seconds |
| average_view_percentage | float | 0.0-100.0 | Percentage of video watched |

### TrafficSource

One row from traffic source report.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| source_type | str | Non-blank | e.g., "SEARCH", "SUGGESTED", "EXTERNAL", "BROWSE" |
| views | int | >= 0 | Views from this source |
| estimated_minutes_watched | float | >= 0.0 | Watch time from this source |

### DemographicGroup

One row from demographics report.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| age_group | str | Non-blank | e.g., "age18-24", "age25-34" |
| gender | str | "male", "female", "user_specified" | Viewer gender |
| viewer_percentage | float | 0.0-100.0 | Percentage of viewers |

### GeographyData

One row from geography report.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| country | str | ISO 3166-1 alpha-2 | Country code |
| views | int | >= 0 | Views from this country |
| estimated_minutes_watched | float | >= 0.0 | Watch time |

### DeviceData

One row from device report.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| device_type | str | Non-blank | e.g., "MOBILE", "DESKTOP", "TABLET", "TV" |
| operating_system | str | Non-blank | e.g., "ANDROID", "IOS", "WINDOWS" |
| views | int | >= 0 | Views |
| estimated_minutes_watched | float | >= 0.0 | Watch time |

### PlaybackLocation

One row from playback location report.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| location_type | str | Non-blank | "WATCH", "EMBEDDED", "EXTERNAL", "MOBILE" |
| views | int | >= 0 | Views |
| estimated_minutes_watched | float | >= 0.0 | Watch time |

### SubscriberChange

One row from subscriber change report.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| date | str | ISO date | Day |
| subscribers_gained | int | >= 0 | New subscribers |
| subscribers_lost | int | >= 0 | Lost subscribers |

### TopicCluster

Result of topic extraction from comments.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| video_id | str | Non-blank | Source video |
| topic_label | str | Non-blank | Auto-generated topic name |
| comment_ids | list[str] | Non-empty | Comments in this cluster |
| sentiment_distribution | dict[str, float] | Keys: positive/neutral/negative, values sum to 1.0 | Aggregate sentiment |
| representative_comments | list[str] | Max 3 | Most representative comment texts |

### QuestionMatch

Result of question-hotspot cross-reference.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| video_id | str | Non-blank | Source video |
| comment_id | str | Non-blank | Question comment |
| question_text | str | Non-blank | Extracted question |
| matched_hotspot_start | float | 0.0-1.0 | Hotspot elapsed_ratio start |
| matched_hotspot_end | float | 0.0-1.0 | Hotspot elapsed_ratio end |
| relevance_score | float | 0.0-1.0 | Match confidence |

### ImprovementSuggestion

Data-driven recommendation for report output.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| video_id | str \| None | None for channel-level | Scope |
| category | str | One of: "length", "structure", "difficulty", "engagement", "content" | Suggestion type |
| suggestion | str | Non-blank | Human-readable recommendation |
| evidence | str | Non-blank | Supporting data summary |
| priority | str | "high", "medium", "low" | Urgency |

### ReportingJob

YouTube Reporting API job state.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| job_id | str | Non-blank | YouTube Reporting API job ID |
| report_type_id | str | Non-blank | YouTube report type identifier |
| channel_id | str | UC-prefix validated | Source channel |
| created_at | str | ISO datetime | Job creation time |
| status | str | "pending", "ready", "downloaded", "failed" | Job lifecycle |
| download_url | str \| None | Set when status=ready | CSV download URL |
| downloaded_at | str \| None | Set when status=downloaded | Download completion time |

## Entity Relationships

```
Channel 1──* Video
Video 1──* Comment
Comment 0──* Comment (replies via parent_comment_id)
Video 1──* ViewingPattern (existing)
Video 1──* TranscriptSegment (existing)
Video 1──1 QualityScore (existing)
Video 1──* AnalyticsReport
Channel 1──* AnalyticsReport (channel-level reports)
Video 1──* TopicCluster
TopicCluster *──* Comment (via comment_ids)
Video 1──* QuestionMatch
Channel 1──1 AcademicCalendar
Channel 1──* Forecast (existing, extended)
Video 1──* ImprovementSuggestion
Channel 1──* ImprovementSuggestion (channel-level)
Channel 1──* ReportingJob
```

## Storage Layout (new paths)

```
data/
├── raw/
│   ├── analytics/{channel_id}/
│   │   ├── daily/{video_id}.parquet       # DailyMetrics per video
│   │   ├── daily/channel.parquet          # Channel-level daily
│   │   ├── traffic/{video_id}.json        # TrafficSource per video
│   │   ├── demographics/channel.json      # DemographicGroup
│   │   ├── geography/{video_id}.json      # GeographyData per video
│   │   ├── device/{video_id}.json         # DeviceData per video
│   │   ├── playback/{video_id}.json       # PlaybackLocation per video
│   │   ├── subscribers/channel.parquet    # SubscriberChange daily
│   │   └── engagement/{video_id}.json     # Engagement summary
│   └── reporting/{channel_id}/
│       └── {report_type}_{date}.csv       # Bulk download CSVs
├── processed/
│   ├── topics/{video_id}.json             # TopicCluster results
│   ├── questions/{video_id}.json          # QuestionMatch results
│   └── suggestions/{video_id}.json        # ImprovementSuggestion
├── config/
│   └── academic_calendar.json             # AcademicCalendar
└── checkpoints/
    └── {channel_id}_analytics_{report_type}.json
```
