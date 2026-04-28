# Implementation Plan: Tube Scout — 강의 영상 분석 플랫폼

**Branch**: `001-lecture-video-analytics` | **Date**: 2026-04-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-lecture-video-analytics/spec.md`

## Summary

YouTube 채널에서 특정 교수의 강의 영상을 식별하고, 시청 메트릭/시청 패턴/댓글/자막을 수집·분석하여 강의 영상 제작 전략을 데이터 기반으로 수립하는 Python CLI 도구. Typer 기반 서브커맨드 구조로, 데이터를 로컬 파일(JSON+Parquet)에 저장하고, LLM API를 활용하여 자막 분석 및 댓글 감성분석을 수행한다.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pandas, polars, plotly, jinja2, statsmodels/prophet
**Storage**: 로컬 파일 (JSON 메타데이터 + Parquet 시계열 데이터), data/ 디렉토리
**Testing**: pytest + pytest-cov
**Target Platform**: Linux (NixOS), CLI
**Project Type**: CLI tool
**Performance Goals**: 100+ 영상 채널 수집 5분 이내 (SC-001), API 할당량 범위 내 효율적 수집
**Constraints**: YouTube API 일일 10,000 units 쿼터, Analytics API 채널 소유자 전용, 환경변수 기반 시크릿
**Scale/Scope**: 단일 채널/단일 교수 (v1), 100~500개 영상 규모

## Constitution Check

*No constitution.md found — skipping gate check.*

## Project Structure

### Documentation (this feature)

```text
specs/001-lecture-video-analytics/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: technology research
├── data-model.md        # Phase 1: entity definitions
├── quickstart.md        # Phase 1: setup guide
├── contracts/
│   └── cli-commands.md  # Phase 1: CLI command contract
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/
├── tube_scout/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py          # Typer app entry point
│   │   ├── collect.py       # collect 서브커맨드
│   │   ├── analyze.py       # analyze 서브커맨드
│   │   ├── report.py        # report 서브커맨드
│   │   └── status.py        # status/list 서브커맨드
│   ├── services/
│   │   ├── __init__.py
│   │   ├── youtube_data.py  # YouTube Data API 클라이언트
│   │   ├── youtube_analytics.py  # YouTube Analytics API 클라이언트
│   │   ├── transcript.py    # 자막 수집 서비스
│   │   ├── sentiment.py     # 댓글 감성분석 (LLM/local)
│   │   ├── segmenter.py     # 자막 챕터 분할 (LLM)
│   │   ├── eqs.py           # 교육 품질 스코어링
│   │   └── forecaster.py    # 시계열 예측
│   ├── models/
│   │   ├── __init__.py
│   │   ├── channel.py       # Channel 데이터 모델
│   │   ├── video.py         # Video 데이터 모델
│   │   ├── comment.py       # Comment 데이터 모델
│   │   └── config.py        # 설정 모델
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── json_store.py    # JSON 읽기/쓰기
│   │   ├── parquet_store.py # Parquet 읽기/쓰기
│   │   └── checkpoint.py    # Resume 체크포인트 관리
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── video_report.py  # 영상별 리포트 생성
│   │   ├── channel_report.py # 채널 종합 리포트
│   │   └── templates/       # Jinja2 HTML 템플릿
│   └── visualization/
│       ├── __init__.py
│       └── charts.py        # plotly 차트 생성 (유지율 곡선 등)

tests/
├── unit/
│   ├── test_youtube_data.py
│   ├── test_transcript.py
│   ├── test_sentiment.py
│   ├── test_segmenter.py
│   ├── test_checkpoint.py
│   └── test_models.py
├── integration/
│   ├── test_collect_flow.py
│   └── test_analyze_flow.py
└── conftest.py              # fixtures (mock API responses 등)
```

**Structure Decision**: Single project 구조. CLI → services → storage 레이어로 관심사 분리. services는 외부 API/LLM 호출을 캡슐화하고, storage는 파일 I/O를 담당. models는 pydantic 기반 데이터 모델로 검증 포함.

## Complexity Tracking

> No constitution violations — no entries needed.
