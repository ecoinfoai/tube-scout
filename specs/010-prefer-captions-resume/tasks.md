---
description: "Task list for spec 010 — Captions-First Priority + Skip-Existing Resume"
---

# Tasks: Captions-First Priority + Skip-Existing Resume

**Input**: Design documents from `/specs/010-prefer-captions-resume/`
**Prerequisites**: plan.md ✓, spec.md ✓ (8 FRs FR-010-01..08, 10 ECs EC-010-A..J), contracts/ ✓

**TDD Rule (NON-NEGOTIABLE)**: RED test written and confirmed failing BEFORE any GREEN implementation task (Constitution v1.1.0 Principle I).

**Rule 4 (HARD BLOCKING)**: Any modification to `src/tube_scout/cli/collect.py` (orchestrator) MUST be immediately followed by `SendMessage qa-engineer` with:
```
INTEGRATION: TranscriptService 호출됨 (orchestrator: src/tube_scout/cli/collect.py, change: modify-args, task: T-010-NN)
```
Missing tag → `RULE4_VIOLATION` FAIL.

**Adversary note**: `tests/adversary/test_transcripts_resume.py` already exists (24 cases, 3 PASS + 21 XFAIL-strict). Do NOT rewrite it. Implementation in T-010-07 and T-010-08 must flip the 21 XFAIL cases.

**Scope**: Exactly 4 source files. Do NOT modify any other file under `src/`.

---

## Wave 1 — RED: Unit tests for `transcript_cache.py` (new module)

- [ ] T-010-01 [RED] [FR-010-04, FR-010-05, EC-010-A..G]
  **File**: `tests/unit/test_transcript_cache.py`
  **Tests**:
  1. `cache_path_for("private_vid_001", tmp_dir)` returns `tmp_dir / "private_vid_001.json"`.
  2. `cache_path_for("../../../etc/passwd", tmp_dir)` raises `ValueError` (path traversal).
  3. `cache_path_for("vid/../../escape", tmp_dir)` raises `ValueError`.
  4. `is_valid_cache(path)` returns `False` when file does not exist.
  5. `is_valid_cache(path)` returns `False` when file contains truncated JSON (EC-010-A).
  6. `is_valid_cache(path)` returns `False` when JSON lacks `segments` key (EC-010-B).
  7. `is_valid_cache(path)` returns `False` when `segments == []` (EC-010-C).
  8. `is_valid_cache(path)` returns `True` when `segments` is a non-empty list; also returns segment count.
  9. `is_valid_cache(path)` returns `False` when path is a directory (EC-010-G).
  10. `partition_videos_by_cache(ids, dir, force_refresh=False)`: mix of cached/uncached/corrupt — correct split.
  11. `partition_videos_by_cache(ids, dir, force_refresh=True)` — always returns `([], all_ids)` regardless of cached files.
  **Acceptance**: All 11 tests exist and FAIL (module does not exist yet).
  **Depends on**: nothing

---

## Wave 2 — RED: Unit tests for `fetch_transcript` priority inversion

- [ ] T-010-02 [RED] [FR-010-03, EC-010-D, EC-010-F, EC-010-I]
  **File**: `tests/unit/test_fetch_transcript_priority.py`
  **Tests**:
  1. `prefer_captions_api=False` (default): scraper called first; `fetch_segments` NOT called when scraper succeeds.
  2. `prefer_captions_api=True`: `fetch_segments()` called first; scraper NOT called when API returns non-empty; result `source == "captions_api"`.
  3. `prefer_captions_api=True`, API returns `None`: falls through to scraper; scraper succeeds.
  4. `prefer_captions_api=True`, API returns `[]` (EC-010-F): falls through to scraper.
  5. `prefer_captions_api=True`, `captions_client is None` (EC-010-D): warning emitted; scraper runs; no `AttributeError`.
  6. `prefer_captions_api=True`, API raises `HttpError 403` (EC-010-I): treated as empty; falls through to scraper.
  **Acceptance**: All 6 tests exist and FAIL (`prefer_captions_api` param does not exist yet).
  **Depends on**: nothing (pure unit, mocks `TranscriptService._api` and `_captions_client`)

---

## Wave 3 — RED: Unit tests for `skipped` audit category

- [ ] T-010-03 [RED] [FR-010-06]
  **File**: `tests/unit/test_audit_skipped_category.py`
  **Tests**:
  1. `"skipped" in ALLOWED_CLASSIFICATIONS` — FAIL until added.
  2. A row dict with `classification="skipped"` round-trips through `write_audit_csv` + re-read with `csv.DictReader` without error.
  3. `hint` for a skipped row that starts with "Existing" does NOT trigger the Excel-injection guard (safe first char).
  **Acceptance**: All 3 tests exist and FAIL.
  **Depends on**: nothing

---

## Wave 4 — GREEN: `transcripts_audit.py`

- [ ] T-010-04 [GREEN] [FR-010-06]
  **File**: `src/tube_scout/services/transcripts_audit.py`
  **Change**: Add `"skipped"` to `ALLOWED_CLASSIFICATIONS`. No other change.
  **Acceptance**: T-010-03 passes. All pre-existing `transcripts_audit` tests still pass.
  **Depends on**: T-010-03

---

## Wave 5 — GREEN: `transcript_cache.py` (new module)

- [ ] T-010-05 [GREEN] [FR-010-04, FR-010-05, EC-010-A..G]
  **File**: `src/tube_scout/services/transcript_cache.py` (NEW)
  **Implement**:
  - `cache_path_for(video_id: str, transcripts_dir: Path) -> Path` — resolves path, asserts it is under `transcripts_dir`, raises `ValueError` on traversal.
  - `is_valid_cache(path: Path) -> tuple[bool, int]` — returns `(True, n_segs)` on valid cache, `(False, 0)` on absent/corrupt/empty. All JSON errors caught with `except (json.JSONDecodeError, KeyError, TypeError, OSError)`.
  - `partition_videos_by_cache(video_ids: list[str], transcripts_dir: Path, force_refresh: bool) -> tuple[list[tuple[str, int]], list[str]]` — when `force_refresh=True` always returns `([], video_ids)`.
  **Acceptance**: T-010-01 passes. `ruff check` clean on new file.
  **Depends on**: T-010-01

---

## Wave 6 — GREEN: `TranscriptService.fetch_transcript()` priority param

- [ ] T-010-06 [GREEN] [FR-010-03, EC-010-D, EC-010-F, EC-010-I]
  **File**: `src/tube_scout/services/transcript.py`
  **Change**: Add `prefer_captions_api: bool = False` parameter to `fetch_transcript()`.
  When `prefer_captions_api=True`:
  - If `self._captions_client is None`: `logger.warning("prefer_captions_api set but no captions client; falling back to scraper")`; proceed to scraper path.
  - Otherwise: call `self._captions_client.fetch_segments(video_id)`.
    - Non-empty result: return `{"video_id": ..., "transcript_type": "captions_api", "source": "captions_api", "segments": segments}`.
    - `None`, `[]`, or any `Exception` (including `HttpError 403`): fall through to existing scraper path.
  When `prefer_captions_api=False`: existing logic unchanged (scraper first).
  **Acceptance**: T-010-02 passes. All pre-existing `transcript.py` tests still pass.
  **Depends on**: T-010-02

---

## Wave 7 — RED: Contract + Integration tests for orchestrator

- [ ] T-010-07 [RED] [FR-010-01, FR-010-02, FR-010-04, FR-010-05, FR-010-07, FR-010-08, US2, US3]
  **Files**:
  - `tests/contract/test_collect_transcripts_010.py`
  - `tests/integration/test_transcripts_resume.py`

  **Contract tests** (`test_collect_transcripts_010.py`):
  1. `collect transcripts --help` output contains `--prefer-captions-api`.
  2. `collect transcripts --help` output contains `--force-refresh`.
  3. `CliRunner` invocation with `--prefer-captions-api` does not raise `UsageError`.
  4. `CliRunner` invocation with `--force-refresh` does not raise `UsageError`.
  5. With a valid cached file and no `--force-refresh`: `fetch_transcript` NOT called; audit CSV has 1 `skipped` row.
  6. With a valid cached file and `--force-refresh`: `fetch_transcript` IS called; audit CSV has 0 `skipped` rows.

  **Integration tests** (`test_transcripts_resume.py`):
  1. **Partial-then-resume**: 5 videos; 3 pre-populated valid JSONs; service called exactly 2 times; audit CSV has 3 `skipped` rows.
  2. **Force-refresh overrides**: same setup + `--force-refresh`; service called 5 times; 0 `skipped` rows.
  3. **Corrupt cache re-fetches**: one of the 3 pre-populated files is truncated JSON (EC-010-A); service called 3 times; corrupt file overwritten on success.
  4. **Empty-segments re-fetches**: one cached file has `{"segments": []}` (EC-010-C); service called 2 times.
  5. **`--video-id` respects cache** (EC-010-H): pass `--video-id <cached_vid>` without `--force-refresh`; service NOT called; 1 `skipped` row in audit CSV.

  **Acceptance**: All tests exist and FAIL (flags + skip logic not yet in orchestrator).
  **Depends on**: T-010-04, T-010-05

---

## Wave 8 — GREEN: Orchestrator wiring in `collect.py` ⚠️ Rule 4

- [ ] T-010-08 [GREEN] [FR-010-01, FR-010-02, FR-010-04, FR-010-05, FR-010-07, FR-010-08]
  **File**: `src/tube_scout/cli/collect.py`
  **Changes**:
  1. Add to `collect_transcripts_command`:
     ```python
     prefer_captions_api: bool = typer.Option(
         False, "--prefer-captions-api",
         help="Consult Captions API before scraper (for quota-extended OAuth operators).",
     )
     force_refresh: bool = typer.Option(
         False, "--force-refresh",
         help="Ignore cached transcripts and re-fetch all.",
     )
     ```
  2. Import `transcript_cache` from `tube_scout.services.transcript_cache`.
  3. Before the per-video loop compute `transcripts_dir = mgr.collect_dir / "transcripts"`.
  4. Call `skipped_with_counts, to_fetch = transcript_cache.partition_videos_by_cache(video_ids_to_collect, transcripts_dir, force_refresh)`.
  5. Emit dim line + build skipped audit row for each item in `skipped_with_counts`. Hint format: `"Existing transcript at {cache_path} ({n} segments); pass --force-refresh to override."`.
  6. In the fetch loop, pass `prefer_captions_api=prefer_captions_api` to every `service.fetch_transcript()` call.
  7. Replace `write_json(output_path, result)` with atomic write: `tmp = output_path.parent / f".{vid_id}.json.tmp"; write_json(tmp, result); os.replace(str(tmp), str(output_path))`.

  **⚠️ MANDATORY immediately after this task**: SendMessage to qa-engineer:
  ```
  INTEGRATION: TranscriptService 호출됨 (orchestrator: src/tube_scout/cli/collect.py, change: modify-args, task: T-010-08)
  ```

  **Acceptance**: T-010-07 passes. Adversary 21 XFAIL cases flip to XPASS. All spec-009 tests still pass. `ruff check` clean.
  **Depends on**: T-010-05, T-010-06, T-010-07

---

## Wave 9 — Final Verification

- [ ] T-010-09 [VERIFY] [FR-010-07, A7]
  **Actions**:
  1. `cd /home/kjeong/localgit/tube-scout/src && uv run pytest tests/ -q` — assert ≥1956 pre-existing tests pass + all new tests pass; 0 failures; adversary file has 0 XFAIL remaining.
  2. `uv run ruff check .` — assert 0 violations.
  **Depends on**: T-010-08

---

## Dependency Graph

```
T-010-01 (unit: transcript_cache RED)
T-010-02 (unit: fetch_transcript priority RED)
T-010-03 (unit: audit skipped RED)
  └─ T-010-04 (GREEN: transcripts_audit.py)
       └─ T-010-07 (RED: contract + integration)
T-010-01 → T-010-05 (GREEN: transcript_cache.py)
               └─ T-010-07
T-010-02 → T-010-06 (GREEN: transcript.py)
               └─ T-010-08 (GREEN: collect.py) ← Rule 4
T-010-04, T-010-05 → T-010-07
T-010-06, T-010-07 → T-010-08
T-010-08 → T-010-09
```

### Parallel Opportunities

- T-010-01, T-010-02, T-010-03: all independent; start simultaneously.
- T-010-04, T-010-05, T-010-06: all independent after their respective RED tasks; can run in parallel.
- T-010-07: waits for T-010-04 + T-010-05 (needed for meaningful RED runs).
- T-010-08: sequential; waits for T-010-06 + T-010-07.

---

## FR Traceability Matrix

| Task | FR / EC |
|---|---|
| T-010-01 | FR-010-04, FR-010-05, EC-010-A, EC-010-B, EC-010-C, EC-010-G |
| T-010-02 | FR-010-03, EC-010-D, EC-010-F, EC-010-I |
| T-010-03 | FR-010-06 |
| T-010-04 | FR-010-06 |
| T-010-05 | FR-010-04, FR-010-05, EC-010-A..G |
| T-010-06 | FR-010-03, EC-010-D, EC-010-F, EC-010-I |
| T-010-07 | FR-010-01, FR-010-02, FR-010-04, FR-010-05, FR-010-07, FR-010-08, EC-010-A, EC-010-C, EC-010-H |
| T-010-08 | FR-010-01, FR-010-02, FR-010-04, FR-010-05, FR-010-07, FR-010-08, EC-010-E |
| T-010-09 | FR-010-07 (regression), A7 |
