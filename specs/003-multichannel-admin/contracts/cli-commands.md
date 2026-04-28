# CLI Commands Contract: Multi-Channel Administration

**Date**: 2026-04-04

## Authentication Commands

### `tube-scout auth --channel <alias>`

Register a new department channel via OAuth.

```
tube-scout auth --channel <alias>

Arguments:
  --channel TEXT    Department alias (required, e.g., "간호학과")
```

**Flow**: Opens browser → admin logs in → system detects channel via `channels.list(mine=True)` → stores token as `tokens/{alias}.json` → updates `channels.json` registry.

**Exit Codes**: 0 = success, 1 = OAuth cancelled, 2 = no channel found on account

### `tube-scout auth --list`

List all registered channels.

```
tube-scout auth --list
```

**Output**: Rich table with columns: Alias, Channel Name, Channel ID, Registered, Last Used

### `tube-scout auth --revoke <alias>`

Remove a channel's token.

```
tube-scout auth --revoke <alias>

Arguments:
  --revoke TEXT    Channel alias to remove (required)
```

**Exit Codes**: 0 = success, 1 = alias not found

## Search Commands

### `tube-scout search`

Search videos using YAML config or CLI flags.

```
tube-scout search [OPTIONS]

Options:
  --config PATH       YAML search configuration file (search_clips.yaml)
  --channel TEXT       Channel alias (required if not in YAML)
  --professor TEXT     Filter by professor name (partial match)
  --course TEXT        Filter by course name (partial match)
  --year INT           Filter by academic year
  --semester INT       Filter by semester (1 or 2)
  --week-from INT      Filter week range start
  --week-to INT        Filter week range end
  --export PATH        Export results to JSON file
```

**Output**: Rich table with columns: Video ID, Professor, Course, Year, Week, Session, Duration, Views

**Exit Codes**: 0 = results found, 1 = no results, 2 = config parse error

## Report Commands

### `tube-scout report department`

Generate department-level analysis report.

```
tube-scout report department [OPTIONS]

Options:
  --channel TEXT       Channel alias (required)
  --format TEXT        Output format: html (default) | xlsx | pdf
  --year INT           Scope to academic year
  --semester INT       Scope to semester (1 or 2)
  --output-dir PATH    Override output directory
```

**Exit Codes**: 0 = report generated, 1 = no data, 2 = channel not found

## Validation Commands

### `tube-scout validate`

Run title validation rules on a channel.

```
tube-scout validate [OPTIONS]

Options:
  --channel TEXT       Channel alias (required)
  --year INT           Scope to academic year
  --semester INT       Scope to semester (1 or 2)
  --output TEXT        Output format: report (default) | json | table
  --rules TEXT         Run specific rules only (comma-separated: V-001,V-002)
```

**Output**: Findings grouped by severity (ERROR → WARNING → INFO) with per-professor summary.

**Exit Codes**: 0 = no errors, 1 = errors found, 2 = channel not found

## Modified Existing Commands

### `tube-scout collect videos` (extended)

```
Options added:
  --channel TEXT       Channel alias (uses multi-channel token)
```

### `tube-scout collect analytics` (extended)

```
Options added:
  --channel TEXT       Channel alias (uses multi-channel token)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| TUBE_SCOUT_TOKENS_DIR | ~/.config/tube-scout/tokens/ | Token storage directory (agenix override) |
| TUBE_SCOUT_OUTPUT_DIR | ./output/ | Base output directory |

## Error Messages

| Code | Message Pattern |
|------|----------------|
| CHANNEL_NOT_FOUND | "Channel '{alias}' is not registered. Run 'tube-scout auth --channel {alias}' first." |
| TOKEN_EXPIRED | "Token for '{alias}' could not be refreshed. Please re-authenticate." |
| PARSE_CONFIG_ERROR | "Failed to parse search configuration: {reason}" |
| NO_VIDEOS | "No videos found for channel '{alias}' matching the given criteria." |
| CALENDAR_MISSING | "Academic calendar not configured. Compliance analysis will be skipped. Use 'tube-scout calendar set --file PATH'." |
