# Implementation Plan: 보고서 필터링 및 PDF 종합 출력

**Branch**: `006-report-filter-pdf-bundle` | **Date**: 2026-04-07 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-report-filter-pdf-bundle/spec.md`

## Summary

학과 관리자가 조건별로 영상을 필터링하고, 표지·목차·페이지번호가 포함된 단일 PDF 종합 보고서를 생성할 수 있도록 기존 `report bundle` 명령을 확장한다. 기존 VideoFilter/VideoFilterService, BundleReportGenerator 인프라를 80% 재사용하며, 5개 파일에 incremental 변경을 적용한다.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: typer, rich, jinja2, weasyprint (optional), pydantic v2, plotly
**Storage**: JSON (videos_meta.json, parsed_titles.json, channel_meta.json) — 기존 수집 데이터 사용
**Testing**: pytest (uv run pytest)
**Target Platform**: Linux (NixOS) CLI
**Project Type**: CLI tool
**Performance Goals**: 100건 영상 PDF 번들 60초 이내 생성
**Constraints**: weasyprint 미설치 시 HTML 폴백 필수, 기존 테스트 전체 PASS 유지
**Scale/Scope**: 영상 1~500건 범위, 단일 채널 대상

## Constitution Check

*Constitution이 기본 템플릿 상태이므로 CLAUDE.md의 프로젝트 규칙을 적용:*

| Gate | Status | Notes |
|------|--------|-------|
| TDD mandatory | PASS | 테스트 먼저 작성 후 구현 |
| Fail-Fast | PASS | 필터 결과 0건 시 즉시 안내 메시지 |
| No hardcoded secrets | PASS | 해당 없음 |
| Type annotations | PASS | 모든 새 함수에 타입 힌트 |
| Conventional commits | PASS | 커밋 규칙 준수 |

## Project Structure

### Documentation (this feature)

```text
specs/006-report-filter-pdf-bundle/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: codebase analysis
├── data-model.md        # Phase 1: entity definitions
├── quickstart.md        # Phase 1: developer guide
├── contracts/
│   └── cli-interface.md # CLI command contract
└── tasks.md             # Phase 2 output (by /speckit.tasks)
```

### Source Code (modified files)

```text
src/tube_scout/
├── services/
│   └── video_filter_service.py    # +date_asc sort option
├── reporting/
│   ├── bundle_report.py           # +channel summary, cover enhancements
│   └── templates/
│       ├── bundle_report.html     # +cover, summary page, TOC page nums
│       └── bundle_from_html.html  # +same template changes
└── cli/
    └── report.py                  # +--format, --no-confirm, preview flow

tests/
├── unit/
│   ├── test_video_filter_service.py  # +date_asc tests
│   ├── test_bundle_report.py         # +cover, summary, PDF tests
│   └── test_report_cli_filter.py     # +preview, confirm, format tests
└── integration/
    └── test_bundle_flow.py           # +E2E filter→PDF pipeline
```

**Structure Decision**: 기존 프로젝트 구조 유지. 새 파일 생성 없이 기존 5개 파일 확장.

## Complexity Tracking

해당 없음 — constitution 위반 없음.
