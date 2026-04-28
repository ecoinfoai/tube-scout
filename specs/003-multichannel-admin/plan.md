# Implementation Plan: Multi-Channel Administration

**Branch**: `003-multichannel-admin` | **Date**: 2026-04-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-multichannel-admin/spec.md`

## Summary

Extend Tube Scout for academic affairs administration: (1) multi-channel OAuth token management with per-department aliases, (2) video title parsing into structured fields (professor/course/year/week/session), (3) YAML-based structured search, (4) department reports with compliance analysis in HTML/Excel/PDF, (5) title validation with 9 anomaly detection rules, and (6) timestamped output directory management.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: typer, rich, google-api-python-client, google-auth-oauthlib, pydantic v2, pyyaml (new), openpyxl (new), plotly, jinja2, Levenshtein (new — for name similarity V-004)
**Storage**: JSON (structured data) + timestamped output directories under `./output/`
**Testing**: pytest + pytest-cov, ruff linting
**Target Platform**: Linux (NixOS), CLI tool
**Project Type**: CLI application
**Performance Goals**: Title parsing < 1s for 5,000 titles, report generation < 2 min for 3,000 videos
**Constraints**: YouTube API quota (10,000 units/day), single admin workstation
**Scale/Scope**: 5-30 department channels, up to 5,000 videos per channel, up to 50 professors per department

## Constitution Check

*No constitution.md found. Skipping gate evaluation.*

## Project Structure

### Documentation (this feature)

```text
specs/003-multichannel-admin/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli-commands.md  # New CLI commands contract
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/tube_scout/
├── models/
│   ├── config.py            # Extended: ChannelRegistration
│   ├── parsed_title.py      # NEW: ParsedTitle, TitlePattern
│   ├── validation.py        # NEW: ValidationFinding, ValidationRule
│   └── search.py            # NEW: SearchFilter, SearchQuery
├── services/
│   ├── auth.py              # Extended: multi-channel token management
│   ├── title_parser.py      # NEW: universal parser with priority patterns
│   ├── search_service.py    # NEW: YAML + CLI search
│   ├── validator.py         # NEW: V-001~V-009 rules
│   └── youtube_data.py      # Extended: --channel flag support
├── cli/
│   ├── main.py              # Extended: auth, search, validate subcommands
│   ├── auth_cli.py          # NEW: auth --channel, --list, --revoke
│   ├── search_cli.py        # NEW: search --config, --professor, --year
│   ├── validate_cli.py      # NEW: validate --channel, --year, --semester
│   └── collect.py           # Extended: --channel flag
├── reporting/
│   ├── department_report.py # NEW: DepartmentReportGenerator
│   ├── excel_export.py      # NEW: Excel multi-sheet export
│   └── templates/
│       └── department.html  # NEW: department report template
├── output/
│   └── manager.py           # NEW: timestamped directory management
└── cli/
    └── report.py            # Extended: report department subcommand

tests/
├── unit/
│   ├── test_title_parser.py     # NEW
│   ├── test_search_service.py   # NEW
│   ├── test_validator.py        # NEW
│   ├── test_department_report.py # NEW
│   ├── test_excel_export.py     # NEW
│   ├── test_output_manager.py   # NEW
│   └── test_auth_multi.py       # NEW
├── integration/
│   └── test_admin_flow.py       # NEW: end-to-end admin workflow
├── adversary/
│   └── test_title_edge_cases.py # NEW
└── fixtures/
    ├── sample_titles.json       # Real title examples for parser tests
    └── search_clips_sample.yaml # Sample YAML search config
```

**Structure Decision**: Extends existing single-project CLI structure. New services (title_parser, search, validator) follow established patterns. New CLI files for auth/search/validate keep command groups clean. New output/manager.py centralizes timestamped directory logic.

## Complexity Tracking

> No constitution violations to justify.
