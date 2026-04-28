# Quickstart: Multi-Channel Administration

**Date**: 2026-04-04

## Prerequisites

- Python 3.11 (via flake.nix devShell)
- uv (Python package manager)
- Existing Tube Scout v2 working installation

## New Dependencies

```toml
# pyproject.toml [project.dependencies]
pyyaml = ">=6.0"              # YAML search config parsing
openpyxl = ">=3.1.0"          # Excel report generation
python-Levenshtein = ">=0.25.0"  # Edit distance for name similarity (V-004)
weasyprint = ">=62.0"         # PDF generation (optional)
```

## Development Order

### Phase P1 — Foundation

1. **Output manager**: `output/manager.py` — timestamped directory creation, latest symlink
2. **Multi-channel auth**: Extend `auth.py` — per-alias token storage, registry, auto-detect channel ID
3. **Title parser**: `title_parser.py` — 5 priority patterns, fallback, ParsedTitle model
4. **Title parser tests**: Test against real titles from 간호학과 channel (214 videos)

### Phase P2 — Search & Analysis

5. **Search service**: `search_service.py` — YAML parsing, filter/query/exclude logic
6. **Validator**: `validator.py` — 9 rules (V-001~V-009), supplementary classification
7. **Search CLI**: `search_cli.py` — --config and CLI flag modes
8. **Validate CLI**: `validate_cli.py`

### Phase P2 — Reports

9. **Department report**: `department_report.py` — overview, professor detail, compliance
10. **Excel export**: `excel_export.py` — multi-sheet with conditional formatting
11. **HTML template**: `department.html` — plotly heatmaps, tables
12. **Report CLI**: Extend `report.py` — `report department` subcommand

### Phase P3 — Integration

13. **Channel flag**: Add `--channel` to existing collect/analyze commands
14. **End-to-end test**: Full workflow from auth → collect → parse → validate → report

## Running Tests

```bash
# All tests
cd src && pytest

# Feature-specific tests
pytest tests/unit/test_title_parser.py
pytest tests/unit/test_validator.py
pytest tests/unit/test_search_service.py
pytest tests/unit/test_department_report.py

# With coverage
pytest --cov=tube_scout --cov-report=term-missing

# Lint
ruff check .
```

## Key Design Patterns

1. **OutputManager**: Singleton-like, creates timestamped dirs, manages `latest` symlink
2. **TitleParser**: Chain-of-responsibility pattern — try patterns in priority order
3. **Validator**: Independent rule functions, collected findings
4. **Channel registry**: JSON file mapping alias → metadata, separate token files
5. **Search**: YAML → Pydantic model → filter function over parsed titles
