# Implementation Plan: Lecture Video Content Reuse Detection

**Branch**: `007-content-reuse-detection` | **Date**: 2026-04-07 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/007-content-reuse-detection/spec.md`

## Summary

강의 영상의 자막을 수집하여 연도별 재사용 여부를 5가지 독립 지표로 복합 판정하고, 교무과 담당자가 우선순위 기반으로 점검할 수 있는 관리자 리뷰 워크플로우를 제공한다. 비공개 영상(88.6%)은 OAuth Captions API(force-ssl scope)로 자막에 접근하며, 분석은 100% 로컬에서 수행된다.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pydantic v2, sentence-transformers, polars, plotly, jinja2, openpyxl
**Storage**: SQLite (processing status, comparison results, review status) + Parquet (embeddings) + JSON (captions, metadata)
**Testing**: pytest (TDD mandatory per CLAUDE.md)
**Target Platform**: Linux (NixOS), CLI tool
**Project Type**: CLI
**Performance Goals**: 2,500 videos fingerprint+compare+quality in under 30 minutes (local processing, excluding API wait)
**Constraints**: Daily YouTube API quota 10,000 units; single-user per department; offline analysis after caption collection
**Scale/Scope**: ~20 departments, up to 2,550 videos per department, periodic analysis (monthly/semester)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution is in template state (not configured). No gate violations to check. Proceeding.

## Project Structure

### Documentation (this feature)

```text
specs/007-content-reuse-detection/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI contracts)
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/tube_scout/
├── models/
│   └── content.py                    # Pydantic models: ComparisonPair, ComparisonResult, QualityCheck, SuspicionScore
├── services/
│   ├── auth.py                       # MODIFIED: force-ssl scope addition
│   ├── transcript.py                 # MODIFIED: Captions API fallback for private videos
│   ├── captions_api.py               # NEW: OAuth Captions API client (list, download, SRT parse)
│   ├── fingerprint.py                # NEW: SHA-256 hash + sentence-transformer embedding
│   ├── content_comparator.py         # NEW: 5-indicator comparison + suspicion score
│   ├── quality_checker.py            # NEW: Q-001~Q-005 quality rules
│   └── rate_limiter.py               # EXISTING: reuse for Captions API rate limiting
├── storage/
│   ├── content_db.py                 # NEW: SQLite wrapper (processing_status, fingerprints, comparisons, reviews)
│   ├── json_store.py                 # EXISTING: caption JSON storage
│   └── parquet_store.py              # EXISTING: embedding Parquet storage
├── cli/
│   ├── collect.py                    # MODIFIED: enhanced transcript collection with Captions API fallback
│   └── content.py                    # NEW: content fingerprint/compare/quality/review/scan commands
├── reporting/
│   └── content_report.py             # NEW: HTML/Excel/JSON content quality reports
└── visualization/
    └── charts.py                     # EXISTING: reuse for heatmaps

tests/
├── unit/
│   ├── test_captions_api.py          # NEW
│   ├── test_fingerprint.py           # NEW
│   ├── test_content_comparator.py    # NEW
│   ├── test_quality_checker.py       # NEW
│   ├── test_content_db.py            # NEW
│   ├── test_content_models.py        # NEW
│   └── test_content_report.py        # NEW
├── integration/
│   ├── test_content_pipeline.py      # NEW: fingerprint→compare→quality flow
│   └── test_caption_collection.py    # NEW: transcript-api + Captions API fallback
└── adversary/
    └── test_content_adversary.py     # NEW: edge cases, malformed data
```

**Structure Decision**: Follows existing tube-scout single-project structure. New files are added to existing directories (services/, models/, cli/, reporting/). SQLite DB is a new storage mechanism added alongside existing JSON/Parquet patterns.

## Complexity Tracking

No constitution violations to justify.
