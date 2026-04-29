# Tutorial: Tube Scout Full-Feature Guide

## Table of Contents

1. [Project layout](#1-project-layout)
2. [Configuration](#2-configuration)
3. [Data collection (`collect`)](#3-data-collection-collect)
4. [Data analysis (`analyze`)](#4-data-analysis-analyze)
5. [Reports (`report`)](#5-reports-report)
6. [Status (`status`, `list`)](#6-status-status-list)
7. [Data directory layout](#7-data-directory-layout)
8. [Environment-variable reference](#8-environment-variable-reference)
9. [Full CLI command reference](#9-full-cli-command-reference)

---

## 1. Project layout

### Install

```bash
uv sync                          # install dependencies
uv run tube-scout --version      # check the version
```

### Command tree

```
tube-scout
├── init                    # initialize a project
├── status                  # collection / analysis status
├── list                    # list videos
├── collect
│   ├── videos              # video metadata
│   ├── comments            # comments
│   ├── transcripts         # transcripts
│   ├── retention           # audience retention
│   └── all                 # everything
├── analyze
│   ├── retention           # rewatch hotspots / skip zones
│   ├── sentiment           # comment sentiment / topics / questions
│   ├── transcript          # chapter splitting + difficulty
│   ├── eqs                 # educational quality score (RACED)
│   ├── forecast            # time-series forecast + anomalies
│   └── all                 # all analyses
└── report
    ├── video               # per-video report
    └── channel             # channel-wide report
```

---

## 2. Configuration

### `init` — initialize a project

```bash
tube-scout init \
  --channel-id "UCxxxxxxxxxx" \
  --professor "Jane Smith" \
  --data-dir "./data"          # default: ./data
```

`data/config.json` is created:

```json
{
  "channels": [
    {
      "channel_id": "UCxxxxxxxxxx",
      "professor_name": "Jane Smith"
    }
  ],
  "settings": {
    "data_dir": "./data",
    "sentiment_backend": "llm",
    "default_report_format": "html"
  }
}
```

### Channel-ID validation

- Must start with `UC`
- Only alphanumeric, hyphen (`-`), and underscore (`_`) are allowed
- Whitespace and special characters are rejected

### Professor-name filtering

A video is selected when its title contains the professor name as a substring:

| Title | Professor "Jane Smith" | Result |
|-------|------------------------|--------|
| "Anatomy — Prof. Jane Smith" | match | selected |
| "Jane Smith Physiology Lecture 1" | match | selected |
| "2024 Jane Smith Special Lecture" | match | selected |
| "Anatomy Lecture, Week 3" | no match | excluded |

---

## 3. Data collection (`collect`)

### `collect videos` — video metadata

```bash
tube-scout collect videos [--force-refresh] [--data-dir ./data]
```

**What is collected**: video_id, title, upload date, duration, view count,
likes, and comment count.

**How it works**:
1. List every video in the channel's uploads playlist (`playlistItems.list`,
   1 unit/call).
2. Filter by professor name.
3. Batch-fetch the selected videos' details (`videos.list`, 50 at a time).
4. Persist to `data/raw/channels/{channel_id}/videos_meta.json` + `.parquet`.

**API cost**: roughly 40 units for a 1,000-video channel (out of the 10,000
daily quota).

**Options**:

| Option | Default | Description |
|--------|---------|-------------|
| `--force-refresh` | false | Ignore checkpoint and re-collect from scratch |
| `--data-dir` | `./data` | Where data is stored |

### `collect comments` — comments

```bash
tube-scout collect comments [--video-id VIDEO_ID] [--data-dir ./data]
```

Collects per-video comments (`commentThreads.list`). With `--video-id`, only
that video; without it, every video.

**Stored at**: `data/raw/comments/{video_id}.json`

### `collect transcripts` — transcripts

```bash
tube-scout collect transcripts [--video-id VIDEO_ID] [--data-dir ./data]
```

Collection priority:
1. Manual subtitles
2. Auto-generated subtitles
3. (If Whisper is installed) speech-to-text fallback
4. No subtitles → skipped + logged

**Stored at**: `data/raw/transcripts/{video_id}.json`

> Transcript collection does not consume the YouTube API quota (a separate
> library is used).

### `collect retention` — audience retention

```bash
tube-scout collect retention [--video-id VIDEO_ID] [--data-dir ./data]
```

Collects per-segment audience retention via the YouTube Analytics API.

**Required**: channel-owner / manager OAuth2 (the `YOUTUBE_OAUTH_TOKEN`
environment variable).

If permission is missing, the video is skipped and the rest continue
(graceful degradation).

**Stored at**: `data/raw/retention/{video_id}.parquet`

### `collect all` — everything

```bash
tube-scout collect all [--force-refresh] [--data-dir ./data]
```

Runs videos → comments → transcripts → retention. A failure in one step does
not stop the others.

---

## 4. Data analysis (`analyze`)

### `analyze retention` — viewing patterns

```bash
tube-scout analyze retention [--video-id VIDEO_ID] [--data-dir ./data]
```

Two zones are auto-identified from the retention curve:

- **Rewatch hotspot**: relative retention ≥ 1.3 → hard segment students replay
- **Skip zone**: relative retention ≤ 0.7 → segment students skip

Results print as a terminal table and persist to
`data/processed/retention/{video_id}.json`.

### `analyze sentiment` — comment analysis

```bash
tube-scout analyze sentiment \
  [--video-id VIDEO_ID] \
  [--sentiment-backend llm|local|skip] \
  [--data-dir ./data]
```

Each comment is auto-classified along three axes:

| Field | Description | Example |
|-------|-------------|---------|
| **Sentiment** | positive / negative / neutral | "Thanks for the explanation" → positive |
| **Topic** | discussed topics | "Confused about muscle contraction" → ["muscle contraction"] |
| **Question** | is-question flag | "Will this be on the exam?" → is_question: true |

**Backends**:

| Backend | Description | Required env |
|---------|-------------|--------------|
| `llm` (default) | LLM API (highest accuracy) | `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` |
| `local` | Local model | none (model download required) |
| `skip` | Skip sentiment analysis | none |

A **content-hash cache** prevents re-analyzing the same comment.

### `analyze transcript` — transcript analysis

```bash
tube-scout analyze transcript [--video-id VIDEO_ID] [--data-dir ./data]
```

Three artifacts are produced from the transcript:

| Artifact | Description |
|----------|-------------|
| **Chapter splits** | Auto-segmenting the video into topic units |
| **Per-chapter summaries** | Key idea per chapter |
| **Difficulty score** | 0.0–1.0, based on vocabulary / concept density |

When retention data is also available, predicted difficulty is cross-checked
against actual rewatch hotspots.

### `analyze eqs` — educational quality score

```bash
tube-scout analyze eqs [--video-id VIDEO_ID] [--data-dir ./data]
```

The RACED 5-axis evaluation:

| Korean | English | Description | Range |
|--------|---------|-------------|-------|
| 관련성 | Relevance | Alignment with the learning goal | 0.0–1.0 |
| 정확성 | Accuracy | Factual correctness | 0.0–1.0 |
| 명료성 | Clarity | Ease of understanding | 0.0–1.0 |
| 참여도 | Engagement | Holds student attention | 0.0–1.0 |
| 깊이 | Depth | Topic coverage | 0.0–1.0 |

The **Overall** score is a weighted average of the five axes.

### `analyze forecast` — time-series forecast

```bash
tube-scout analyze forecast [--data-dir ./data]
```

Based on historical view counts:

- **30-day view-count forecast** (linear regression with a confidence band)
- **Anomaly detection** (z-score; e.g., exam-week spikes, vacation dips)

Requires at least 6 months (180 days) of data.

### `analyze all` — every analysis

```bash
tube-scout analyze all [--sentiment-backend llm] [--data-dir ./data]
```

Runs sentiment → transcript → retention → eqs → forecast.

---

## 5. Reports (`report`)

### `report video` — per-video report

```bash
tube-scout report video \
  [--video-id VIDEO_ID] \
  [--format html|notebook] \
  [--output-dir ./custom-path] \
  [--data-dir ./data]
```

**HTML report contents**:
- Basic video metadata (title, upload date, views, duration)
- Retention chart (hotspots and skips highlighted)
- Difficulty table per transcript chapter
- Comment sentiment summary
- Data-driven **improvement suggestions** (length, difficulty distribution,
  rewatch hotspots)

**Jupyter Notebook report** (`--format notebook`):
- Generates an `.ipynb` with interactive plotly charts
- Open in Jupyter to explore the data directly

### `report channel` — channel-wide report

```bash
tube-scout report channel \
  [--format html|notebook] \
  [--output-dir ./custom-path] \
  [--data-dir ./data]
```

**Contents**:
- Channel overview (video count, average views, average length)
- Side-by-side video comparison
- Topic-level performance
- Channel-operations insights

### Suggestion engine

Improvement suggestions in the report are auto-generated from the data:

| Signal | Suggestion |
|--------|------------|
| Video length > 10 min | "Splitting the video into segments under 10 minutes improves completion rate." |
| Many rewatch hotspots | "Provide supplementary material for those segments." |
| Many skip zones | "Restructure or shorten those segments." |
| Difficulty score > 0.8 | "Add visuals or worked examples in those segments." |

---

## 6. Status (`status`, `list`)

### `status` — collection / analysis status

```bash
tube-scout status [--data-dir ./data]
```

Shows channel info, the number of collected videos, and the completion state
of each collection step in a table.

### `list` — video list

```bash
tube-scout list \
  [--sort published_at|view_count|like_count|duration_seconds] \
  [--limit 20] \
  [--data-dir ./data]
```

Tabulates the collected videos.

| Option | Default | Description |
|--------|---------|-------------|
| `--sort` | `published_at` | Field to sort by |
| `--limit` | 20 | Number of videos to show |

---

## 7. Data directory layout

```
data/
├── config.json                          # project settings
├── raw/
│   ├── channels/{channel_id}/
│   │   ├── channel_meta.json            # channel info
│   │   ├── videos_meta.json             # video list (JSON)
│   │   └── videos_meta.parquet          # video list (Parquet)
│   ├── comments/{video_id}.json         # raw comments
│   ├── transcripts/{video_id}.json      # raw transcripts
│   └── retention/{video_id}.parquet     # audience retention
├── processed/
│   ├── retention/{video_id}.json        # hotspot / skip results
│   ├── sentiment/{video_id}.parquet     # sentiment results
│   ├── segments/{video_id}.json         # chapter splits
│   ├── eqs/{video_id}.json              # educational quality scores
│   └── forecast/{channel_id}_*.json     # time-series forecasts
├── reports/
│   ├── video/{video_id}.html            # per-video report
│   └── channel/{channel_id}.html        # channel-wide report
└── checkpoints/
    └── {channel_id}_{phase}.json        # collection progress
```

---

## 8. Environment-variable reference

| Variable | Required | Purpose |
|----------|----------|---------|
| `YOUTUBE_API_KEY` | required | YouTube Data API v3 |
| `YOUTUBE_OAUTH_TOKEN` | optional | YouTube Analytics API (retention) |
| `ANTHROPIC_API_KEY` | optional | Claude (sentiment, transcript, EQS) |
| `OPENAI_API_KEY` | optional | OpenAI (alternative to Anthropic) |

> API keys are never hard-coded. All authentication goes through
> environment variables only.

---

## 9. Full CLI command reference

| Command | Description | Key options |
|---------|-------------|-------------|
| `tube-scout init` | Initialize a project | `--channel-id`, `--professor`, `--data-dir` |
| `tube-scout status` | Show status | `--data-dir` |
| `tube-scout list` | Video list | `--sort`, `--limit`, `--data-dir` |
| `tube-scout collect videos` | Collect video metrics | `--force-refresh`, `--data-dir` |
| `tube-scout collect comments` | Collect comments | `--video-id`, `--data-dir` |
| `tube-scout collect transcripts` | Collect transcripts | `--video-id`, `--data-dir` |
| `tube-scout collect retention` | Collect retention | `--video-id`, `--data-dir` |
| `tube-scout collect all` | Collect everything | `--force-refresh`, `--data-dir` |
| `tube-scout analyze retention` | Retention analysis | `--video-id`, `--data-dir` |
| `tube-scout analyze sentiment` | Sentiment analysis | `--video-id`, `--sentiment-backend`, `--data-dir` |
| `tube-scout analyze transcript` | Transcript analysis | `--video-id`, `--data-dir` |
| `tube-scout analyze eqs` | EQS evaluation | `--video-id`, `--data-dir` |
| `tube-scout analyze forecast` | Time-series forecast | `--data-dir` |
| `tube-scout analyze all` | All analyses | `--sentiment-backend`, `--data-dir` |
| `tube-scout report video` | Per-video report | `--video-id`, `--format`, `--output-dir`, `--data-dir` |
| `tube-scout report channel` | Channel report | `--format`, `--output-dir`, `--data-dir` |
