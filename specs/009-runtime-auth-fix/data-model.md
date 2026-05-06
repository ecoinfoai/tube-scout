# Phase 1 Data Model: Runtime Integration & Multi-Channel Auth Fix

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)
**Date**: 2026-05-07

This spec is mostly behavioral (auth flow, project resolution defaults, error
surfacing) and adds only minimal new persistent state. The entities below
list every persisted artifact this feature creates, mutates, or migrates.

---

## E1. Channel Token File — `~/.config/tube-scout/tokens/<alias>.json`

**Origin**: idea6 D-5 / FR-IDEA6-001 (alias-aware ProjectManager and per-alias tokens).

**Mutated by this spec**: yes (consolidation target — all auth-using
commands now read/write through this path).

**Schema** (Google OAuth `Credentials.to_json()` format, unchanged):

```json
{
  "token": "<access token>",
  "refresh_token": "<refresh token>",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "<from agenix>",
  "client_secret": "<from agenix>",
  "scopes": [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly"
  ],
  "expiry": "2026-05-07T13:24:00Z"
}
```

**Invariants**:

- File mode: 0600.
- Write semantics: atomic replace via `os.rename` from a sibling temp file.
- `scopes` MUST cover REQUIRED_SCOPES at write time; verified by
  `_verify_scopes` (idea6 FR-IDEA6-005).
- Filename pattern: `<alias>.json` (no `_token` suffix; corrected by
  constitution v1.0.1).

**Lifecycle**:

| Event | Effect |
|---|---|
| `auth --channel <alias>` (device flow path) | Created or rotated by `auth_device_flow.py` |
| `auth --channel <alias> --browser-redirect` | Created or rotated by `flow.run_local_server` |
| `authenticate_channel(alias)` refresh path | Updated in place (token, expiry); 0600 atomic |
| Migration of legacy `token.json` (one-shot) | Created from migrated source |
| `auth --revoke <alias>` | Deleted (idempotent if missing) |

---

## E2. Channels Registry — `~/.config/tube-scout/tokens/channels.json`

**Origin**: idea6 D-5 / multi-channel registration.

**Mutated by this spec**: no (consumed unchanged).

**Schema**:

```json
{
  "<alias>": {
    "alias": "<alias>",
    "channel_id": "UC...",
    "channel_name": "...",
    "registered_at": "2026-05-06T15:00:00+09:00",
    "last_used_at": "2026-05-07T00:11:39+09:00",
    "scopes": [...]
  }
}
```

**Invariants**:

- File mode: 0600.
- Atomic write.
- One entry per alias; `channel_id` is unique across entries.
- `last_used_at` is updated by `authenticate_channel(alias)` on success.

**Lifecycle** (this spec adds no new mutators, only readers):

| Event | Read by |
|---|---|
| Multi-alias `--channel` resolution helper | `services/auth.py:resolve_channel_alias` |
| Legacy token migration (channel_id lookup) | `services/auth_migration.py` |
| `auth --list` | `cli/auth_cli.py` |

---

## E3. Legacy Token Files (deprecated; migrated and deleted)

**Origin**: pre-idea6 single-channel install era.

**Mutated by this spec**: yes (one-shot migrate-or-delete; never re-created).

**Affected paths**:

- `~/.config/tube-scout/token.json`
- `~/.config/tube-scout/token_forcessl.json`

**Migration target schema**: same as E1.

**Migration outcome states**:

| Source state | Outcome |
|---|---|
| File missing | No-op (most operators after first migration) |
| File present, parses, `channel_id` matches a registry entry | Atomically replaced into `tokens/<alias>.json` if newer; else legacy unlinked |
| File present, parses, `channel_id` matches none | Unlinked; operator told to register |
| File present, corrupt JSON | Unlinked with warning |
| File present but unreadable (filesystem error) | Fail fast |

**Cache file** (transient, removed at end of successful migration):

- `~/.config/tube-scout/.legacy_token_channel_id_cache.json`
- Stores the result of the one-time `youtube.channels.list(mine=True)` call
  used to recover the legacy token's bound `channel_id`.

**Invariant**: After a successful migration run, neither legacy file exists,
and no code path re-creates them.

---

## E4. Transcript JSON — `projects/{job-id}/01_collect/transcripts/<video_id>.json`

**Origin**: spec 001 (lecture-video-analytics); refined by idea6.

**Mutated by this spec**: yes (adds `source` field; existing fields
unchanged).

**Schema after this spec** (additive):

```json
{
  "video_id": "abc123",
  "language": "ko",
  "segments": [
    {"start": 0.0, "duration": 3.2, "text": "..."},
    ...
  ],
  "source": "manual" | "auto_generated" | "captions_api"
}
```

**Backward compatibility**: existing JSON files without `source` remain
parseable by content scan (spec 007) and report (spec 003); consumers MUST
treat absent `source` as "unknown" and not fail.

**Invariant**: Any new transcript JSON written by spec 009 code carries
`source`. No legacy transcript is rewritten silently.

---

## E5. Transcript Audit CSV — `projects/{job-id}/01_collect/transcripts_audit.csv`

**Origin**: NEW (spec 009).

**Schema** (CSV with header):

```csv
video_id,video_title,primary_error_class,fallback_error_class,classification,hint
xyz789,"Lecture 5: Microbiology basics",NoTranscriptFound,HttpError404,asr_not_generated,Wait for YouTube ASR or upload manual captions
abc456,"...",VideoUnavailable,HttpError403,private_no_owner_access,Re-auth with channel owner; or skip
```

**Invariants**:

- File mode: 0644 (readable; not a secret).
- One row per video that did NOT produce a transcript in this run.
- Always re-emitted from scratch on each `collect transcripts` run for the
  same project (no incremental append).
- `classification` value is from the controlled vocabulary in
  research.md R5.
- `hint` is a single short sentence, operator-readable.

**Producer**: `services/transcripts_audit.py:write_audit_csv()`.
**Consumer**: future `report bundle` integration (out of scope for spec 009;
documented for forward compatibility).

---

## E6. Project Directory + `latest` Symlink

**Origin**: idea6 ADR-001 / ADR-006.

**Mutated by this spec**: yes (producer commands now invoke `commit_latest`;
non-producer commands no longer accidentally create empty siblings).

**State machine** (single project):

```
created → populated → committed
   |          |
   |          └──▶ partial (orphan; latest does not point here)
   └──▶ empty (orphan; latest never points here per idea6 D-3 guard)
```

**Transitions** (this spec's contribution):

| From | To | Trigger | Code |
|---|---|---|---|
| (none) | created | producer command + `--project=` omitted | `resolve_project(producer=True)` |
| created | populated | data write succeeds | `collect.videos` body |
| populated | committed | producer command success path | `mgr.commit_latest()` (NEW invocation) |
| created | partial | producer command fails after data write started | (no commit; no latest advance) |
| created | empty | producer command fails before any data write | (no commit; idea6 D-3 empty guard prevents pollution) |

---

## E7. Producer Set Constant — `cli/project.py:PRODUCER_COMMANDS`

**Origin**: NEW (spec 009).

**Type**: `frozenset[str]`.

**Default value** (this spec): `frozenset({"collect.videos"})`.

**Schema**: each entry is the canonical CLI command identifier in
dotted form (`<group>.<subcommand>`). The string MUST match what the
calling code passes to `resolve_project(command_id=..., ...)`.

**Invariant**: Adding a command to this set is the ONLY way to grant it
the "default → create new project + commit_latest on success" behavior.
Removing a command from the set does NOT delete its existing projects.

**Test contract**: any new producer added in a future spec MUST extend this
set; absence triggers the consumer-default branch and the new spec hits
D-13 immediately.

---

## E8. Error Classes — `cli/errors.py` additions

**Origin**: extends idea6 ADR-007 / `UserFacingError`.

**New subclasses**:

| Class | `next_command` |
|---|---|
| `LegacyTokenChannelMismatch` | `tube-scout auth --channel <name>` |
| `LegacyTokenCorrupt` | `tube-scout auth --channel <existing-alias>` |
| `MultipleAliasesNoSelection` | `tube-scout <command> --channel <one-of-listed-aliases>` |
| `NoAliasRegistered` | `tube-scout auth --channel <name>` |
| `DeviceCodeTimeout` | `tube-scout auth --channel <alias>` (retry) |
| `DeviceCodeAccessDenied` | `tube-scout auth --channel <alias>` (retry) |
| `LatestProjectMissing` | `tube-scout collect videos --channel <alias>` |
| `ProducerCommandRequiresChannel` | `tube-scout collect videos --channel <alias>` |

**Invariant**: every new error class carries `message` (English, no secret
leakage per Principle II) and `next_command` (operator-actionable
correction, FR-017).

---

## Summary

| Entity | Status | Persistence |
|---|---|---|
| E1 Channel Token | mutated (consolidation target) | Filesystem (per-user) |
| E2 Channels Registry | consumed unchanged | Filesystem (per-user) |
| E3 Legacy Token Files | migrated + deleted (one-shot) | Filesystem (per-user) — going away |
| E4 Transcript JSON | additive `source` field | Filesystem (per-project) |
| E5 Transcripts Audit CSV | NEW | Filesystem (per-project) |
| E6 Project + `latest` symlink | mutated (commit wiring) | Filesystem (project root) |
| E7 PRODUCER_COMMANDS constant | NEW | In-code constant |
| E8 Error Classes | NEW (extends idea6) | In-code |

No new database, schema, or shared state introduced. Principle V (local-first)
and Principle VI (agenix-only secrets) preserved.
