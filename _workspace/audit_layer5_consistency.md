# Layer 5: Consistency & Convention Audit Results

## Summary

| # | Check Item | Violations | Severity |
|---|-----------|-----------|----------|
| 1 | Error message language | 0 | OK |
| 2 | Logging pattern | 2 patterns | WARNING |
| 3 | CLI option naming | 0 | OK |
| 4 | Pydantic model_config | 0 (none used) | INFO |
| 5 | Import style | 0 | OK |
| 6 | Function naming | 0 | OK |
| 7 | Type hints | 1 | WARNING |
| 8 | Exception classes | 0 custom | INFO |
| 9 | Magic numbers | 7 | WARNING |
| 10 | Docstrings | 0 | OK |

---

## Detailed Results

### 1. Error Message Language

**Result: PASS** -- All `raise`, `console.print`, and `typer.echo` messages use English.

Korean text exists in the codebase but is confined to:
- **`services/title_parser.py`**: Regex patterns for parsing Korean video titles (e.g., `주차`, `차시`, `학기`). This is domain data, not error messages.
- **`services/sentiment.py:31-33`**: Korean-to-English label mapping dict (`"긍정": "positive"` etc.). Domain data.
- **`reporting/excel_export.py`**: Korean sheet names and headers (`"개요"`, `"교수별 상세"`, `"준수율"`, `"이상 탐지"`, `"항목"`, etc.). These are user-facing output for Korean university stakeholders -- intentional and appropriate.
- **`services/auth.py:272`**: Korean example in docstring (`"간호학과"`). Acceptable in documentation.

**No violations**: All error/raise messages and console error output are in English.

### 2. Logging Pattern

**Result: 2 PATTERNS -- mixed but intentional**

| Pattern | Modules | Usage |
|---------|---------|-------|
| `rich.console.Console` | cli/collect, cli/report, cli/main, cli/analyze, cli/status, cli/validate_cli, cli/search_cli, cli/auth_cli | User-facing CLI output |
| `import logging` + `logger` | services/youtube_data, services/eqs, services/transcript, services/forecaster, services/segmenter, reporting/bundle_report | Backend service logging |
| `print()` | reporting/notebook_export (inside generated notebook code) | Not actual logging -- code generation |

**Assessment**: The split is actually consistent by layer:
- **CLI layer** -> `rich.console.Console` (user-facing, styled output)
- **Service layer** -> `logging` module (machine-parseable backend logs)

This is a legitimate two-tier pattern. No `print()` is used for actual logging (the notebook_export uses it inside generated Jupyter cell code strings).

**No corrective action needed**, but the pattern should be documented as a convention.

### 3. CLI Option Naming

**Result: PASS** -- All CLI options use kebab-case consistently.

All `typer.Option()` declarations use `"--kebab-case"` naming:
- `--data-dir`, `--project-dir`, `--force-refresh`, `--video-id`, `--include-replies`
- `--start-date`, `--report-type`, `--sentiment-backend`, `--horizon-days`
- `--published-after`, `--published-before`, `--video-ids`, `--dry-run`, `--from-html`
- `--output-dir`, `--week-from`, `--week-to`

Python parameter names use `snake_case` (typer convention). No inconsistencies found.

### 4. Pydantic Model Settings

**Result: INFO** -- No `model_config` is used on any of the 40 Pydantic models.

All models inherit from `BaseModel` with default configuration. No model uses:
- `model_config = ConfigDict(frozen=True, ...)` or any custom config

This is consistent (all models use defaults), but worth noting:
- None of the models are frozen (immutable)
- No `extra = "forbid"` is set (unexpected fields silently ignored)
- No `str_strip_whitespace = True`

**Recommendation**: Consider adding `model_config = ConfigDict(extra="forbid")` to data models to catch typos in input data. This is an improvement suggestion, not a violation.

### 5. Import Style

**Result: PASS** -- 100% absolute imports.

All internal imports use `from tube_scout.x.y import z` (absolute). No relative imports (`from .x import y`) found anywhere. Fully consistent.

### 6. Function Naming

**Result: PASS** -- All public functions follow `snake_case`.

Examined all `def` declarations across 48 modules. All function names are `snake_case`. Regarding the verb-first convention:

- **Service/utility functions**: Properly verb-first (`detect_rewatch_hotspots`, `generate_improvement_suggestions`, `compare_videos`, `parse_report_csv`, `run_all_validations`, `save_validation_results`, `authenticate`, `build_data_client`, `load_registry`, `save_registry`, etc.)
- **CLI command functions**: Follow `{noun}_{noun}_command` pattern (`collect_videos_command`, `report_bundle_command`, etc.) -- this is a CLI convention, not a violation.
- **Pydantic validators**: Follow `{field}_must_be_{condition}` pattern -- Pydantic convention.
- **Private helpers**: Prefixed with `_` (`_load_config`, `_build_patterns`, `_extract_json`, etc.)

No naming violations found.

### 7. Type Hints

**Result: 1 WARNING**

All public functions have parameter and return type annotations, with one exception:

| File | Function | Issue |
|------|----------|-------|
| `cli/search_cli.py:153` | `_load_parsed_titles(...)` | Return type is bare `list` instead of `list[ParsedTitle]` |

This is a private function but the unparameterized `list` is imprecise. All other functions across the codebase have fully parameterized type hints.

### 8. Exception Classes

**Result: INFO** -- No custom exceptions defined.

The project uses only built-in exceptions:
- `ValueError` -- most common (input validation in models and services)
- `PermissionError` -- API auth failures (youtube_analytics.py)
- `FileNotFoundError` -- missing files (output/manager.py)
- `RuntimeError` -- state errors (output/manager.py)
- `ConnectionError` -- LLM unreachable (llm_adapter.py, documented)
- `typer.Exit` -- CLI-level exit

**Assessment**: For a project this size (48 modules), the current approach is adequate. The built-in exceptions are used consistently and with descriptive messages. However, a `TubeScoutError` hierarchy could improve error handling at API boundaries in the future.

### 9. Magic Numbers

**Result: 7 locations with inline magic numbers**

| File | Line | Value | Context |
|------|------|-------|---------|
| `services/youtube_analytics.py:14` | `_MAX_RETRIES = 3` | 3 | **Already a named constant** -- OK |
| `services/youtube_analytics.py:15` | `_RETRY_BASE_DELAY = 0.1` | 0.1 | **Already a named constant** -- OK |
| `services/topic_extractor.py:174` | `batch_size = 20` | 20 | LLM batch size -- local variable, not constant |
| `services/sentiment.py:175` | `batch_size = 20` | 20 | LLM batch size -- duplicated in two files |
| `services/forecaster.py:13` | `MIN_DATA_DAYS = 180` | 180 | **Already a class constant** -- OK |
| `services/forecaster.py:88` | `horizon_days: int = 30` | 30 | Default forecast horizon -- parameter default |
| `services/youtube_reporting.py:125-126` | `max_polls=60, interval=60` | 60, 60 | Poll limit and interval -- parameter defaults |
| `services/validator.py:182` | `pt.week > 16` | 16 | Max weeks per semester -- inline magic |
| `services/youtube_data.py:191` | `max_results: int = 100` | 100 | API page size -- parameter default |
| `reporting/channel_report.py:261` | `len(weak_axes) >= 2` | 2 | Threshold for "high" priority -- inline magic |
| `services/llm_adapter.py:95` | `max_tokens=4096` | 4096 | LLM max tokens -- inline magic |
| `services/llm_adapter.py:131` | `range(2)` | 2 | Retry attempts -- inline magic |
| `reporting/excel_export.py:117,152,185,187,215` | `width = 10/15/18/20` | Various | Column widths -- cosmetic, acceptable |

**Key findings**:
- `batch_size = 20` appears identically in both `sentiment.py` and `topic_extractor.py` -- should be a shared constant
- `pt.week > 16` (max semester weeks) should be a named constant
- `max_tokens=4096` and retry count `2` in `llm_adapter.py` should be constants
- Column widths in excel_export.py are cosmetic -- acceptable as-is

### 10. Docstrings

**Result: PASS** -- All public functions and classes have Google-style English docstrings.

Comprehensive check of all 48 modules confirms:
- All public functions have docstrings with Args/Returns/Raises sections where applicable
- All classes have class-level docstrings
- All docstrings are in English, Google style
- Private functions (prefixed `_`) also have docstrings in most cases

The only minor observation is that CLI command functions' docstrings serve double duty as typer help text, which is the intended pattern.

---

## Proposed Unification Rules

### Confirmed Conventions (already consistent)
1. **Error messages**: English only
2. **CLI options**: kebab-case for flags, snake_case for Python params
3. **Imports**: Absolute only (`from tube_scout.x import y`)
4. **Function naming**: snake_case, verb-first for non-CLI functions
5. **Type hints**: Full parameterized types on all public functions
6. **Docstrings**: Google-style English with Args/Returns/Raises
7. **Logging**: rich.Console in CLI layer, logging module in service layer

### Recommended Improvements
1. **Pydantic model_config**: Add `model_config = ConfigDict(extra="forbid")` to all data models to catch silent field typos
2. **Shared constants**: Extract `LLM_BATCH_SIZE = 20` and `MAX_SEMESTER_WEEKS = 16` to a shared config/constants module
3. **LLM constants**: Move `max_tokens=4096` and retry count to named constants in `llm_adapter.py`
4. **Type precision**: Fix `-> list:` to `-> list[ParsedTitle]` in `cli/search_cli.py:153`
5. **Custom exceptions**: Consider a `TubeScoutError` base class for domain-specific errors (future enhancement, not urgent)
