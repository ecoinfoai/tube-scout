# Implementation Plan: 보고서 필터링 및 PDF 종합 출력

**Branch**: `004-report-filter-pdf-bundle` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-report-filter-pdf-bundle/spec.md`

## Summary

기존 `report video` 명령에 키워드/기간/ID 필터 옵션을 추가하고, 신규 `report bundle` 명령으로 필터링된 영상들의 분석 결과를 표지·목차·페이지번호가 포함된 단일 PDF 종합 보고서로 출력한다. 데이터→PDF 직접 생성과 기존 HTML→PDF 수거 두 경로를 모두 지원한다.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: typer, rich, jinja2, weasyprint, pydantic v2, plotly (static image export)
**Storage**: JSON (videos_meta.json), Parquet (retention), HTML (existing reports)
**Testing**: pytest
**Target Platform**: Linux (NixOS)
**Project Type**: CLI tool
**Performance Goals**: 24개 영상 PDF 3분 이내, HTML→PDF 수거 1분 이내
**Constraints**: weasyprint 시스템 라이브러리(pango, gobject) 필요 — flake.nix에 추가 필수
**Scale/Scope**: 최대 214개 영상, PDF 단일 문서

## Constitution Check

*No constitution.md found — gate check skipped.*

## Project Structure

### Documentation (this feature)

```text
specs/004-report-filter-pdf-bundle/
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
├── cli/
│   ├── report.py            # 수정: report video 필터 옵션 추가
│   └── main.py              # 수정: report bundle 명령 등록
├── models/
│   └── video_filter.py      # 신규: VideoFilter 모델
├── reporting/
│   ├── bundle_report.py     # 신규: BundleReportGenerator (PDF 종합)
│   ├── video_report.py      # 기존 유지 (수정 없음)
│   └── templates/
│       └── bundle_report.html  # 신규: 표지+목차+영상반복 Jinja2 템플릿
├── services/
│   └── video_filter_service.py  # 신규: 필터링 로직 (키워드/기간/ID)

tests/
├── unit/
│   ├── test_video_filter.py       # 신규: 필터링 로직 테스트
│   └── test_bundle_report.py      # 신규: PDF 생성 테스트
└── integration/
    └── test_bundle_flow.py        # 신규: 필터→PDF 통합 테스트
```

**Structure Decision**: 기존 프로젝트 구조(src/tube_scout/, tests/)를 그대로 따름. 신규 파일은 models/, reporting/, services/ 각 디렉터리에 추가.
