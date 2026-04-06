# Tube Scout v0.1.0 — Audit Remediation Tasks

## Context
- Source: `_workspace/audit_remediation_plan.md`
- Scope: 16 fix tasks (High 6, Medium 5, Low 5)
- Verification: 기존 1,067 + 신규 246 테스트 전부 PASS
- Rule: TDD — 실패 테스트 확인(RED) → 수정(GREEN) → 정리(REFACTOR)

---

## Tasks

### T-001: Fix kwargs unpacking crash in cli/report.py [H-01]
- **File**: `src/tube_scout/cli/report.py:473`
- **Problem**: `**kwargs` unpacking on a string causes runtime crash
- **Fix**: Identify the string being unpacked and correct to proper dict unpacking
- **Test**: `uv run pytest tests/ -k "report" -x`
- **Severity**: High

### T-002: Harden checkpoint against corruption and schema changes [H-04+H-05]
- **File**: `src/tube_scout/storage/checkpoint.py`
- **Problem**: (1) Line 47: JSONDecodeError from corrupted checkpoint file is unhandled → crash after power loss. (2) Line 54: Schema validation failure returns None silently → collection restarts from scratch after upgrade
- **Fix**: (1) Catch JSONDecodeError, log warning, return None (treat as fresh start with warning message). (2) On ValidationError, log warning with old schema info, backup old file, return None with clear message explaining restart reason
- **Test**: `uv run pytest tests/adversary/test_global_audit_env_conditions.py -k "checkpoint" -x` and `uv run pytest tests/unit/test_checkpoint.py -x`
- **Severity**: High

### T-003: Fix transcript snippet indexing errors [H-06]
- **File**: `src/tube_scout/services/transcript.py`
- **Problem**: 6 mypy errors — FetchedTranscriptSnippet accessed by index but may not support indexing (API type change suspected)
- **Fix**: Check youtube-transcript-api current version's FetchedTranscriptSnippet type. Use dict-style access (.text, .start, .duration) instead of index access if API changed
- **Test**: `uv run pytest tests/unit/test_transcript.py -x`
- **Severity**: High

### T-004: Secure OAuth token file permissions + atomic write [H-02+L-07]
- **File**: `src/tube_scout/services/auth.py`
- **Problem**: (1) 4 `write_text()` calls save tokens with umask default 0644 — readable by other users on shared servers. (2) Token writes are non-atomic — power loss during write corrupts token file
- **Fix**: (1) Use `os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)` + `os.fdopen()` for all token writes. (2) Write to temp file + `os.rename()` for atomicity (same pattern as json_store.py)
- **Test**: `uv run pytest tests/unit/test_auth.py tests/unit/test_auth_multi.py -x`
- **Severity**: High

### T-005: Add network timeouts to all external API calls [H-03]
- **File**: `src/tube_scout/services/youtube_data.py`, `youtube_analytics.py`, `youtube_reporting.py`, `transcript.py`, `llm_adapter.py`, `sentiment.py`
- **Problem**: No explicit timeout on google-api-python-client, youtube-transcript-api, anthropic/openai SDK calls — CLI can hang indefinitely
- **Fix**: Add timeout parameters: google API client `http=httplib2.Http(timeout=60)`, transcript API timeout param, anthropic/openai `timeout=60`. Extract timeout as configurable constant `DEFAULT_API_TIMEOUT_SECONDS = 60`
- **Test**: `uv run pytest tests/unit/test_youtube_data.py tests/unit/test_youtube_analytics.py tests/unit/test_transcript.py tests/unit/test_llm_adapter.py -x`
- **Severity**: High

### T-006: Defend against Excel formula injection [M-01]
- **File**: `src/tube_scout/reporting/excel_export.py`
- **Problem**: External data (video titles, professor names) written directly to Excel cells. Values starting with `=`, `+`, `-`, `@` are executed as formulas
- **Fix**: Add `_sanitize_cell(value)` helper that prefixes dangerous characters with a single quote `'`. Apply to all cells containing external data
- **Test**: `uv run pytest tests/unit/test_excel_export.py -x`
- **Severity**: Medium

### T-007: Fix json_store default=str and add BOM support [M-03+M-04]
- **File**: `src/tube_scout/storage/json_store.py`
- **Problem**: (1) Line 40: `default=str` silently converts any non-serializable object to string — masks bugs and corrupts data. (2) Line 20: `encoding="utf-8"` fails on UTF-8 BOM files copied from Windows
- **Fix**: (1) Remove `default=str`. Use explicit serializer or raise TypeError for unserializable objects. (2) Change `encoding="utf-8"` to `encoding="utf-8-sig"` in `read_json()`
- **Test**: `uv run pytest tests/unit/test_json_store.py tests/adversary/test_global_audit_env_conditions.py -k "json" -x`
- **Severity**: Medium

### T-008: Fix validator tuple type error [M-05]
- **File**: `src/tube_scout/services/validator.py:225`
- **Problem**: Incorrect tuple type used with `set.add()` — validation logic error
- **Fix**: Correct the type being added to set (inspect actual usage and fix accordingly)
- **Test**: `uv run pytest tests/unit/test_validator.py -x`
- **Severity**: Medium

### T-009: Fix reporting return type inconsistencies [M-06]
- **File**: `src/tube_scout/reporting/video_report.py:104`, `src/tube_scout/reporting/bundle_report.py:326`
- **Problem**: Functions return `dict` in some paths and `list[dict]` in others — type mismatch
- **Fix**: Unify return types to match declared signatures and caller expectations
- **Test**: `uv run pytest tests/unit/test_report.py tests/unit/test_bundle_report.py -x`
- **Severity**: Medium

### T-010: Add None check in youtube_analytics [M-07]
- **File**: `src/tube_scout/services/youtube_analytics.py:98`
- **Problem**: Missing None check before attribute access — AttributeError under specific conditions
- **Fix**: Add `if result is None: return []` (or appropriate empty default) before the attribute access
- **Test**: `uv run pytest tests/unit/test_youtube_analytics.py -x`
- **Severity**: Medium

### T-011: Apply ruff format to entire codebase [L-01]
- **File**: `src/` and `tests/` (71 files)
- **Problem**: 71 files have formatting inconsistencies
- **Fix**: `uv run ruff format src/ tests/`
- **Test**: `uv run ruff format --check src/ tests/` (0 violations)
- **Severity**: Low

### T-012: Extract magic numbers to constants + fix type hint [L-02+L-03]
- **Files**: `services/sentiment.py`, `services/topic_extractor.py` (batch_size=20), `services/validator.py:182` (week>16), `services/llm_adapter.py` (max_tokens=4096, retry range(2)), `cli/search_cli.py:153` (return type)
- **Problem**: Hard-coded magic numbers scattered across modules; incomplete type hint
- **Fix**: Extract to module-level constants with descriptive names. Fix `-> list` to `-> list[ParsedTitle]`
- **Test**: `uv run pytest tests/unit/test_sentiment.py tests/unit/test_validator.py tests/unit/test_llm_adapter.py tests/unit/test_search_service.py -x`
- **Severity**: Low

### T-013: Apply rate_limiter to YouTubeDataService [L-05]
- **File**: `src/tube_scout/services/youtube_data.py`
- **Problem**: `list_all_videos()`, `get_video_details()`, `get_comments()` make bulk API calls without throttling — quota exhaustion risk
- **Fix**: Inject `RateLimiter` dependency and call `limiter.wait()` before each API request, matching the pattern in other services
- **Test**: `uv run pytest tests/unit/test_youtube_data.py -x`
- **Severity**: Low

### T-014: Fix title_parser fallback professor extraction [L-08]
- **File**: `src/tube_scout/services/title_parser.py:268`
- **Problem**: Fallback regex extracts "주차" as professor name from titles like "3주차 강의"
- **Fix**: Add negative lookahead or post-validation to exclude known Korean suffixes (주차, 차시, 학과, etc.) from professor name candidates
- **Test**: `uv run pytest tests/unit/test_title_parser.py tests/adversary/test_global_audit_user_personas.py -k "title" -x`
- **Severity**: Low

### T-015: Fix checkpoint path double nesting [L-10]
- **File**: `src/tube_scout/storage/checkpoint.py` (or `output/manager.py`)
- **Problem**: `_checkpoint_path()` appends `checkpoints/` but `mgr.checkpoint_dir` already includes it → `checkpoints/checkpoints/collection_state.json`
- **Fix**: Remove the redundant `checkpoints/` prefix from one location
- **Test**: `uv run pytest tests/integration/test_global_audit_e2e.py -x`
- **Severity**: Low
- **Note**: This may affect existing checkpoint files — verify backward compatibility or add migration

### T-016: Fix pre-existing forecaster test failures [I-06]
- **File**: `tests/unit/test_forecaster_ext.py`
- **Problem**: 11 tests fail due to prophet/statsmodels compatibility issues (pre-existing)
- **Fix**: Investigate prophet/statsmodels version compatibility. Fix test expectations or source code to match current library behavior
- **Test**: `uv run pytest tests/unit/test_forecaster_ext.py -x`
- **Severity**: Low

---

## Final Verification

After all tasks complete:
```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pytest --tb=short
```

Target: **0 ruff violations, all tests PASS**
