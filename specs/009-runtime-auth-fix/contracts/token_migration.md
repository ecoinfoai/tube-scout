# Contract: Legacy Token Migration

**Spec**: [../spec.md](../spec.md) · **Plan**: [../plan.md](../plan.md)
**Source**: [research.md R2](../research.md) · spec FR-008 / FR-009 / FR-010

This contract defines the one-shot migration of legacy single-channel
tokens (`token.json`, `token_forcessl.json`) into the multi-channel
`tokens/<alias>.json` layout introduced by idea6.

---

## Trigger

Migration runs at most once per process, **before** any auth-using command's
preflight finishes. Triggered by:

- The first call to `authenticate_channel(alias)` in a process (lazy import
  of `services/auth_migration.py:run_once()`).
- Or explicitly by `tube-scout auth --channel <alias>` (also routes through
  `authenticate_channel`).

A module-level flag prevents re-entry within the same process. Across
processes, an `fcntl.flock` advisory lock on
`~/.config/tube-scout/.migration.lock` serializes concurrent invocations.

---

## Inputs

| Path | Read? | Required? |
|---|---|---|
| `~/.config/tube-scout/token.json` | yes (if exists) | no |
| `~/.config/tube-scout/token_forcessl.json` | yes (if exists) | no |
| `~/.config/tube-scout/tokens/channels.json` | yes (always) | no (treated as empty if missing) |
| `~/.config/tube-scout/tokens/<existing-alias>.json` | yes (per match) | no |

If both legacy paths are missing, migration is a no-op.

---

## Algorithm

```text
acquire flock(~/.config/tube-scout/.migration.lock):
    for path in [token.json, token_forcessl.json]:
        if not path.exists():
            continue
        try:
            creds = Credentials.from_authorized_user_file(path)
        except (json.JSONDecodeError, ValueError):
            log "legacy token at {path} is corrupt; deleting"
            path.unlink()
            continue
        channel_id = recover_channel_id(creds)  # uses cache file
        if channel_id is None:
            log "could not recover channel_id for legacy token at {path}; deleting"
            path.unlink()
            continue
        registry = load_channels_registry()
        match = first alias whose channel_id == channel_id
        if match is None:
            log "legacy token at {path} channel_id {channel_id} not in registry; deleting"
            path.unlink()
            continue
        target = tokens / f"{match}.json"
        if target.exists():
            if path.mtime > target.mtime:
                atomic_replace(path → target)
            else:
                path.unlink()
        else:
            atomic_replace(path → target)
        log "migrated legacy {path} → {target}"
    cache_file.unlink(missing_ok=True)
release flock
```

### `recover_channel_id(creds)`

Legacy `token.json` does NOT persist `channel_id`. Recovery:

1. Check cache file `~/.config/tube-scout/.legacy_token_channel_id_cache.json`.
2. If cached for the legacy file's mtime, return cached value.
3. Else: build a one-shot Data API client with the legacy creds and call
   `youtube.channels.list(mine=True)`. Take `items[0].id`.
4. Persist `(legacy_path, mtime, channel_id)` to the cache file.

If the API call itself fails (revoked, network), return `None` → triggers
the "deleting" branch.

---

## Outputs

| Path | After migration |
|---|---|
| `~/.config/tube-scout/token.json` | Removed |
| `~/.config/tube-scout/token_forcessl.json` | Removed |
| `~/.config/tube-scout/.legacy_token_channel_id_cache.json` | Removed |
| `~/.config/tube-scout/tokens/<alias>.json` | Possibly created or rotated |

---

## Operator-visible output

The CLI prints **one** line per legacy file processed, dimmed:

```text
[dim]Migrated legacy token.json → tokens/nursing.json (matched channel_id UCnh...).[/dim]
[dim]Removed legacy token_forcessl.json (channel_id UCnh... not in registry; run 'tube-scout auth --channel <name>' to register).[/dim]
```

Quiet on no-op (most operators after first migration).

---

## Failure modes

| Failure | Behavior |
|---|---|
| `flock` cannot acquire (another process holds it) | Wait up to 10s; if still held, fail fast with guidance to retry |
| Filesystem read-only | Fail fast: tube-scout cannot operate without writable `~/.config/` |
| Legacy file unreadable (permission) | Fail fast: do not silently skip |
| `recover_channel_id` API call fails | Treat as "channel_id not recoverable" → delete legacy file with warning |
| Atomic rename fails (cross-device) | Fail fast: should not happen in same `~/.config/tube-scout/` directory; if observed, fail with a clear message |

No silent-skip path. All failures raise `UserFacingError` with `next_command`
where applicable.

---

## Idempotency

- After a successful migration, both legacy paths no longer exist.
- The next process invocation's "if not path.exists(): continue" branch
  fires for each legacy path.
- The cache file is removed at end of successful migration; if migration
  was partial (one file processed, second file errored), cache may persist
  and is read by next run.

---

## Test contract

| Scenario | Test type | Location |
|---|---|---|
| Legacy `token.json` matches existing alias, newer mtime | integration | `tests/integration/test_legacy_token_migration.py` |
| Legacy `token.json` matches existing alias, older mtime | integration | same |
| Legacy `token.json` matches no alias | integration | same |
| Legacy `token.json` is corrupt JSON | integration | same |
| Legacy `token.json` missing entirely | integration | same |
| Both `token.json` and `token_forcessl.json` present | integration | same |
| Concurrent processes race on flock | contract | `tests/contract/test_auth_migration.py` |
| `recover_channel_id` API call returns None | contract | same |

---

## Invariants

- Migration runs at most once per process.
- After successful run, legacy paths NEVER reappear (no code re-creates them).
- File modes preserved: target token always 0600 atomic.
- No mixing of "legacy" and "multi-channel" code paths after migration —
  every command from preflight onward uses `authenticate_channel(alias)` only.
