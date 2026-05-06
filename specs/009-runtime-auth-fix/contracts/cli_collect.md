# Contract: `collect` command group (post-spec-009)

**Spec**: [../spec.md](../spec.md) · **Plan**: [../plan.md](../plan.md)

This contract defines the post-fix CLI surface for every `tube-scout collect
<subcommand>` after spec 009 lands. Every subcommand below is constrained to
the same auth/project resolution semantics. Deviations are violations of
FR-001 ~ FR-007.

---

## Common options (every subcommand)

| Option | Type | Default | Semantics |
|---|---|---|---|
| `--data-dir` | str | `./data` | unchanged from today |
| `--project-dir` | str | `./projects` | unchanged from today |
| `--project` | str \| None | None | None means "open latest" for consumers; "create new + commit_latest on success" for producers |
| `--channel` | str \| None | None | Alias from registry. None falls back to single-alias auto-select or refusal (FR-006) |

---

## Common preflight

Before any auth call, every subcommand MUST:

1. Run **legacy token migration** (one-shot, idempotent — FR-008/FR-009/FR-010).
2. Resolve the **channel alias** via `resolve_channel_alias(--channel)` (FR-006).
3. Resolve the **project** via `resolve_project(project_dir, --project, producer=<is_producer>)` (FR-001/FR-002).
4. Build the **API client** via `authenticate_channel(alias)` (FR-005).

Any of the above failing MUST raise a `UserFacingError` with `next_command`
(FR-017) and exit with non-zero status. No subcommand may proceed past
preflight on a missing token, missing project, or missing alias.

---

## `collect videos` (PRODUCER)

```text
tube-scout collect videos
    [--data-dir DIR]
    [--project-dir DIR]
    [--project (latest | <path> | <omitted>)]
    [--channel ALIAS]
    [--published-after YYYY-MM-DD]
    [--published-before YYYY-MM-DD]
```

- Producer: `--project` omitted → creates new project, commits `latest` on success.
- `--channel` semantics per common preflight.
- Output: `01_collect/channels/<channel_id>/videos_meta.{json,parquet}`.
- Side effect (NEW in this spec): `mgr.commit_latest()` invoked on success path.

---

## `collect transcripts` (CONSUMER)

```text
tube-scout collect transcripts
    [--data-dir DIR]
    [--project-dir DIR]
    [--project (latest | <path> | <omitted>)]
    [--channel ALIAS]
    [--video-id VID]
```

- Consumer: `--project` omitted → opens latest; fail-fast if none.
- `--channel` per common preflight.
- Reads `01_collect/channels/<channel_id>/videos_meta.json`.
- Writes `01_collect/transcripts/<video_id>.json` with NEW `source` field.
- Writes (NEW): `01_collect/transcripts_audit.csv` listing every miss.
- Output formatting (NEW): primary-library exception is one dim line when
  fallback succeeds; full traceback only when both paths fail.

---

## `collect retention` (CONSUMER)

```text
tube-scout collect retention
    [--data-dir DIR]
    [--project-dir DIR]
    [--project (latest | <path> | <omitted>)]
    [--channel ALIAS]              # NEW
    [--video-id VID]
```

- **NEW**: `--channel` option accepted (FR-007).
- Auth: `authenticate_channel(alias)` — uses `tokens/<alias>.json`. Does
  **NOT** consult legacy `token.json` (FR-005 / FR-010).
- Calls YouTube Analytics API (`youtubeAnalytics.v2.reports.query`) with the
  alias's token.

---

## `collect comments` (CONSUMER)

```text
tube-scout collect comments
    [--data-dir DIR]
    [--project-dir DIR]
    [--project (latest | <path> | <omitted>)]
    [--channel ALIAS]
    [--video-id VID]
    [--include-replies]
```

- Already accepts `--channel` today; ensures preflight is consistent.
- No new behavior.

---

## `collect analytics` (CONSUMER)

```text
tube-scout collect analytics
    [--data-dir DIR]
    [--project-dir DIR]
    [--project (latest | <path> | <omitted>)]
    [--channel ALIAS]              # NEW
```

- **NEW**: `--channel` option accepted (FR-007).
- Auth: `authenticate_channel(alias)` for both Analytics and Reporting clients.

---

## `collect bulk` (CONSUMER)

```text
tube-scout collect bulk
    [--data-dir DIR]
    [--project-dir DIR]
    [--project (latest | <path> | <omitted>)]
    [--channel ALIAS]              # NEW
    [--check JOB_ID]
```

- **NEW**: `--channel` option accepted (FR-007).
- Auth: `authenticate_channel(alias)` for Reporting API.

---

## `collect all` (composite)

```text
tube-scout collect all
    [--data-dir DIR]
    [--project-dir DIR]
    [--channel ALIAS]
```

- Internally invokes `collect videos` (PRODUCER) → `collect transcripts` →
  `collect retention` → `collect comments` → `collect analytics` →
  `collect bulk` in order.
- Producer step creates the project and commits `latest` once. Subsequent
  steps consume the same project.
- `--project` is intentionally omitted (composite manages it internally);
  passing `--project` is rejected with a clear message.

---

## Error contract

| Failure mode | Error class | `next_command` |
|---|---|---|
| `--channel` missing, registry empty | `NoAliasRegistered` | `tube-scout auth --channel <name>` |
| `--channel` missing, registry has ≥2 | `MultipleAliasesNoSelection` | `tube-scout <cmd> --channel <listed-alias>` |
| `--channel <bad>` not in registry | `UserFacingError` (existing pattern) | `tube-scout auth --channel <bad>` |
| Consumer + `--project=` omitted + no `latest` | `LatestProjectMissing` | `tube-scout collect videos --channel <alias>` |
| Producer + `--project=` omitted + auth missing | `ProducerCommandRequiresChannel` | `tube-scout auth --channel <alias>` |
| Stored token scope-deficient | `ScopeReauthRequired` (idea6, unchanged) | `tube-scout auth --revoke <alias> && tube-scout auth --channel <alias>` |
| Headless TTY + `--browser-redirect` | `InteractiveAuthRequired` (idea6) | (auto fallback to device flow if available) |

All errors are rendered via the existing `cli.errors.render_error` helper.

---

## Invariants (every collect subcommand)

- MUST NOT create a fresh empty project on consumer commands (FR-001).
- MUST NOT consult `token.json` or `token_forcessl.json` after migration completes (FR-010).
- MUST NOT hang waiting for a TCP callback (FR-011 / FR-013).
- MUST NOT silent-skip a missing project, alias, or token (FR-018).
- MUST emit error messages with `next_command` (FR-017).
