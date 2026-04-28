# Research: Tube Scout v2 Analytics Expansion

**Date**: 2026-04-04

## R1: YouTube Analytics API Report Types

**Decision**: Use `youtubeAnalytics.reports().query()` with 8 distinct dimension/metric combinations to collect all available analytics data.

**Rationale**: The YouTube Analytics API v2 provides a single `reports.query` endpoint. Different report types are selected by varying `dimensions` and `metrics` parameters. All reports use `ids=channel==MINE` for channel-level data and support `filters=video=={video_id}` for per-video queries.

**Available Report Types**:

| Report | dimensions | metrics | Notes |
|--------|-----------|---------|-------|
| Daily time-series | `day` | `views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage` | Primary forecaster input |
| Traffic sources | `insightTrafficSourceType` | `views,estimatedMinutesWatched` | Per-video or channel-level |
| Demographics | `ageGroup,gender` | `viewerPercentage` | Channel-level only |
| Geography | `country` | `views,estimatedMinutesWatched` | Channel or per-video |
| Device | `deviceType,operatingSystem` | `views,estimatedMinutesWatched` | Channel or per-video |
| Playback location | `insightPlaybackLocationType` | `views,estimatedMinutesWatched` | Channel or per-video |
| Subscriber changes | `day` | `subscribersGained,subscribersLost` | Channel-level only |
| Engagement | (no dimension, per-video) | `shares,likes,comments,averageViewPercentage` | Per-video summary |

**Alternatives Considered**:
- YouTube Reporting API for bulk download — included as separate FR-006 for large channels, not a replacement for real-time queries.
- Scraping YouTube Studio — rejected: violates ToS, unreliable.

## R2: YouTube Reporting API (Bulk Download)

**Decision**: Use `youtubeReporting` API v1 to create report jobs, poll for completion, and download CSV.

**Rationale**: For channels with large history, the Analytics API's per-query quota cost (typically 1-50 units) can exhaust the 10,000 daily quota. The Reporting API generates pre-built reports asynchronously with lower quota impact.

**Workflow**:
1. `reportTypes.list()` — enumerate available report types
2. `jobs.create()` — create a job for a specific report type
3. `jobs.reports.list()` — poll for available report downloads
4. Download CSV via `media.download()` URL
5. Parse CSV with polars for storage

**Alternatives Considered**:
- Analytics API only with pagination — insufficient for channels with 5+ years of daily data across 500+ videos.
- BigQuery export — requires Google Cloud project with billing, over-scoped for this CLI tool.

## R3: LLM Adapter Architecture

**Decision**: Single `LLMAdapter` class with provider selection via `TUBE_SCOUT_LLM_PROVIDER` env var (default: `claude`). Direct API calls via `anthropic` and `openai` Python SDKs.

**Rationale**: Both providers offer similar chat-completion APIs. A thin adapter with `complete(system_prompt, user_prompt) -> str` interface abstracts the provider difference. No framework (LangChain, LlamaIndex) needed for simple prompt-in/text-out usage.

**Interface**:
```python
class LLMAdapter:
    def __init__(self, provider: str = "claude", model: str | None = None)
    def complete(self, system_prompt: str, user_prompt: str) -> str
    def complete_json(self, system_prompt: str, user_prompt: str, schema: type[BaseModel]) -> BaseModel
```

**Alternatives Considered**:
- LangChain — rejected: too heavy for simple prompt/response, adds 50+ transitive dependencies.
- LlamaIndex — rejected: designed for RAG, not needed here.
- Instructor library — considered for structured output, but `complete_json` with Pydantic validation achieves same result with less overhead.

## R4: Korean NLP Sentiment Analysis (Local Backend)

**Decision**: Use `transformers` library with a pre-trained Korean sentiment model (e.g., `snunlp/KR-FinBert-SC` or `beomi/KcELECTRA-base-v2022`). CPU inference acceptable.

**Rationale**: KoBERT and KoELECTRA are the most widely used Korean NLP models. The `transformers` library from Hugging Face provides unified pipeline interface. GPU is optional; CPU inference handles comment batches within acceptable time (100 comments in ~30-60 seconds on modern CPU).

**Interface**: Implements same `SentimentService` interface as LLM backend. Backend selected via `--sentiment-backend local` CLI flag.

**Alternatives Considered**:
- KoBERT via SKT's original repo — rejected: unmaintained, complex setup.
- Fine-tuning on lecture comments — deferred: requires labeled dataset not yet available.
- Korean BERT from KLUE — viable alternative, similar performance.

## R5: Topic Extraction and Clustering

**Decision**: LLM-based topic extraction using structured output (Pydantic models). Each comment analyzed for topic label, sentiment, and is_question flag in a single LLM call per batch.

**Rationale**: BERTopic requires significant setup and tuning for Korean text. LLM-based extraction with structured output provides better accuracy on small-to-medium comment sets (< 1000 comments) typical for lecture videos. Batching comments in groups of 20 keeps token usage manageable.

**Alternatives Considered**:
- BERTopic — deferred: good for large-scale topic modeling but requires topic count tuning and Korean tokenizer setup.
- Manual keyword matching — rejected: too brittle for varied comment phrasing.

## R6: ARIMA and Prophet Forecasting

**Decision**: Add `statsmodels.tsa.arima.model.ARIMA` and `prophet.Prophet` as forecasting backends alongside existing linear regression. Auto-select based on data characteristics.

**Rationale**: Linear regression is too simplistic for seasonal patterns. ARIMA handles trend + autocorrelation. Prophet handles seasonality (weekly, yearly) and holiday effects — ideal for academic calendar events.

**Model Selection Logic**:
- < 90 days data: linear regression (insufficient for ARIMA/Prophet)
- 90-365 days: ARIMA (handles trend, no strong seasonality yet)
- > 365 days: Prophet (leverages yearly seasonality + academic calendar)

**Academic Calendar Integration**: User provides calendar dates via JSON config. Prophet treats these as "holidays" for its model. ARIMA uses calendar dates for post-hoc anomaly annotation only.

**Alternatives Considered**:
- Neural Prophet — rejected: heavier dependency, marginal improvement for this scale.
- Simple exponential smoothing — rejected: doesn't handle seasonality.

## R7: Incremental Collection Strategy

**Decision**: Track `last_collected_at` timestamp per report type per channel. On re-run, query only `startDate=last_collected_at+1` to `endDate=today`.

**Rationale**: YouTube Analytics API returns data with a 2-3 day delay. Incremental collection avoids re-fetching historical data and reduces quota usage by ~80%+ after initial collection. Existing checkpoint system stores per-phase state and can be extended with `last_collected_at` per analytics report type.

**Storage**: Extend `CollectionState` model with `analytics_last_dates: dict[str, str]` mapping report type to last collected date.

**Alternatives Considered**:
- Always fetch full history and deduplicate — rejected: wastes quota.
- Hash-based change detection — rejected: API doesn't support ETags for analytics reports.

## R8: Extended Video Metadata Fields

**Decision**: Expand `videos().list()` `part` parameter from `contentDetails,statistics` to `snippet,contentDetails,statistics,status,topicDetails`.

**Rationale**: The YouTube Data API allows requesting additional "parts" at 2 quota units each. Adding `snippet` (description, tags, category, thumbnails, language), `status` (privacy, license), and `topicDetails` (topic categories) provides the metadata needed for video comparison and LLM analysis.

**New Fields on Video model**: `description`, `tags: list[str]`, `category_id`, `thumbnail_url`, `default_language`, `privacy_status`, `topic_categories: list[str]`, `has_captions: bool`.

**Alternatives Considered**:
- Separate API calls per field group — rejected: single call with multiple parts is more efficient.

## R9: Comment Replies Collection

**Decision**: Use `comments().list()` with `parentId` parameter to fetch replies for each top-level comment that has `totalReplyCount > 0`.

**Rationale**: The current `commentThreads().list()` only returns top-level comments. To collect replies, iterate threads with `totalReplyCount > 0` and call `comments().list(parentId=thread_id)`. Store replies alongside parent with `parent_comment_id` field.

**New Fields on Comment model**: `parent_comment_id: str | None`, `reply_count: int`.

**Alternatives Considered**:
- `commentThreads().list(part="snippet,replies")` — retrieves up to 5 replies inline but misses longer threads. Insufficient for completeness.
