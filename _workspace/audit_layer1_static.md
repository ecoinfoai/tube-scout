# Layer 1: Static Analysis Results

## 요약

| 검사 | 위반 수 | 심각도 |
|------|---------|--------|
| ruff lint | 0 | None |
| ruff format | 71 | Low |
| mypy | 37 (18 files) | Medium (10 real errors) / Low (27 missing stubs) |
| vulture (dead code) | 248 | Low (mostly Pydantic model fields at 60% confidence) |
| circular imports | 0 | None |
| bandit (security) | 3 | Low |

## 상세 결과

### 1. ruff lint

All checks passed. 위반 없음.

### 2. ruff format

71 files would be reformatted, 54 files already formatted.

**src/ (32 files):**
- `src/tube_scout/cli/analyze.py`
- `src/tube_scout/cli/auth_cli.py`
- `src/tube_scout/cli/collect.py`
- `src/tube_scout/cli/main.py`
- `src/tube_scout/cli/report.py`
- `src/tube_scout/cli/status.py`
- `src/tube_scout/models/analytics.py`
- `src/tube_scout/models/config.py`
- `src/tube_scout/models/parsed_title.py`
- `src/tube_scout/models/report.py`
- `src/tube_scout/models/validation.py`
- `src/tube_scout/models/video_filter.py`
- `src/tube_scout/reporting/bundle_report.py`
- `src/tube_scout/reporting/channel_report.py`
- `src/tube_scout/reporting/comment_report.py`
- `src/tube_scout/reporting/department_report.py`
- `src/tube_scout/reporting/excel_export.py`
- `src/tube_scout/reporting/video_report.py`
- `src/tube_scout/services/auth.py`
- `src/tube_scout/services/eqs.py`
- `src/tube_scout/services/forecaster.py`
- `src/tube_scout/services/llm_adapter.py`
- `src/tube_scout/services/rate_limiter.py`
- `src/tube_scout/services/search_service.py`
- `src/tube_scout/services/segmenter.py`
- `src/tube_scout/services/sentiment.py`
- `src/tube_scout/services/title_parser.py`
- `src/tube_scout/services/topic_extractor.py`
- `src/tube_scout/services/validator.py`
- `src/tube_scout/services/video_filter_service.py`
- `src/tube_scout/services/youtube_analytics.py`
- `src/tube_scout/services/youtube_data.py`
- `src/tube_scout/services/youtube_reporting.py`

**tests/ (39 files):**
- `tests/adversary/test_auth_failures.py`
- `tests/adversary/test_bundle_cli_adversary.py`
- `tests/adversary/test_feature004_final_adversary.py`
- `tests/adversary/test_filter_pdf_adversary.py`
- `tests/adversary/test_multichannel_adversary.py`
- `tests/adversary/test_rate_limit_edge.py`
- `tests/adversary/test_report_video_adversary.py`
- `tests/adversary/test_reporting_failures.py`
- `tests/adversary/test_v2_adversary.py`
- `tests/adversary/test_validation_edge_cases.py`
- `tests/integration/test_admin_flow.py`
- `tests/integration/test_collect_flow.py`
- `tests/integration/test_filtered_report.py`
- `tests/integration/test_report_performance.py`
- `tests/unit/test_auth.py`
- `tests/unit/test_auth_multi.py`
- `tests/unit/test_bundle_report.py`
- `tests/unit/test_channel_report.py`
- `tests/unit/test_checkpoint.py`
- `tests/unit/test_collect_all.py`
- `tests/unit/test_department_report.py`
- `tests/unit/test_device_config.py`
- `tests/unit/test_eqs_llm.py`
- `tests/unit/test_forecaster_ext.py`
- `tests/unit/test_llm_adapter.py`
- `tests/unit/test_output_manager.py`
- `tests/unit/test_report_cli_filter.py`
- `tests/unit/test_search_service.py`
- `tests/unit/test_segmenter_llm.py`
- `tests/unit/test_sentiment_llm.py`
- `tests/unit/test_sentiment_local.py`
- `tests/unit/test_topic_extractor.py`
- `tests/unit/test_transcript.py`
- `tests/unit/test_validator.py`
- `tests/unit/test_video_filter_service.py`
- `tests/unit/test_youtube_analytics.py`
- `tests/unit/test_youtube_analytics_ext.py`
- `tests/unit/test_youtube_data.py`

### 3. mypy

37 errors in 18 files (56 source files checked).

**Real Type Errors (10):**

| File | Line | Error | Code |
|------|------|-------|------|
| `services/validator.py` | 225 | Argument 1 to "add" of "set" has incompatible type `tuple[str, ...]`; expected `tuple[str, str]` | arg-type |
| `services/youtube_analytics.py` | 98 | Item "None" of `Any \| None` has no attribute "reports" | union-attr |
| `services/transcript.py` | 79,80,82,101,102,104 | Value of type `FetchedTranscriptSnippet` is not indexable | index (x6) |
| `reporting/video_report.py` | 104 | Incompatible return value type (got `dict[str, Any] \| None`, expected `list[dict[str, Any]] \| None`) | return-value |
| `reporting/bundle_report.py` | 326 | Incompatible return value type (got `dict[str, Any] \| None`, expected `list[dict[str, Any]] \| None`) | return-value |
| `cli/report.py` | 473 | Argument after ** must be a mapping, not "str" | arg-type |
| `services/sentiment.py` | 67 | No overload variant of "pipeline" matches argument types `str, str, str` | call-overload |
| `cli/analyze.py` | 677 | Incompatible `sort` key return type | arg-type / return-value |
| `cli/collect.py` | 822 | Cannot call function of unknown type | operator |

**Missing Type Annotations (3):**

| File | Line | Variable |
|------|------|----------|
| `cli/search_cli.py` | 177 | `results` needs `list[<type>]` annotation |
| `cli/report.py` | 359 | `topics_list` needs `list[<type>]` annotation |
| `cli/analyze.py` | 212, 308 | `comments` needs `list[<type>]` annotation |

**Missing Library Stubs (27 errors):** plotly, googleapiclient, openpyxl, yaml, weasyprint, statsmodels, pandas, prophet -- these are third-party stub issues, not code bugs.

### 4. vulture (dead code)

248 findings total. Most are Pydantic model fields/validators at 60% confidence (false positives for Pydantic).

**Likely True Positives (functions/classes potentially unused):**

| File | Line | Item | Confidence |
|------|------|------|------------|
| `cli/main.py` | 101 | unused variable `version` | 100% |
| `services/segmenter.py` | 127 | unused function `compare_with_retention` | 60% |
| `services/sentiment.py` | 281 | unused function `cross_reference_questions_hotspots` | 60% |
| `services/title_parser.py` | 295 | unused class `TitleParser` | 60% |
| `services/title_parser.py` | 380 | unused method `parse_batch` | 60% |
| `services/title_parser.py` | 416 | unused method `save_results` | 60% |
| `services/youtube_analytics.py` | 180-434 | 8 unused methods (`get_daily_metrics`, `get_traffic_sources`, `get_demographics`, `get_geography`, `get_devices`, `get_playback_locations`, `get_subscriber_changes`, `get_engagement_metrics`) | 60% |
| `services/youtube_data.py` | 317 | unused method `detect_new_videos` | 60% |
| `services/youtube_reporting.py` | 122,151,201 | unused methods `poll_until_ready`, `download_report`, `parse_report_csv` | 60% |
| `storage/checkpoint.py` | 57,74,100 | unused functions `is_stage_complete`, `mark_stage_complete`, `clear_checkpoint` | 60% |
| `storage/parquet_store.py` | 33 | unused function `append_parquet` | 60% |
| `visualization/charts.py` | 9 | unused function `create_retention_chart` | 60% |

**False Positives (Pydantic model fields/validators):** ~200 items across `models/` directory -- Pydantic fields and `@field_validator` methods that are accessed dynamically by the framework.

**False Positives (openpyxl/HTMLParser attributes):** ~15 items in `reporting/excel_export.py` and `reporting/bundle_report.py` -- attribute assignments used by library internals.

### 5. circular imports

No circular import errors detected. All modules in `src/tube_scout/` import successfully.

### 6. bandit (security)

3 findings, all Low severity.

| # | File | Line | Test ID | Severity | Confidence | Issue |
|---|------|------|---------|----------|------------|-------|
| 1 | `services/auth.py` | 23 | B105 | LOW | MEDIUM | Possible hardcoded password: `TOKEN_FILE = "token.json"` -- false positive, this is a filename constant, not a password |
| 2 | `services/rate_limiter.py` | 43 | B311 | LOW | HIGH | `random.uniform()` used for jitter -- acceptable for non-security rate limiting |
| 3 | `services/rate_limiter.py` | 66 | B311 | LOW | HIGH | `random.uniform()` used for jitter -- same as above |

CWE references:
- B105: CWE-259 (Use of Hard-coded Password)
- B311: CWE-330 (Use of Insufficiently Random Values)

## 심각도 분류

### Critical
- None

### High
- **mypy `report.py:473`**: `**kwargs` unpacking on a string -- this will crash at runtime if reached
- **mypy `video_report.py:104` / `bundle_report.py:326`**: Return type mismatch (`dict` vs `list[dict]`) -- may cause downstream type errors

### Medium
- **mypy `transcript.py`**: 6 indexing errors on `FetchedTranscriptSnippet` -- API may have changed or type stubs are wrong
- **mypy `validator.py:225`**: Wrong tuple type for set.add -- logical error
- **mypy `youtube_analytics.py:98`**: Missing None check before `.reports()` call
- **mypy `sentiment.py:67`**: `pipeline()` call signature mismatch with transformers stubs
- **ruff format**: 71 files need reformatting -- code style inconsistency

### Low
- **vulture**: ~15 potentially unused functions/methods (need manual verification)
- **bandit**: 3 low-severity findings (all false positives or acceptable usage)
- **mypy**: 27 missing library stubs (third-party package issue, not code bug)
- **mypy**: 3 missing type annotations on local variables
