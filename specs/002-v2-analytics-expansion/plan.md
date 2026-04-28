# Implementation Plan: Tube Scout v2 Analytics Expansion

**Branch**: `002-v2-analytics-expansion` | **Date**: 2026-04-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-v2-analytics-expansion/spec.md`

## Summary

Extend Tube Scout from a basic YouTube lecture analytics CLI (v1: retention + metadata collection) to a comprehensive analytics platform. This includes: (1) collecting all YouTube Analytics API report types with incremental sync, (2) enriching video/channel metadata, (3) implementing LLM-based and local NLP comment analysis, (4) connecting LLM transcript analysis (segmentation, difficulty, EQS), (5) upgrading forecasting to ARIMA/Prophet with academic calendar support, (6) generating comprehensive channel reports with improvement suggestions, and (7) adding YouTube Reporting API bulk download.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pandas, polars, plotly, jinja2, pydantic v2, nbformat, anthropic (new), openai (new), statsmodels (new — ARIMA), prophet (new), transformers + torch (new — KoBERT/KoELECTRA)
**Storage**: JSON (atomic write) + Parquet (polars) — existing pattern preserved
**Testing**: pytest + pytest-cov, ruff linting
**Target Platform**: Linux (NixOS), CLI tool
**Project Type**: CLI application
**Performance Goals**: 100 comments sentiment analysis < 60s (LLM), channel report < 5 min for 500 videos
**Constraints**: YouTube API quota (10,000 units/day default), LLM API rate limits, offline local NLP inference support
**Scale/Scope**: Single channel owner, up to 500 videos, 2 years daily time-series

## Constitution Check

*No constitution.md found. Skipping gate evaluation.*

## Project Structure

### Documentation (this feature)

```text
specs/002-v2-analytics-expansion/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli-commands.md  # Extended CLI contract
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/tube_scout/
├── models/
│   ├── config.py          # Extended: AcademicCalendar, Settings updates
│   ├── video.py           # Extended: new metadata fields
│   ├── channel.py         # Extended: subscriber_count, total_views, description
│   ├── comment.py         # Extended: replies, reply_count
│   └── analytics.py       # NEW: AnalyticsReport, TrafficSource, Demographics, etc.
├── services/
│   ├── auth.py            # Existing (unchanged)
│   ├── youtube_data.py    # Extended: full metadata, replies, incremental sync
│   ├── youtube_analytics.py  # Extended: 8 report types, date range, incremental
│   ├── youtube_reporting.py  # NEW: Reporting API bulk download
│   ├── transcript.py      # Existing (unchanged)
│   ├── sentiment.py       # Extended: LLM backend impl, local backend impl
│   ├── topic_extractor.py # NEW: topic clustering, question extraction
│   ├── segmenter.py       # Extended: LLM call implementation
│   ├── eqs.py             # Extended: LLM call implementation
│   ├── forecaster.py      # Extended: ARIMA, Prophet, academic calendar
│   └── llm_adapter.py     # NEW: provider-agnostic LLM adapter (Claude/GPT-4o)
├── cli/
│   ├── main.py            # Extended: new subcommands
│   ├── collect.py         # Extended: analytics, --start-date, --incremental
│   ├── analyze.py         # Extended: --sentiment-backend, topic
│   ├── report.py          # Extended: comment-insight, channel improvements
│   └── status.py          # Existing (minor updates)
├── storage/
│   ├── json_store.py      # Existing (unchanged)
│   ├── parquet_store.py   # Existing (unchanged)
│   └── checkpoint.py      # Extended: new phases for analytics collection
├── reporting/
│   ├── channel_report.py  # Extended: comparisons, trends, suggestions
│   ├── video_report.py    # Existing (minor updates)
│   ├── comment_report.py  # NEW: comment insight report
│   ├── notebook_export.py # Existing (unchanged)
│   └── templates/         # Extended: new report templates
└── visualization/
    └── charts.py          # Extended: new chart types for analytics

tests/
├── unit/
│   ├── test_analytics_models.py     # NEW
│   ├── test_youtube_analytics_ext.py # NEW: extended analytics tests
│   ├── test_youtube_reporting.py    # NEW
│   ├── test_llm_adapter.py         # NEW
│   ├── test_sentiment_llm.py       # NEW: LLM backend tests
│   ├── test_sentiment_local.py     # NEW: local NLP backend tests
│   ├── test_topic_extractor.py     # NEW
│   ├── test_segmenter_llm.py       # NEW: LLM integration tests
│   ├── test_eqs_llm.py             # NEW
│   ├── test_forecaster_ext.py      # NEW: ARIMA/Prophet tests
│   ├── test_comment_report.py      # NEW
│   └── ... (existing tests unchanged)
├── integration/
│   ├── test_collect_flow.py         # Extended
│   └── test_analytics_collect.py    # NEW
└── adversary/
    ├── test_failure_cases.py        # Extended
    └── test_llm_failures.py         # NEW: malformed LLM responses
```

**Structure Decision**: Extends the existing single-project CLI structure. New services follow the established pattern (service class + module-level helper functions). New `llm_adapter.py` provides a single LLM integration point; `topic_extractor.py` isolates topic/question logic from sentiment. No new top-level directories needed.

## Complexity Tracking

> No constitution violations to justify.
