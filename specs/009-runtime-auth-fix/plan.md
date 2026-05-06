# Implementation Plan: Runtime Integration & Multi-Channel Auth Fix

**Branch**: `009-runtime-auth-fix` | **Date**: 2026-05-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/009-runtime-auth-fix/spec.md`

## Summary

Spec 009 closes the runtime-side integration gap left by idea6 (Phase 4 closed
2026-04-30). idea6 fixed the static layer (paths / scopes / silent-skip / atomic
commit_latest at the ProjectManager level). idea7 / spec 009 fixes the runtime
layer where commands actually invoke that machinery: `--project` default, the
producer-side wiring of `commit_latest`, multi-channel auth routing for
retention / analytics, OAuth flow robustness on multi-account browsers, and
transcript audit metadata.

**Primary deliverable**: an operator can run `auth → collect videos → collect
transcripts → collect retention → content scan → report bundle` end-to-end
against one registered channel using only the alias as a flag — no
`--project`, no manual symlink fix, no token-file deletion, no browser
redirect lottery.

**Technical approach**:

1. Change `resolve_project(project=None)` semantics to "open existing latest
   unless the caller is in the explicit producer set". Producer set is one
   constant exported from `cli/project.py`. This is a single-line semantic
   change with broad blast radius — TDD coverage in tasks.md.
2. Add `commit_latest()` invocation to the explicit producer commands
   (`collect videos` is the only producer today; enumeration is future-proof
   for new producers like content fingerprint if desired).
3. Replace every `authenticate()` call site outside `services/auth.py` with
   `authenticate_channel(alias)`. Add `--channel` to retention/analytics/bulk.
   Implement single-alias auto-select and multi-alias refusal in a shared
   helper.
4. Add `services/auth_migration.py` that runs once per process to migrate or
   delete legacy `token.json` / `token_forcessl.json`. Idempotent on
   subsequent runs.
5. Add `services/auth_device_flow.py` implementing OAuth 2.0 Device
   Authorization Grant (RFC 8628) against Google's device code endpoints,
   bypassing `flow.run_local_server`. Make it the default; expose
   `--browser-redirect` to opt back into local-server flow.
6. Add `source` field to transcript JSON; replace verbose 1st-step exception
   logging with a one-line dim notice when fallback succeeds; emit
   `transcripts_audit.csv` per channel listing every miss with classification.

## Technical Context

**Language/Version**: Python 3.11 (pinned via flake.nix devShell + pyproject.toml).
**Primary Dependencies**: typer, rich, google-api-python-client,
google-auth, google-auth-oauthlib, pydantic v2, httpx (already transitive
via google-api-python-client; introduced as direct dep for device flow
endpoints), polars, pandas (only for audit CSV via existing helpers).
**Storage**: JSON (atomic write) under `~/.config/tube-scout/tokens/` for
per-alias OAuth credentials; `~/.config/tube-scout/tokens/channels.json` for
the alias registry; `projects/{job-id}/01_collect/.../transcripts/*.json`
plus a sibling `transcripts_audit.csv` per channel. No new schema layers.
**Testing**: pytest (existing); contract tests for the device flow against
recorded fixtures; integration tests that exercise the project resolution
default change against the existing `projects/` fixture set.
**Target Platform**: Linux (NixOS via `flake.nix devShell`), POSIX semantics.
Headless / SSH / systemd contexts are first-class — no command may block on
TCP listen.
**Project Type**: cli (single project; the existing `src/tube_scout/` layout).
**Performance Goals**: device-code OAuth completes in ≤2 minutes wall-clock
(SC-002). `resolve_project(project=None)` resolves in <50ms (filesystem
stat on `projects/latest` symlink). Migration of legacy `token.json` runs
once per upgrade in <100ms.
**Constraints**: must preserve every idea6 invariant (atomic
commit_latest, secret_loader behavior, scope verifier, silent-skip lint
guard, headless TTY guard). Files written to `~/.config/tube-scout/`
must be 0600 atomic. No new agenix variable required (reuses existing
`TUBE_SCOUT_CLIENT_SECRET` / `_B64` per idea6 D-4 fix).
**Scale/Scope**: ~1–10 channels per operator; ~200–500 videos per channel;
1–3 operators total in the current deployment (RISE / DX지원센터). Audit
CSV per channel ≤500 rows.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution version at plan time: **1.1.0** (Principles I–VII).

| # | Principle | Application | Status |
|---|---|---|---|
| I | Test-First (NON-NEGOTIABLE) | Every change in tasks.md follows RED→GREEN→REFACTOR. Project-resolution default change is a behavior switch with broad blast radius — RED tests must cover both "default → latest" and "explicit `--project` unchanged" before any source edit. | PASS |
| II | Fail-Fast & Anti-Hallucination | Spec FR-018 explicitly forbids silent skip. New auth migration MUST fail-fast when a legacy token's channel_id is unreadable. New device flow MUST fail-fast on timeout (FR-013). All new error messages route through the existing user-facing error pattern (FR-017). | PASS |
| III | Type Safety + Single Responsibility | All new functions in `auth_device_flow.py` and `auth_migration.py` carry full type annotations and Google-style docstrings. Migration logic and device flow live in dedicated modules — no leakage into existing `cli/collect.py`. | PASS |
| IV | CLI-First | Every change is to the CLI surface or its underlying services. No new web/HTTP surface introduced. Web UI (spec 008) inherits the fix transparently via the same service layer (no parallel implementation). | PASS |
| V | Local-First | No new external store. Transcript audit CSV stays under `projects/{job-id}/01_collect/transcripts/`. Token migration stays under `~/.config/tube-scout/`. | PASS |
| VI | Secrets via agenix (NON-NEGOTIABLE) | Legacy `token.json` migration touches only operator-side runtime artifacts (already 0600, never committed). Agenix-managed `TUBE_SCOUT_CLIENT_SECRET[_B64]` is unchanged. Device flow does not introduce new secret types. | PASS |
| VII | Cross-Spec Boundary Discipline (NON-NEGOTIABLE) | See enumeration below — every shared boundary is named and contracted. | PASS (enumerated) |

### Cross-Spec Boundaries (Principle VII)

| Boundary | Prior side (guarantee) | This spec (assumes / produces) | Test |
|---|---|---|---|
| `ProjectManager.commit_latest` (idea6 ADR-006) | Atomic symlink update; empty-project guard | This spec WIRES the call into `collect videos`. Other producers (none today, but enumerated constant) follow the same wiring. | Integration test: collect videos → assert `projects/latest` resolves to the new project; partial failure → assert `latest` unchanged. |
| `tokens/<alias>.json` + `channels.json` (idea6 D-5) | 0600 atomic; alias-keyed; carries channel_id and scopes | This spec ROUTES every auth-using command through `authenticate_channel(alias)`. | Integration test: `collect retention --channel <alias>` reads `tokens/<alias>.json`, never `token.json`. |
| `secret_loader` (idea6 D-4 / FR-IDEA6-004) | Reads `TUBE_SCOUT_CLIENT_SECRET` (path) or `_B64` (base64) | Unchanged consumer. Device flow uses the same client-secret material. | No new test (covered by idea6). |
| `_verify_scopes` (idea6 D-8 / FR-IDEA6-005) | Raises `ScopeReauthRequired` when stored token lacks REQUIRED_SCOPES | Migration MUST run scope verification on legacy `token.json` before adopting it; if scope-deficient, treat as "must re-auth via device flow". | Contract test: legacy token with single scope → migration triggers re-auth path, not silent adoption. |
| `UserFacingError` + `render_error` (idea6 ADR-007) | Cause + suggested-next-command pattern | This spec ADDS error cases: `LegacyTokenChannelMismatch`, `MultipleAliasesNoSelection`, `DeviceCodeTimeout`. All include a `next_command`. | Snapshot test on each new error message. |
| Silent-skip lint guard (idea6 FR-IDEA6-010 / ADR-007+ADR-003) | AST-walk lint forbids `except SystemExit: pass` and similar | This spec MUST NOT add any silent-skip path. Migration of legacy token, missing alias, device-flow timeout — all fail with non-zero exit. | Existing lint runs on new code; no new lint config. |
| Headless TTY guard (idea6 NFR-IDEA6-003 / B7) | `_require_tty` raises `InteractiveAuthRequired` when no TTY | Device flow MUST integrate: even with `--browser-redirect`, headless context falls through to device flow (or refuses with same exception class if device flow also requires TTY for code entry). | Test: simulate non-TTY → device flow surfaces actionable error, no port listen. |
| `tests/manual/` exclusion (idea6 D-9 / FR-IDEA6-009) | `tests/manual/` excluded from default suite | Real-OAuth-against-Google tests stay in `tests/manual/`. Device flow CI tests use recorded fixtures or local fakes. | No regression: default `pytest` run remains green. |
| `_collect_all_for_web` (spec 008 T035-bis) | Web UI imports `cli/collect.py` internals to drive the pipeline | Spec 009's `--project` default change AUTOMATICALLY benefits web UI; no parallel changes needed. Web UI must continue to pass `--project <explicit>` to be deterministic. | Integration test: web UI pipeline run still produces a coherent project after spec 009 change. |
| Content reuse detection (spec 007) | Reads `videos_meta.json` + transcripts under the project | Spec 009 transcript JSON gains `source` field — must remain backward-compatible (additive only). Audit CSV is sibling, not consumed by spec 007. | Backward-compat test: existing transcript JSON without `source` still parses for content scan. |
| YouTube Captions API + youtube-transcript-api (idea6 D-8) | Captions API requires force-ssl scope; library is best-effort | Spec 009 polishes the verbose 1st-step exception output and adds source attribution. No semantic change to capture logic. | Snapshot test: terminal output for a private video shows ≤2 lines for fallback-succeeded path. |
| `~/.config/tube-scout/` directory layout | XDG-compliant, 0600 files | Migration MUST NOT relax permissions. After migration, deprecated `token.json` / `token_forcessl.json` no longer reappear on subsequent runs. | Contract test: post-migration filesystem state. |
| Agenix env vars `TUBE_SCOUT_CLIENT_SECRET[_B64]` | Provided via `flake.nix` devShell injection | Consumed unchanged. No new env var introduced by this spec. | No new test (covered by idea6). |

**Initial gate result**: PASS. No principle violations to justify in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/009-runtime-auth-fix/
├── plan.md                # This file
├── research.md            # Phase 0 output
├── data-model.md          # Phase 1 output
├── quickstart.md          # Phase 1 output
├── contracts/             # Phase 1 output
│   ├── cli_collect.md     # CLI command shapes (collect group, post-fix)
│   ├── auth_flow.md       # OAuth device flow + browser-redirect contract
│   └── token_migration.md # Legacy token migration contract
├── checklists/
│   └── requirements.md    # Already created during /speckit.specify
└── tasks.md               # Phase 2 output (NOT created here)
```

### Source Code (repository root)

Single-project layout (Option 1) — extends the existing `src/tube_scout/`
package without adding new top-level modules.

```text
src/tube_scout/
├── cli/
│   ├── project.py             # CHANGED: resolve_project default → 'latest'
│   │                          #   for non-producer commands; producer set
│   │                          #   exported as constant.
│   ├── collect.py             # CHANGED: collect videos calls commit_latest;
│   │                          #   retention/analytics/bulk gain --channel;
│   │                          #   transcript output adds `source` field;
│   │                          #   verbose 1st-step exception suppressed.
│   ├── auth_cli.py            # CHANGED: --browser-redirect flag added.
│   └── errors.py              # CHANGED: new UserFacingError subclasses.
├── services/
│   ├── auth.py                # CHANGED: every external call site routes
│   │                          #   through authenticate_channel; legacy
│   │                          #   authenticate() retained only as private
│   │                          #   shim used by migration.
│   ├── auth_migration.py      # NEW: one-shot migration of legacy
│   │                          #   token.json / token_forcessl.json into
│   │                          #   tokens/<alias>.json, idempotent.
│   ├── auth_device_flow.py    # NEW: RFC 8628 device authorization grant
│   │                          #   against Google's endpoints. Default
│   │                          #   OAuth flow.
│   ├── transcript.py          # CHANGED: persists `source` field; emits
│   │                          #   audit row per missed video.
│   └── transcripts_audit.py   # NEW: classification + CSV emitter.
└── models/
    └── (no schema changes)

tests/
├── contract/
│   ├── test_auth_device_flow.py     # NEW
│   ├── test_auth_migration.py       # NEW
│   └── test_resolve_project.py      # NEW (default-change behavior)
├── integration/
│   ├── test_collect_chain.py        # NEW (videos → transcripts → retention)
│   ├── test_legacy_token_migration.py # NEW
│   └── test_transcript_audit.py     # NEW
├── unit/
│   ├── test_resolve_project_unit.py # NEW
│   └── test_transcripts_audit_classify.py # NEW
└── manual/
    └── test_real_oauth_device_flow.py # NEW (excluded from default suite)
```

**Structure Decision**: Option 1 (single project). The change is entirely
within `src/tube_scout/cli/` and `src/tube_scout/services/`. New modules
`auth_migration.py`, `auth_device_flow.py`, `transcripts_audit.py` are
service-layer additions; no new top-level package.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| (none) | (Constitution Check passed without justification.) | — |
