# Implementation Plan: Captions-First Priority + Skip-Existing Resume

**Branch**: `010-prefer-captions-resume` | **Date**: 2026-05-08 | **Spec**: [spec.md](./spec.md)

## Summary

Spec 010 delivers two orthogonal behaviour changes to `tube-scout collect transcripts`:

1. **`--prefer-captions-api` flag** — inverts `TranscriptService.fetch_transcript()`'s
   source priority so the Captions API is consulted first (scraper fallback only on
   `None`/empty result). Opt-in; default behaviour is unchanged.
2. **Skip-existing on resume** — before any API call the orchestrator checks whether
   a valid transcript JSON already exists; if yes, it is classified as `skipped` in
   the audit CSV and the API call is skipped entirely. `--force-refresh` overrides.

**Source files touched** (exactly these four):

- `src/tube_scout/services/transcript_cache.py` — NEW: cache validity helpers with path-traversal guard
- `src/tube_scout/cli/collect.py` — 2 new flags, skip loop (uses transcript_cache), atomic write
- `src/tube_scout/services/transcript.py` — `fetch_transcript()` gains `prefer_captions_api: bool`
- `src/tube_scout/services/transcripts_audit.py` — `ALLOWED_CLASSIFICATIONS` += `"skipped"`

No new third-party dependency. No schema changes to existing JSON or CSV formats.

---

## Architecture

### Component Map

```
collect_transcripts_command (cli/collect.py)
  │
  ├─[new]─ --prefer-captions-api : bool = False   (FR-010-01)
  ├─[new]─ --force-refresh : bool = False          (FR-010-02)
  │
  └─ per-video loop:
       │
       ├─[new]─ transcript_cache.partition_videos_by_cache(ids, transcripts_dir, force_refresh)
       │         returns (to_skip, to_fetch)
       │         │
       │         ├─ to_skip → emit dim line, build skipped audit row   (FR-010-04, FR-010-06)
       │         └─ to_fetch → call service.fetch_transcript(...)
       │
       └─ TranscriptService.fetch_transcript(
              video_id,
              audio_path=None,
              prefer_captions_api=prefer_captions_api,   ← [new] (FR-010-03)
          )
            │
            ├─[prefer=True]─ CaptionsAPIClient.fetch_segments() first
            │                 └─ empty/None → fall through to scraper
            └─[prefer=False]─ scraper first (spec-009 unchanged path)
                              └─ failure → CaptionsAPIClient.fetch_segments()
```

### New Module: `transcript_cache.py`

Extracts all cache-validity logic into a single, testable, injectable module.
This is the adversary's recommendation to prevent path-traversal (persona 12)
and to keep the orchestrator loop thin.

```python
# Public surface (all functions are pure / no I/O side-effects except reads)

def cache_path_for(video_id: str, transcripts_dir: Path) -> Path:
    """Return the expected JSON path, raising ValueError on path traversal."""

def is_valid_cache(path: Path) -> bool:
    """Return True iff path exists as a file, parses as JSON, and segments non-empty."""

def partition_videos_by_cache(
    video_ids: list[str],
    transcripts_dir: Path,
    force_refresh: bool,
) -> tuple[list[tuple[str, int]], list[str]]:
    """Return (skipped_with_counts, to_fetch).

    skipped_with_counts: list of (video_id, segment_count) for cache hits.
    to_fetch: video_ids where cache is absent, corrupt, or empty.
    When force_refresh=True, skipped_with_counts is always [] and to_fetch == video_ids.
    """
```

**Path-traversal guard** in `cache_path_for`: resolve the candidate path and assert
it is under `transcripts_dir`. Raise `ValueError` for any `video_id` that escapes
(e.g. `../../../etc/passwd`). The adversary's persona 12 has 8 cases covering this.

### Data Flow

```
collect_transcripts_command
  │
  ├─ resolve video_ids_to_collect (unchanged from spec-009)
  │
  ├─ skipped_with_counts, to_fetch =
  │     transcript_cache.partition_videos_by_cache(
  │         video_ids_to_collect, transcripts_dir, force_refresh)
  │
  ├─ for (vid_id, n_segs) in skipped_with_counts:
  │     print dim "{vid_id}: cached ({n_segs} segments)"
  │     append audit_row {classification="skipped", hint="...{n_segs} segments..."}
  │
  ├─ for vid_id in to_fetch:
  │     result = service.fetch_transcript(
  │                  vid_id, prefer_captions_api=prefer_captions_api)
  │     if result:
  │         atomic_write(transcripts_dir / f"{vid_id}.json", result)
  │     else:
  │         append miss audit_row
  │
  └─ write_audit_csv(audit_rows, audit_path)   (skips + misses)
```

### Atomic Write Invariant (FR-010-08)

```python
tmp = transcripts_dir / f".{vid_id}.json.tmp"
write_json(tmp, result)
os.replace(str(tmp), str(output_path))   # POSIX atomic
```

SIGINT between `write_json` and `os.replace` leaves a `.tmp` orphan, not a
half-written `<vid_id>.json`. `is_valid_cache()` reads `<vid_id>.json` only; `.tmp`
orphans never poison the cache.

---

## Risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | **Silent-skip regression (Rule 4)** — orchestrator adds skip branch but forgets to pass `prefer_captions_api` to `fetch_transcript()`, silently never using the flag | Medium | Rule 4 INTEGRATION tag mandatory on T-010-08; adversary persona "silent-skip detector" in existing `test_transcripts_resume.py` |
| R2 | **`json.JSONDecodeError` propagates uncaught** — corrupt cache crashes the whole run | Low | `is_valid_cache()` wraps all JSON reads in `try/except`; returns `False` on any parse failure |
| R3 | **Empty-segments treated as valid cache** — `segments == []` permanently skips a video | Low | Explicit `if not segments` guard inside `is_valid_cache()` |
| R4 | **`--prefer-captions-api` + `captions_client is None`** — `AttributeError` on `None.fetch_segments()` | Medium | Guard in `fetch_transcript()`: `if prefer_captions_api and self._captions_client is None: log warning; fall through to scraper` |
| R5 | **Path traversal in `cache_path_for`** — crafted `video_id` escapes `transcripts/` | Low | `cache_path_for` resolves path and asserts prefix; raises `ValueError`; adversary persona 12 covers 8 cases |
| R6 | **Audit CSV missing skipped rows** — skip logic fires but never appends to `audit_rows` | Low | Contract test asserts exact row count (skipped + miss) |
| R7 | **`ALLOWED_CLASSIFICATIONS` not updated** — `write_audit_csv` writes rows with unknown classification | Low | Unit test asserts `"skipped" in ALLOWED_CLASSIFICATIONS` before any impl change |
| R8 | **`cache_corrupt` classification scope creep** — adversary recommends a distinct `"cache_corrupt"` value; spec FR-010-06 mandates only `"skipped"`. A corrupt file that re-fetches successfully is not a miss and produces no audit row at all. | Low | Do NOT add `cache_corrupt` unless spec is amended. Corrupt → re-fetch → success: no audit row; corrupt → re-fetch → fail: use existing miss classifications. |

---

## Constitution Check

| # | Principle | Application | Status |
|---|---|---|---|
| I | Test-First (NON-NEGOTIABLE) | Every task in tasks.md has a RED test before GREEN impl | PASS |
| II | Fail-Fast | `is_valid_cache()` never swallows exceptions silently; corrupt → re-fetch. `prefer_captions_api + None client` → warning + fallback. Path traversal → `ValueError` (fail-fast). | PASS |
| III | Type Safety | All new functions fully annotated; `fetch_transcript()` new param typed `bool` with default | PASS |
| IV | CLI-First | All changes are CLI flag additions and service parameter additions only | PASS |
| V | Local-First | No new store; cache is the existing per-project `transcripts/` directory | PASS |
| VI | Secrets via agenix | No new secret; OAuth client unchanged | PASS |
| VII | Cross-Spec Boundary (NON-NEGOTIABLE) | spec-009 `transcripts_audit.py` schema extended additively only; `TranscriptService` public API backward-compatible (new param has default) | PASS |

### Cross-Spec Boundaries

| Boundary | Prior side | This spec | Test |
|---|---|---|---|
| `AUDIT_HEADER` + `write_audit_csv` (spec-009 FR-016) | Fixed 6-column header; CSV written per-run | `"skipped"` rows use same 6-column header; no column added | Contract test: skipped rows parse with same CSV reader as miss rows |
| `TranscriptService.fetch_transcript()` signature (spec-009 FR-014) | `(video_id, audio_path=None) -> dict \| None` | New param `prefer_captions_api: bool = False`; default preserves old behaviour | Unit test: call without new param → unchanged scraper-first path |
| `ALLOWED_CLASSIFICATIONS` (spec-009) | `frozenset` of 5 values | Gains `"skipped"` (total: 6) | Unit test: assert `"skipped" in ALLOWED_CLASSIFICATIONS` |
| `CaptionsAPIClient.fetch_segments()` (spec-009) | Returns `list[dict] \| None` | Consumed unchanged; empty-or-None → "no result" | No new contract (behaviour unchanged) |
| spec-007 content scan | Reads `transcripts/*.json` | No schema change; atomic write path unchanged | Existing spec-007 contract tests must stay green |
| Adversary suite (`tests/adversary/test_transcripts_resume.py`) | 24 cases, 3 PASS + 21 XFAIL-strict | Implementation must flip all 21 XFAIL to XPASS; adversary removes `xfail` markers after | T-010-10 final verify |

---

## Project Structure

### Source additions / changes

```
src/tube_scout/
├── services/
│   ├── transcript_cache.py      NEW: cache_path_for, is_valid_cache,
│   │                                 partition_videos_by_cache
│   ├── transcript.py            CHANGED: fetch_transcript gains prefer_captions_api param
│   └── transcripts_audit.py    CHANGED: ALLOWED_CLASSIFICATIONS += "skipped"
└── cli/
    └── collect.py               CHANGED: 2 new flags, skip loop, atomic write
```

### Test additions

```
tests/
├── unit/
│   ├── test_transcript_cache.py          NEW (is_valid_cache, partition, path-traversal)
│   ├── test_fetch_transcript_priority.py NEW (prefer_captions_api logic, 5 sub-cases)
│   └── test_audit_skipped_category.py   NEW (ALLOWED_CLASSIFICATIONS, row format)
├── contract/
│   └── test_collect_transcripts_010.py  NEW (CLI flags, skip-existing via CliRunner)
└── integration/
    └── test_transcripts_resume.py        NEW (partial-then-resume, 5 sub-cases)
```

Note: `tests/adversary/test_transcripts_resume.py` already exists (24 cases,
3 PASS + 21 XFAIL-strict). No new adversary file needed; implementation must
flip the 21 XFAIL cases.

---

## Complexity Tracking

> No Constitution violations. One justified addition:

| Item | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| New module `transcript_cache.py` | Path-traversal guard (adversary persona 12, 8 cases) + testability of cache logic in isolation | Inline in orchestrator loop mixes concerns and cannot be unit-tested without invoking the full CLI |
