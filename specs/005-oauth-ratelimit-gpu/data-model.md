# Data Model: 005-oauth-ratelimit-gpu

**Date**: 2026-04-05

## New Entities

### RateLimitProfile

Per-service rate limiting configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| base_delay | float | varies | Seconds between requests |
| max_retries | int | varies | Maximum retry attempts on error |
| backoff_multiplier | float | varies | Multiplier for exponential backoff |
| jitter | float | 0.5 | Random delay variance (±seconds) |

**Preset instances**:
- `TRANSCRIPT_PROFILE`: base_delay=2.0, max_retries=5, backoff_multiplier=3.0, jitter=0.5
- `YOUTUBE_API_PROFILE`: base_delay=0.1, max_retries=3, backoff_multiplier=2.0, jitter=0.0

**Validation rules**:
- base_delay >= 0.0
- max_retries >= 0
- backoff_multiplier >= 1.0
- jitter >= 0.0

### StageResult

Outcome of a single pipeline stage execution.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| stage_name | str | required | Pipeline stage identifier (e.g., "videos", "transcripts") |
| status | Literal["completed", "failed", "skipped"] | required | Execution outcome |
| error_message | str | None | Error details if failed |
| items_processed | int | 0 | Number of items successfully processed |
| duration_seconds | float | 0.0 | Wall-clock execution time |

### PipelineResult

Summary of a full `collect all` pipeline run.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| channel_alias | str | None | Channel alias if --channel was specified |
| stages | list[StageResult] | [] | Results for each stage |
| started_at | datetime | required | Pipeline start time |
| completed_at | datetime | None | Pipeline completion time |
| resumed | bool | False | Whether this was a resumed run |

## Modified Entities

### CollectionState (existing, in models/config.py)

**Added fields**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| stage_completed | bool | False | Whether this stage finished in a `collect all` run |

**State transitions**:
```
not_started → in_progress → completed (stage_completed=True)
                          → failed (stage_completed=False, error recorded)
```

### Settings (existing, in models/config.py)

**Added fields**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| rate_limit_transcript | RateLimitProfile | TRANSCRIPT_PROFILE | Rate limit for transcript scraping |
| rate_limit_youtube_api | RateLimitProfile | YOUTUBE_API_PROFILE | Rate limit for YouTube Data/Analytics API |

### YouTubeDataService (existing, in services/youtube_data.py)

**Removed fields**:
- `api_key` parameter from `__init__`

**Modified constructor**:
- `__init__(self, client: Any)` — client is now required (no fallback to API key)

## Entity Relationships

```
Settings
├── rate_limit_transcript → RateLimitProfile
└── rate_limit_youtube_api → RateLimitProfile

PipelineResult
└── stages → list[StageResult]

CollectionState (per channel:phase key)
└── stage_completed: bool (new)
```

## Device Configuration (not an entity — utility function)

`get_device() -> str`: Reads `TUBE_SCOUT_DEVICE` env var, validates `{"cpu", "cuda"}`, defaults to `"cpu"`. Not stored as a persistent model — runtime-only configuration.
