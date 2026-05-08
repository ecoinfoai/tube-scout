# Contract: `tube-scout collect transcripts` (spec 010 additions)

**Owner**: spec 010 | **Date**: 2026-05-08
**Baseline**: spec-009 `collect_transcripts_command` (src/tube_scout/cli/collect.py:467)

This contract documents ONLY the additions made by spec 010. All spec-009 flags and
behaviour are preserved unchanged.

---

## New CLI Flags

### `--prefer-captions-api`

| Property | Value |
|---|---|
| Type | `bool` |
| Default | `False` |
| Typer option | `--prefer-captions-api` |
| Help text | `Consult Captions API before scraper (for quota-extended OAuth operators).` |
| Scope | `collect transcripts` only |

**Semantics**:
- When `False` (default): `TranscriptService.fetch_transcript()` uses scraper first,
  Captions API on scraper failure. Byte-identical to spec-009 master (FR-010-07).
- When `True`: `TranscriptService.fetch_transcript()` calls
  `CaptionsAPIClient.fetch_segments(video_id)` first. If non-empty result is returned,
  that result is used immediately and the scraper is NOT called. If `None`, `[]`, or
  any exception (including `HttpError 403 quotaExceeded`), the method falls through to
  the existing scraper path (EC-010-I).
- When `True` but `captions_client is None` (EC-010-D): a warning line is logged and
  the scraper path runs. The command does NOT raise an exception.

**FR reference**: FR-010-01, FR-010-03.

---

### `--force-refresh`

| Property | Value |
|---|---|
| Type | `bool` |
| Default | `False` |
| Typer option | `--force-refresh` |
| Help text | `Ignore cached transcripts and re-fetch all.` |
| Scope | `collect transcripts` (mirrors identical flag on `collect videos`) |

**Semantics**:
- When `False` (default): skip-existing check fires before each API call. A valid
  cached JSON (`segments` non-empty) causes the video to be skipped.
- When `True`: skip-existing check is bypassed entirely. Every video proceeds through
  the full fetch path. Existing transcript JSON files are atomically overwritten on
  success. No `skipped` audit rows are emitted (US3 acceptance #3).

**FR reference**: FR-010-02, FR-010-05.

---

## New Service Module: `transcript_cache.py`

`src/tube_scout/services/transcript_cache.py` is introduced to isolate all cache
validation logic from the orchestrator and to enforce the path-traversal guard
(adversary persona 12).

### `cache_path_for(video_id, transcripts_dir) -> Path`

Returns `transcripts_dir / f"{video_id}.json"` after verifying the resolved path
is a child of `transcripts_dir`. Raises `ValueError` on path traversal.

```python
def cache_path_for(video_id: str, transcripts_dir: Path) -> Path:
    ...
```

### `is_valid_cache(path) -> tuple[bool, int]`

Returns `(True, n_segments)` when:
- `path` exists as a regular file (not directory),
- JSON parses without error,
- `segments` key exists and is a non-empty list.

Returns `(False, 0)` in all other cases. All exceptions (`json.JSONDecodeError`,
`KeyError`, `TypeError`, `OSError`) are caught and treated as cache-miss.

```python
def is_valid_cache(path: Path) -> tuple[bool, int]:
    ...
```

### `partition_videos_by_cache(video_ids, transcripts_dir, force_refresh) -> tuple[...]`

```python
def partition_videos_by_cache(
    video_ids: list[str],
    transcripts_dir: Path,
    force_refresh: bool,
) -> tuple[list[tuple[str, int]], list[str]]:
    ...
```

Returns `(skipped_with_counts, to_fetch)` where:
- `skipped_with_counts`: list of `(video_id, n_segments)` for valid cache hits.
- `to_fetch`: video IDs where cache is absent, corrupt, or empty.
- When `force_refresh=True`: always returns `([], video_ids)`.

---

## Skip-Existing Behaviour in Orchestrator

The orchestrator calls `partition_videos_by_cache` once, before the fetch loop:

```python
transcripts_dir = mgr.collect_dir / "transcripts"
skipped_with_counts, to_fetch = transcript_cache.partition_videos_by_cache(
    video_ids_to_collect, transcripts_dir, force_refresh
)
```

For each `(vid_id, n_segs)` in `skipped_with_counts`:
- Print: `  [dim]{vid_id}: cached ({n_segs} segments)[/dim]`
- Append audit row with `classification="skipped"` and hint (see below).

For each `vid_id` in `to_fetch`:
- Call `service.fetch_transcript(vid_id, prefer_captions_api=prefer_captions_api)`.
- On success: atomic write.
- On `None`/exception: append miss audit row.

**FR reference**: FR-010-04, FR-010-05.

---

## `TranscriptService.fetch_transcript()` Signature Change

```python
# BEFORE (spec-009)
def fetch_transcript(
    self,
    video_id: str,
    audio_path: str | None = None,
) -> dict[str, Any] | None: ...

# AFTER (spec-010)
def fetch_transcript(
    self,
    video_id: str,
    audio_path: str | None = None,
    prefer_captions_api: bool = False,
) -> dict[str, Any] | None: ...
```

Default `False` preserves all existing spec-009 call sites without modification.

**FR reference**: FR-010-03.

---

## Audit CSV Contract Extension

The `transcripts_audit.csv` header is **unchanged**:

```
video_id,title,published_at,privacy_status,classification,hint
```

`ALLOWED_CLASSIFICATIONS` gains `"skipped"` (total 6 values):

```python
ALLOWED_CLASSIFICATIONS: frozenset[str] = frozenset({
    "private_no_captions_api",
    "transcripts_disabled",
    "no_caption_track",
    "api_error",
    "unknown",
    "skipped",    # NEW in spec 010
})
```

Skipped rows are constructed **inline in the orchestrator** (not via `classify_miss()`).

**Hint format** (from spec.md Output Format section):

```
Existing transcript at <path> (<N> segments); pass --force-refresh to override.
```

Example:

```
private_vid_001,Sample Lecture Week 13,2026-04-06T07:24:13Z,unlisted,skipped,Existing transcript at projects/20260508T093012/01_collect/transcripts/private_vid_001.json (87 segments); pass --force-refresh to override.
```

**FR reference**: FR-010-06.

---

## Atomic Write Contract (FR-010-08)

All transcript JSON writes (new fetch or `--force-refresh` overwrite) are atomic:

```python
tmp = output_path.parent / f".{vid_id}.json.tmp"
write_json(tmp, result)
os.replace(str(tmp), str(output_path))   # POSIX atomic rename
```

A SIGINT between `write_json` and `os.replace` leaves a `.tmp` orphan, not a
half-written `<vid_id>.json`. `is_valid_cache()` reads `<vid_id>.json` only;
`.tmp` orphans are never treated as valid cache.

---

## Path-Traversal Guard

`cache_path_for()` rejects any `video_id` that causes the resolved path to escape
`transcripts_dir`:

```python
resolved = (transcripts_dir / f"{video_id}.json").resolve()
if not str(resolved).startswith(str(transcripts_dir.resolve())):
    raise ValueError(f"Path traversal detected for video_id={video_id!r}")
```

Crafted IDs like `"../../../etc/passwd"` or `"vid/../../escape"` raise `ValueError`.
The orchestrator catches `ValueError` per-video, logs a dim warning, and continues.

---

## Non-Regression Guarantee

With `--prefer-captions-api=False`, `--force-refresh=False`, and an empty
`transcripts/` directory, `collect_transcripts_command` produces behaviour
byte-identical to spec-009 master (FR-010-07). Verified by T-010-09.

---

## Error / Warning Messages

| Condition | Output | Severity |
|---|---|---|
| `prefer_captions_api=True` and `captions_client is None` (EC-010-D) | `prefer_captions_api set but no captions client; falling back to scraper` | `logger.warning` |
| Cache hit (valid) | `{vid_id}: cached ({N} segments)` | `[dim]` console line |
| Cache is a directory (EC-010-G) | treated as absent by `is_valid_cache` → re-fetch silently | n/a (no console output beyond normal fetch line) |
| Path traversal in `video_id` | `{vid_id}: invalid video_id (path traversal), skipping` | `[yellow]` console line; no audit row |
