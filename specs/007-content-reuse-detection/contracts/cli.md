# CLI Contracts: Content Reuse Detection

## Command Group: `tube-scout content`

### `tube-scout content fingerprint`

Generate SHA-256 hash and semantic embedding for each video's caption text.

```
tube-scout content fingerprint --channel <alias>
  [--project <path|"latest">]
  [--year <int>] [--semester <int>]
  [--force-refresh]
```

**Input**: Collected caption JSON files in `01_collect/channels/{channel_id}/transcripts/`
**Output**: SQLite `fingerprint_hashes` table + `02_analyze/content/embeddings.parquet`
**Exit codes**: 0 success, 1 error, 2 no captions found

### `tube-scout content compare`

Compare matched video pairs across years using 5 indicators.

```
tube-scout content compare --channel <alias>
  --year-from <int> --year-to <int>
  [--project <path|"latest">]
  [--course <name>]
  [--professor <name>]
```

**Input**: Fingerprints + parsed title data
**Output**: SQLite `comparison_results` table
**Exit codes**: 0 success, 1 error, 2 no comparison pairs found

### `tube-scout content quality`

Run quality checklist (Q-001~Q-005) on all videos with captions.

```
tube-scout content quality --channel <alias>
  [--project <path|"latest">]
  [--year <int>] [--semester <int>]
```

**Input**: Caption JSON files + video metadata
**Output**: SQLite `quality_results` table
**Exit codes**: 0 success, 1 error

### `tube-scout content review`

View and update review status for comparison results.

```
tube-scout content review --channel <alias>
  [--project <path|"latest">]
  [--status <UNREVIEWED|CONFIRMED_DUPLICATE|FALSE_POSITIVE>]
  [--grade <critical|high|moderate|normal>]
  [--mark <comparison_id> <CONFIRMED_DUPLICATE|FALSE_POSITIVE>]
```

**Output (list mode)**: Rich table of comparison results filtered by status/grade
**Output (mark mode)**: Confirmation of status update
**Exit codes**: 0 success, 1 error, 2 no results found

### `tube-scout content scan`

Run full pipeline: fingerprint → compare → quality.

```
tube-scout content scan --channel <alias>
  --year-from <int> --year-to <int>
  [--project <path|"latest">]
  [--force-refresh]
```

**Behavior**: Executes fingerprint, compare, quality sequentially. Skips completed stages unless `--force-refresh`.
**Exit codes**: 0 success, 1 error

## Modified Command: `tube-scout collect transcripts`

Enhanced with Captions API fallback for private videos.

```
tube-scout collect transcripts --channel <alias>
  [--project <path|"latest">]
  [--force-refresh]
  [--private-only]          # NEW: only process private videos via Captions API
  [--quota-limit <int>]     # NEW: max API quota units to consume (default: 8000)
```

**New behavior**: After attempting `youtube-transcript-api`, falls back to Captions API for videos that return VideoUnplayable. Tracks per-video processing status in SQLite.

## Report Command: `tube-scout report content`

```
tube-scout report content --channel <alias>
  [--project <path|"latest">]
  --format <html|xlsx|json>
  [--year <int>] [--semester <int>]
  [--output-dir <path>]
```

**Output**: Report file at `03_report/content_quality/{channel_id}_{year}_{semester}.{format}`
**Exit codes**: 0 success, 1 error, 2 no data
