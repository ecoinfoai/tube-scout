# CLI Commands Contract: v2 Extensions

**Date**: 2026-04-04

## New and Modified Commands

### Collection Commands

#### `tube-scout collect analytics`

Collect all YouTube Analytics report types for the configured channel.

```
tube-scout collect analytics [OPTIONS]

Options:
  --start-date TEXT     Override default 2-year lookback (ISO date: YYYY-MM-DD)
  --report-type TEXT    Collect only a specific report type
                        (daily|traffic|demographics|geography|device|playback|subscribers|engagement)
  --video-id TEXT       Collect for a specific video only (where applicable)
  --incremental / --full  Incremental (default) or full re-collection
```

**Exit Codes**: 0 = success, 1 = auth error, 2 = quota exhausted, 3 = API error

#### `tube-scout collect videos` (modified)

Extended to collect full metadata (description, tags, category, thumbnails, language, privacy, topics, captions).

```
tube-scout collect videos [OPTIONS]

Options:
  --force-refresh       Re-collect all videos (default: incremental, new videos only)
```

**New behavior**: On re-run without `--force-refresh`, only newly uploaded videos are collected.

#### `tube-scout collect comments` (modified)

Extended to collect reply comments.

```
tube-scout collect comments [OPTIONS]

Options:
  --video-id TEXT       Collect for a specific video
  --include-replies / --no-replies  Include reply comments (default: include)
```

#### `tube-scout collect bulk`

YouTube Reporting API bulk data download.

```
tube-scout collect bulk [OPTIONS]

Options:
  --report-type TEXT    Reporting API report type ID
  --status              Show status of existing jobs instead of creating new
```

### Analysis Commands

#### `tube-scout analyze sentiment` (modified)

```
tube-scout analyze sentiment [OPTIONS]

Options:
  --video-id TEXT             Analyze specific video
  --sentiment-backend TEXT    Backend: llm (default) | local
```

**Changed**: Removed `skip` backend from user-facing options. No automatic fallback between backends.

#### `tube-scout analyze topic`

New command for topic extraction and question-hotspot cross-reference.

```
tube-scout analyze topic [OPTIONS]

Options:
  --video-id TEXT       Analyze specific video
```

#### `tube-scout analyze transcript` (modified)

Now connects to LLM for actual segmentation.

#### `tube-scout analyze eqs` (modified)

Now connects to LLM for actual RACED scoring.

#### `tube-scout analyze forecast` (modified)

```
tube-scout analyze forecast [OPTIONS]

Options:
  --video-id TEXT       Forecast for specific video
  --model TEXT          Model: auto (default) | linear | arima | prophet
  --calendar TEXT       Path to academic calendar JSON
  --horizon-days INT    Forecast horizon in days (default: 30)
```

### Report Commands

#### `tube-scout report comment-insight`

New command for comment insight report.

```
tube-scout report comment-insight [OPTIONS]

Options:
  --video-id TEXT       Report for specific video (required)
  --format TEXT         Output format: html (default) | notebook
  --output-dir TEXT     Output directory
```

#### `tube-scout report channel` (modified)

Extended with comparison tables, trend charts, forecasts, and improvement suggestions.

### Configuration Commands

#### `tube-scout calendar set`

Set academic calendar for forecasting.

```
tube-scout calendar set --file PATH
```

**Input Format**: JSON file with CalendarEvent array.

```json
{
  "events": [
    {"name": "spring_midterm", "start_date": "2026-04-20", "end_date": "2026-04-24", "event_type": "exam"},
    {"name": "spring_semester_end", "start_date": "2026-06-20", "end_date": "2026-06-20", "event_type": "semester_end"}
  ]
}
```

#### `tube-scout calendar show`

Display current academic calendar.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| YOUTUBE_API_KEY | (required) | YouTube Data API key |
| TUBE_SCOUT_CLIENT_SECRET | auto-detect | Path to OAuth client secret JSON |
| TUBE_SCOUT_LLM_PROVIDER | claude | LLM provider: "claude" or "openai" |
| ANTHROPIC_API_KEY | (required if provider=claude) | Claude API key |
| OPENAI_API_KEY | (required if provider=openai) | OpenAI API key |

## Error Messages

All error messages in English per project convention.

| Code | Message Pattern |
|------|----------------|
| AUTH_ERROR | "OAuth credentials required. Run tube-scout init first." |
| QUOTA_EXHAUSTED | "YouTube API quota exhausted. Retry after midnight Pacific Time." |
| LLM_UNAVAILABLE | "LLM backend '{backend}' is unavailable: {reason}. Use --sentiment-backend to select alternative." |
| NO_DATA | "No {data_type} data found for video {video_id}. Run 'tube-scout collect {phase}' first." |
| CALENDAR_INVALID | "Academic calendar file is invalid: {reason}" |
