# CLI Contract Changes: 005-oauth-ratelimit-gpu

**Date**: 2026-04-05

## Modified Commands

### `collect all`

**Before**:
```
tube-scout collect all [--data-dir DIR] [--project-dir DIR] [--project PATH] [--force-refresh]
```

**After**:
```
tube-scout collect all [--channel ALIAS] [--data-dir DIR] [--project-dir DIR] [--project PATH] [--force-refresh]
```

**New option**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--channel` | str | None | Channel alias for multi-channel OAuth authentication. When omitted, uses default config. |

**Behavior changes**:
- With `--channel`: Authenticates via `authenticate_channel(alias)` and passes OAuth client to all 5 stages
- Without `--channel`: Existing behavior preserved (backward compatible)
- Stage failure: Aborts on video listing failure; continues on other stage failures with summary
- Resume: Detects completed stages on re-run and skips them (unless `--force-refresh`)

**Exit codes**:
| Code | Meaning |
|------|---------|
| 0 | All stages completed successfully |
| 1 | One or more non-critical stages failed (summary printed) |
| 2 | Video listing stage failed (pipeline aborted) |

### `collect videos`

**Before**: Accepts `--channel` + falls back to `YOUTUBE_API_KEY`
**After**: Accepts `--channel` only; OAuth required. API key fallback removed.

### All `collect *` subcommands

**Breaking change**: `YOUTUBE_API_KEY` environment variable no longer recognized. All authentication must go through OAuth.

## Removed Environment Variables

| Variable | Replacement |
|----------|-------------|
| `YOUTUBE_API_KEY` | OAuth via `TUBE_SCOUT_CLIENT_SECRET` |

## New Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TUBE_SCOUT_CLIENT_SECRET` | Yes | — | Path to OAuth client secret JSON file (agenix-managed) |
| `TUBE_SCOUT_DEVICE` | No | `cpu` | Compute device for ML tasks: `cpu` or `cuda` |

## Unchanged Environment Variables

| Variable | Description |
|----------|-------------|
| `TUBE_SCOUT_TOKENS_DIR` | Custom tokens directory (default: `~/.config/tube-scout/tokens/`) |

## Progress Output Contract

During rate-limited operations, the CLI displays:
```
Collecting transcripts... [####------] 45/214  (backoff: 5.0s after 429)
```

Backoff events are shown inline in the progress bar description. Normal operation shows only the counter.
