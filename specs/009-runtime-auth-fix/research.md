# Phase 0 Research: Runtime Integration & Multi-Channel Auth Fix

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)
**Date**: 2026-05-07

This document resolves the technical unknowns identified in the plan's
Technical Context section. There are no `[NEEDS CLARIFICATION]` markers
because spec 009 entered with DEC-1/DEC-2/DEC-3 already resolved at
idea7-document time. The research items below are *implementation-path*
decisions, not scope ambiguities.

---

## R1. OAuth 2.0 Device Authorization Grant (RFC 8628) on Google's endpoints

**Decision**: Implement the device authorization grant flow directly against
Google's public OAuth endpoints, calling them from `services/auth_device_flow.py`
with `httpx`. Do not depend on `google-auth-oauthlib`'s `Flow.run_local_server`
for the default path.

**Endpoints**:

- Device code request: `POST https://oauth2.googleapis.com/device/code`
- Token poll: `POST https://oauth2.googleapis.com/token` with
  `grant_type=urn:ietf:params:oauth:grant-type:device_code`
- Refresh: `POST https://oauth2.googleapis.com/token` with
  `grant_type=refresh_token` (handled by existing `google.oauth2.credentials.Credentials.refresh()`)

**Flow**:

1. POST `client_id` + `scope` (space-joined) to `/device/code`. Receive
   `device_code`, `user_code`, `verification_url`, `expires_in`, `interval`.
2. Print `verification_url` and `user_code` to terminal via `rich`.
3. Poll `/token` every `interval` seconds with the `device_code`. Handle
   `authorization_pending` (continue polling), `slow_down` (increase
   interval), `expired_token` (timeout — fail fast with actionable error),
   `access_denied` (operator pressed deny — fail), and success (consume
   `access_token` + `refresh_token`).
4. Wrap the resulting credentials in `google.oauth2.credentials.Credentials`
   for compatibility with the existing `_authorized_http` transport.

**Rationale**: `google-auth-oauthlib`'s `InstalledAppFlow` only exposes
`run_local_server` (loopback redirect) and `fetch_token(code=...)` (manual
code paste, requires the deprecated OOB redirect URI). Neither addresses the
multi-account browser hang seen in D-17. RFC 8628 is the modern replacement,
supported by Google for "Limited Input Device" client types, and works
identically across desktop/SSH/CI without TCP listen.

**Alternatives considered**:

- **Manual code paste via `Flow.fetch_token(code=...)`**: requires Google's
  deprecated `urn:ietf:wg:oauth:2.0:oob` redirect or scraping the auth code
  from the browser's `localhost` page. Fragile and Google has actively
  removed OOB support.
- **`run_local_server(open_browser=False)` + manual URL paste**: still binds
  port 8080. D-17 is exactly this hang.
- **External `gcloud auth` shelling out**: introduces a new dependency the
  operator may not have; also not channel-bound.

**Client-type prerequisite**: Google Cloud Console OAuth client must be type
"Desktop" or "Limited Input Device" (TV / IoT). Today's tube-scout client is
already "Desktop" (works with both `run_local_server` and device code). No
GCP-side change required from the operator.

**Failure modes addressed**:

- D-17 (multi-account browser redirect hang): no localhost redirect → no hang.
- Headless / SSH / systemd: works identically (no `_require_tty` block needed
  for the polling itself; only the initial code display needs stdout).
- Brave / Chrome with redirect interception: bypassed.

**Test strategy**:

- Contract test `tests/contract/test_auth_device_flow.py` with `httpx_mock`
  recording fixtures for the four polling states (pending / slow_down / expired
  / success) plus access_denied.
- Manual test in `tests/manual/test_real_oauth_device_flow.py` (excluded by
  idea6 D-9 default-suite exclusion) for end-to-end verification on the
  operator's machine.

---

## R2. Atomic legacy-token migration on POSIX

**Decision**: Use `Path.replace()` (which delegates to `os.rename`) for the
legacy-token migration. POSIX `rename(2)` is atomic on the same filesystem;
both source and destination live under `~/.config/tube-scout/` so this
holds. For the in-place delete branch, use `Path.unlink(missing_ok=False)`
followed by an immediate fsync of the parent directory to commit the unlink.

**Algorithm** (one-shot per process; gated by a module-level flag):

1. Acquire a `fcntl.flock` advisory lock on
   `~/.config/tube-scout/.migration.lock` to serialize across concurrent
   tube-scout invocations.
2. For each of `token.json`, `token_forcessl.json`:
   - If the file does not exist → no-op.
   - Else read it as `Credentials.from_authorized_user_file`. If parse
     fails → log a one-line warning and unlink (corrupt legacy state).
   - Read the embedded `client_id` + `quota_project_id` and call
     `youtube.channels.list(mine=True)` once with the token to recover the
     bound `channel_id`. (Required because legacy `token.json` does not
     persist `channel_id` directly.) Cache the result in a side file
     `~/.config/tube-scout/.legacy_token_channel_id_cache.json` so
     subsequent process invocations don't re-call.
   - Look up the channels registry (`tokens/channels.json`) for an alias
     whose `channel_id` matches.
   - **Match**: If `tokens/<alias>.json` exists, compare mtime. Newer
     wins. If legacy is newer, atomically `replace()` it into
     `tokens/<alias>.json` (overwriting). If existing is newer, `unlink()`
     the legacy file. Either way, end state is "single canonical token at
     `tokens/<alias>.json`".
   - **No match**: `unlink()` the legacy file and emit a one-line notice
     instructing `tube-scout auth --channel <name>`.
3. Release the lock.

**Idempotency**: After successful migration, both legacy paths no longer
exist, so the next invocation's "if file does not exist → no-op" branch
fires. The cache file is also removed at the end of a successful migration.

**Rationale**: `os.rename` is the canonical POSIX atomic-replace primitive;
already used by idea6 ADR-006's `commit_latest`. fcntl.flock is the standard
way to serialize across concurrent CLI invocations and is already used by
some Python projects in the same niche (e.g., pip's lock).

**Alternatives considered**:

- **Hardlink + unlink**: same atomicity guarantee but more error-prone if
  destination already exists.
- **Copy then unlink**: not atomic; a crash mid-copy leaves both copies on
  disk.
- **No locking, accept races**: two concurrent `tube-scout` processes could
  both decide to migrate and clobber each other. Cheap to lock.

**Edge cases**:

- Token file exists but is corrupt JSON → unlink with warning (legacy is
  ambiguous; best to require fresh OAuth).
- Token file refresh fails (revoked) → unlink with warning + guidance to
  re-auth.
- Filesystem is read-only → fail fast with actionable error (filesystem
  must be writable; tube-scout cannot run with read-only `~/.config/`).

---

## R3. `resolve_project(project=None)` default-change blast radius

**Decision**: Change the default semantics to "open existing latest unless
the caller is in the explicit producer set". Producer set is defined as a
constant `PRODUCER_COMMANDS = {"collect.videos"}` exported from
`cli/project.py`. Each command identifies itself via a `producer: bool = False`
parameter when calling `resolve_project`.

**Affected commands** (verified against `src/tube_scout/cli/`):

| Command | Producer? | New default behavior |
|---|---|---|
| `collect videos` | YES | Creates new project, calls `commit_latest()` on success |
| `collect transcripts` | no | Opens latest; fail-fast if no latest |
| `collect retention` | no | Opens latest; fail-fast if no latest |
| `collect comments` | no | Opens latest; fail-fast if no latest |
| `collect analytics` | no | Opens latest; fail-fast if no latest |
| `collect bulk` | no | Opens latest; fail-fast if no latest |
| `collect all` | YES (delegates to collect videos as the producer) | Inherits from delegated step |
| `analyze *` | no | Opens latest |
| `content fingerprint/compare/quality/review/scan` | no | Opens latest |
| `report *` | no | Opens latest |
| `validate` | no | Opens latest |
| `search` | no | Opens latest |
| `status` | no | Opens latest (read-only) |
| `list` | no | Opens latest (read-only) |

Explicit `--project latest` and `--project <path>` are unchanged
(non-producer commands explicitly passing `latest` is now a no-op vs default;
producers explicitly passing `latest` open it instead of creating new).

**Rationale**: A small, enumerated producer set is reviewable in a single
glance and survives future spec additions (e.g., "content fingerprint
becomes a producer if it stages a new project type" — would be added to the
constant). The alternative — every command declaring `producer: bool` at
its CLI call site — works but is harder to audit for completeness.

**Alternatives considered**:

- **Detect producer at runtime by code path**: brittle; couples runtime
  behavior to import patterns.
- **Keep `project=None` semantics, force every command to pass
  `--project latest`**: spec 009 SC-001 explicitly forbids this UX.
- **A separate `--new-project` flag for producers, `project=None` always
  means latest**: clean but breaks today's operator habit of running
  `collect videos` without flags. Marginal gain.

**Backward compatibility**:

- `--project latest` → unchanged
- `--project <explicit>` → unchanged
- `--project=` (omitted) on a producer → now creates new + commits latest
  (was: created new but did not commit)
- `--project=` (omitted) on a non-producer → now opens latest (was:
  created new empty project, the D-13 failure mode)

The only place where the old behavior is needed is "I want to make a fresh
empty consumer project for some reason". This is not a documented use case
and is reachable via explicit `--project <new-path>` if anyone ever wants it.

---

## R4. Multi-channel resolution helper (single-auto, multi-refuse)

**Decision**: Add `resolve_channel_alias(explicit: str | None) -> str` to
`services/auth.py`. Behavior matches FR-006:

1. `explicit` is not None → return `explicit` after verifying it exists in
   the registry; raise `UserFacingError` with `next_command` if not.
2. `explicit` is None and registry has 0 entries → raise `UserFacingError`
   with `next_command = "tube-scout auth --channel <name>"`.
3. `explicit` is None and registry has 1 entry → return that alias; emit
   a one-line dim notice via `rich` (`Using channel: <alias> (only
   registered alias)`).
4. `explicit` is None and registry has ≥2 entries → raise `UserFacingError`
   with `next_command` listing each alias with its `channel_id` and
   `last_used` and one corrected example command.

**Rationale**: Centralizing this logic prevents drift across collect
subcommands. Every CLI command that needs a channel calls this helper at
its entry point. Makes the behavior testable in isolation.

**Test strategy**: Unit test in `tests/unit/test_resolve_channel_alias.py`
covers all four branches with a fake registry fixture.

---

## R5. Transcript miss classification

**Decision**: Map `(primary_error_class, fallback_error_class, video_meta)`
to one of these classifications, in priority order:

| Classification | When | Hint |
|---|---|---|
| `private_no_owner_access` | primary raised "private" AND fallback got `403` | Re-auth with channel owner account; or skip if not owned |
| `asr_not_generated` | primary raised "no transcript" AND fallback got `404` AND video duration < 4h | Wait for YouTube ASR; or upload manual captions |
| `unsupported_long_video` | primary raised "no transcript" AND duration ≥ 4h | YouTube does not generate ASR for very long videos |
| `library_bug` | primary raised an unexpected exception class AND fallback succeeded | Suppress; the data was retrieved |
| `rate_limited` | primary raised "TooManyRequests" OR fallback raised `429` | Retry later; check quota |
| `quota_exhausted` | fallback raised `quotaExceeded` | Wait for quota reset (per-day) |
| `member_only` | video_meta indicates members-only | Cannot retrieve programmatically |
| `deleted_or_unavailable` | both raised `404` AND not private | Video may have been removed |
| `unknown` | none of the above | Inspect terminal log for this `video_id` |

Each row of `transcripts_audit.csv` carries `(video_id, video_title,
primary_error_class, fallback_error_class, classification, hint)`.

**Rationale**: The classification axes match the failure modes already
distinguishable at runtime by the existing exception types from
`youtube_transcript_api` and `googleapiclient.errors.HttpError`. The hint
column is operator-actionable and short.

**Alternatives considered**:

- **No classification, just dump exception class strings**: forces operator
  to learn library internals; defeats the purpose of an audit.
- **Machine-learning classifier on the exception text**: overkill; rule
  table covers all known cases.

**Test strategy**: Unit test
`tests/unit/test_transcripts_audit_classify.py` enumerates each rule with
a synthetic `(primary, fallback, meta)` triple.

---

## R6. Verbose-stack-trace suppression for fallback-succeeded path

**Decision**: When `collect transcripts` runs the primary library and gets
an exception, it captures the exception class + first-line message but
does **not** print the full traceback at the time of failure. After the
fallback succeeds for that video, output is a single dim line:

`  <video_id>: <segments> segments (captions_api, primary skipped: <ExceptionClass>)`

When the fallback ALSO fails, the full primary exception traceback IS
printed (since both paths failed and the operator needs the detail).

**Rationale**: Today's verbose multi-line "This video is private" message
per video drowns the per-video success line. The information is still
recoverable in the audit CSV (`primary_error_class`).

**Alternatives considered**:

- **Suppress unconditionally**: loses information when both paths fail.
- **Aggregate at end of run**: harder to correlate to the live progress.
- **Verbosity level flag**: would require a new `--verbose` flag; out of
  scope for this fix.

**Test strategy**: Snapshot test on captured stdout for a small fixture
of three videos: one public (manual), one private with successful fallback,
one private with both paths failing.

---

## R7. Producer-side `commit_latest` wiring atomicity

**Decision**: `collect videos` calls `mgr.commit_latest()` exactly once,
at the end of its successful execution path (after every video is written
and parquet is flushed). On any exception during collection, `commit_latest`
is NOT called and the new project remains a non-`latest` directory until
manually recovered or a successful re-run promotes a different project.

**Rationale**: The atomic guarantee is "latest always points to a fully-
populated project". Crash mid-collection leaves an orphan project but does
not corrupt the symlink. Idea6 ADR-006's `commit_latest` already enforces
the "non-empty project" guard, so even calling it accidentally on an empty
project would be a no-op.

**Alternatives considered**:

- **Commit incrementally per video**: would mean `latest` advances mid-run;
  consumers see partial data; SC-001 would not hold.
- **Commit at the start, before any data is written**: D-3 today's failure
  mode.

**Test strategy**: Integration test
`tests/integration/test_collect_chain.py` includes a "collect videos crashes
mid-run" scenario asserting `latest` did not advance.

---

## R8. Test fixture for `projects/` directory

**Decision**: Add a pytest fixture `tmp_projects_root` (in
`tests/conftest.py`) that creates a `tmp_path / "projects"` directory and
returns it. Tests for project resolution, commit_latest, and the producer
set use this fixture instead of the live `projects/`. Existing tests that
rely on the live `projects/` already use isolation; no global change.

**Rationale**: Keeps each test reproducible, avoids polluting the repo's
real `projects/` directory.

**Test strategy**: Existing project-related tests already use `tmp_path`;
this fixture standardizes the pattern.

---

## R9. Open Items (none)

All Phase 0 unknowns are resolved. Proceeding to Phase 1.
