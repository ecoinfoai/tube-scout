# Data Model: Multi-Channel Administration

**Date**: 2026-04-04

## New Models

### ChannelRegistration

A registered department channel.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| alias | str | Non-blank, unique | Human-readable department name (e.g., "간호학과") |
| channel_id | str | UC-prefix validated | YouTube channel ID |
| channel_name | str | Non-blank | Channel display name from YouTube |
| registered_at | str | ISO datetime | First registration timestamp |
| last_used_at | str | ISO datetime | Last successful authentication |
| token_path | str | Valid file path | Path to token JSON file |

### ParsedTitle

Structured data extracted from a video title.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| video_id | str | Non-blank | YouTube video ID |
| original_title | str | Non-blank | Unmodified original title |
| professor | list[str] | May be empty | One or more professor names |
| course | str \| None | | Course/subject name |
| year | int \| None | 2000-2099 if present | Academic year |
| semester | int \| None | 1 or 2 if present | Semester number |
| week | int \| None | 1-16 if present | Week number |
| session | int \| None | >= 1 if present | Session/class number |
| department | str \| None | | Department name if in title |
| category | str | "regular" or "supplementary" | Regular lecture or supplementary content |
| parse_error | bool | | True if title could not be fully parsed |
| matched_pattern | str \| None | | Pattern name that matched |

### TitlePattern

A regex pattern for title parsing.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| name | str | Non-blank, unique | Pattern identifier (e.g., "standard_kr") |
| pattern | str | Valid regex | Regex with named groups |
| priority | int | >= 1 | Lower = tried first |
| description | str | | Human-readable pattern description |

### SearchFilter

Single filter criteria set (AND logic within).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| professor | str \| None | | Partial match |
| course | str \| None | | Partial match |
| year | int \| None | | Exact match |
| semester | int \| None | 1 or 2 | Exact match |
| week_range | list[int] \| None | [start, end] | Inclusive range |
| session | int \| None | | Exact match |

### SearchQuery

Complete search configuration (from YAML).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| filters | SearchFilter \| None | | Single AND filter |
| queries | list[SearchFilter] | | Multiple OR-combined queries |
| exclude | ExcludeRule \| None | | Exclusion patterns |

### ExcludeRule

Exclusion criteria.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| title_contains | list[str] | | Exclude videos with these keywords |

### ValidationFinding

A detected anomaly.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| rule_id | str | V-001 to V-009 | Validation rule identifier |
| severity | str | "ERROR", "WARNING", "INFO" | Severity level |
| video_ids | list[str] | Non-empty | Affected video(s) |
| professor | str \| None | | Affected professor (if applicable) |
| description | str | Non-blank, English | Human-readable finding description |
| details | dict | | Rule-specific details (e.g., expected vs actual year) |

### DepartmentOverview

Department-level summary metrics.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| channel_id | str | UC-prefix validated | Source channel |
| channel_name | str | | Department name |
| year | int \| None | | Scoped year (if filtered) |
| semester | int \| None | | Scoped semester (if filtered) |
| total_videos | int | >= 0 | Total video count |
| total_professors | int | >= 0 | Unique professor count |
| total_courses | int | >= 0 | Unique course count |
| total_duration_hours | float | >= 0 | Total duration in hours |
| total_views | int | >= 0 | Total view count |
| parse_success_rate | float | 0.0-1.0 | Title parse success percentage |

### ProfessorDetail

Per-professor analysis metrics.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| professor_name | str | Non-blank | Professor name |
| video_count | int | >= 0 | Number of videos |
| courses | list[str] | | Courses taught |
| weekly_coverage | float | 0.0-1.0 | Percentage of weeks with uploads (1-16) |
| session_completeness | float | 0.0-1.0 | Average sessions per week / expected sessions |
| avg_duration_minutes | float | >= 0 | Average video duration |
| total_views | int | >= 0 | Total views across all videos |
| avg_views | float | >= 0 | Average views per video |
| validation_error_count | int | >= 0 | Number of validation findings |

### ComplianceMatrix

Professor × Week upload status for heatmap.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| professor_name | str | Non-blank | Row identifier |
| week_statuses | dict[int, str] | Keys 1-16, values: "uploaded", "missing", "late" | Per-week status |
| upload_deadline_compliance | float | 0.0-1.0 | Percentage uploaded before week start |

### OutputRun

Metadata for a timestamped output directory.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| run_id | str | Format: report-YYYYMMDD-HHMM | Directory name |
| created_at | str | ISO datetime | Run start time |
| channel_id | str \| None | | Channel analyzed |
| year | int \| None | | Scoped year |
| semester | int \| None | | Scoped semester |
| output_path | str | Valid directory path | Absolute path to output directory |

## Entity Relationships

```
ChannelRegistration 1──* Video (via channel_id)
Video 1──1 ParsedTitle (via video_id)
ParsedTitle *──1 TitlePattern (via matched_pattern)
SearchQuery 1──* SearchFilter (via queries)
SearchQuery 1──1 ExcludeRule (via exclude)
ParsedTitle *──* ValidationFinding (via video_ids)
DepartmentOverview 1──* ProfessorDetail (via channel)
DepartmentOverview 1──1 ComplianceMatrix (via channel+year+semester)
OutputRun 1──* all stored artifacts
```

## Storage Layout

```
output/
└── report-20260404-1211/
    ├── raw/
    │   └── channels/{channel_id}/
    │       ├── videos_meta.json
    │       └── channel_meta.json
    ├── parsed/
    │   └── {channel_id}/
    │       ├── parsed_titles.json        ← list[ParsedTitle]
    │       ├── professors.json           ← list[ProfessorDetail]
    │       └── courses.json              ← course → video_id mapping
    ├── validation/
    │   └── {channel_id}/
    │       └── {year}_{semester}.json    ← list[ValidationFinding]
    └── reports/
        └── department/
            └── {channel_id}_{year}_{semester}.{html|xlsx|pdf}

~/.config/tube-scout/
├── client_secret_*.json
└── tokens/
    ├── channels.json                     ← dict[alias, ChannelRegistration]
    ├── 간호학과.json
    └── 물리치료과.json
```
