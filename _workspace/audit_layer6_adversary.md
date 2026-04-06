# Layer 6: Adversary Testing Results

## Summary

| Group | Persona | Tests | PASS | FAIL |
|-------|---------|-------|------|------|
| A-01 | New admin staff | 7 | 7 | 0 |
| A-02 | Rushed department head | 6 | 6 | 0 |
| A-03 | DX operator parallel | 6 | 6 | 0 |
| A-04 | Creative professor titles | 7 | 7 | 0 |
| A-05 | Wrong permissions TA | 5 | 5 | 0 |
| A-06 | Historical auditor | 5 | 5 | 0 |
| A-07 | Bad YAML user | 8 | 8 | 0 |
| A-08 | External evaluator | 6 | 6 | 0 |
| A-09 | Multi-project operator | 5 | 5 | 0 |
| A-10 | New machine user | 7 | 7 | 0 |
| B-01 | Corrupt filesystem | 10 | 10 | 0 |
| B-02 | Abnormal API responses | 9 | 9 | 0 |
| B-03 | Network failures | 7 | 7 | 0 |
| B-04 | Unicode edge cases | 10 | 10 | 0 |
| B-05 | Time anomalies | 8 | 8 | 0 |
| B-06 | Large scale | 8 | 8 | 0 |
| B-07 | Concurrency | 8 | 8 | 0 |
| Combo | 8 scenarios | 31 | 31 | 0 |
| **Total** | | **157** | **157** | **0** |

## Vulnerabilities Discovered (documented in passing tests)

Tests pass because they document the actual (broken) behavior. These are vulnerabilities where the system does NOT behave as users would expect.

### VULN-001: read_json fails on UTF-8 BOM files
- **Persona**: A-08 External evaluator
- **Test**: `test_json_with_bom_encoding_fails`
- **Expected**: JSON files with BOM (common from Windows) should be readable
- **Actual**: `read_json` uses `encoding="utf-8"` not `"utf-8-sig"`, so BOM causes `JSONDecodeError`
- **Impact**: External users transferring files from Windows cannot use them
- **Severity**: Medium
- **Fix**: Change `open(filepath, encoding="utf-8")` to `encoding="utf-8-sig"` in `json_store.py:20`

### VULN-002: write_json default=str silently serializes non-serializable objects
- **Persona**: B-01 Corrupt filesystem
- **Test**: `test_atomic_write_default_str_serializes_anything`
- **Expected**: Non-JSON-serializable objects should raise TypeError (fail-fast)
- **Actual**: `json.dump(..., default=str)` silently converts any object to its `str()` representation
- **Impact**: Corrupt data written silently, discovered only on later read
- **Severity**: Medium
- **Fix**: Remove `default=str` from `json.dump` call in `json_store.py:40`, or use a selective default that only handles known types (datetime, date, Path)

### VULN-003: Checkpoint schema changes cause silent data loss
- **Persona**: A-06 Historical auditor
- **Test**: `test_checkpoint_with_old_schema_forward_compat_fails`
- **Expected**: Old-format checkpoint data should either load with defaults or raise a clear migration error
- **Actual**: `load_checkpoint` → `CollectionState(**state_data)` raises `ValidationError` which is NOT caught, causing the checkpoint to be treated as non-existent (returns None via caller), meaning the collection restarts from scratch
- **Impact**: After schema changes, users lose all checkpoint progress silently
- **Severity**: High
- **Fix**: Catch `ValidationError` in `load_checkpoint`, log a warning about schema mismatch, and either migrate or return a degraded state

### VULN-004: Corrupt checkpoint file crashes load_checkpoint
- **Persona**: A-10 + B-01 combination
- **Test**: `test_half_written_checkpoint_crashes_on_load`
- **Expected**: Corrupt checkpoint file should be handled gracefully (return None or raise specific error)
- **Actual**: `read_json` raises `JSONDecodeError` which propagates uncaught through `load_checkpoint`
- **Impact**: Power loss during checkpoint write -> crash on next run, requiring manual file deletion
- **Severity**: High
- **Fix**: Catch `json.JSONDecodeError` in `load_checkpoint`, log the corruption, return None or attempt backup recovery

### VULN-005: Title parser fallback extracts false professor names
- **Persona**: A-04 Creative professor
- **Test**: `test_no_professor_name_in_title`
- **Expected**: "3주차 강의" should extract no professor
- **Actual**: Fallback regex `^(?:\d+[-\s.]*)?([가-힣]{2,4})\s` matches "주차" as professor name
- **Impact**: Incorrect professor attribution in reports and validation
- **Severity**: Low (known parser limitation, parse_error=True is set)

## PASS Tests Summary (System Defended Successfully)

The system correctly handles these adversary scenarios:

**Authentication & Authorization**
- Missing env vars produce clear error messages (TUBE_SCOUT_CLIENT_SECRET, TUBE_SCOUT_TOKENS_DIR)
- Invalid channel IDs rejected by Pydantic (UC prefix validation)
- Unregistered channel aliases raise KeyError with guidance message
- Token file missing for registered channel raises FileNotFoundError

**Checkpoint & Recovery**
- Checkpoint state preserved after interruption (in_progress, interrupted states)
- Different channels have isolated checkpoints
- Multiple phases (videos, retention, transcripts, analytics) coexist in same checkpoint file
- Checkpoint overwrite preserves other entries

**Data Isolation**
- Channel data in separate directories under collect/channels/{channel_id}/
- Project data fully isolated across different ProjectManager instances
- Latest symlink correctly tracks most recent project

**YAML & Config Validation**
- Empty YAML, null YAML, list YAML all produce clear ValueError
- YAML syntax errors (tabs/spaces) produce clear error messages
- Invalid week_range (inverted, wrong type) rejected by Pydantic
- Invalid semester values rejected

**Unicode & Encoding**
- RTL, emoji, zero-width, surrogate pairs all parse without crash
- 10KB titles parse without memory issues
- Unicode-heavy titles survive JSON write/read roundtrip
- Mixed Korean/English/Arabic titles handled gracefully

**Scale & Performance**
- 10,000 title batch parsing completes without error
- 50,000 video filtering works correctly
- Large Parquet files (50k rows) write/read correctly
- Append Parquet accumulates data correctly

**Filesystem & Atomicity**
- Atomic write_json creates parent directories
- write_parquet creates parent directories
- ProjectManager creates projects_root if missing
- Broken symlinks don't crash resolve_latest()
- Read-only directories raise appropriate PermissionError

**API Error Handling**
- ConnectionError, TimeoutError, SSLError propagate correctly
- HttpError (403, 404, 500) propagated from mock API
- Empty channel response raises clear ValueError
- Empty/malformed ISO 8601 durations return 0

## Test Files

- `tests/adversary/test_global_audit_user_personas.py` — 62 tests (A-01 ~ A-10)
- `tests/adversary/test_global_audit_env_conditions.py` — 64 tests (B-01 ~ B-07)
- `tests/adversary/test_global_audit_combinations.py` — 31 tests (8 combination scenarios)
