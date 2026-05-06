# Feature Specification: Runtime Integration & Multi-Channel Auth Fix

**Feature Branch**: `009-runtime-auth-fix`
**Created**: 2026-05-07
**Status**: Draft
**Input**: User description: "Tube Scout v7 — Runtime Integration & Multi-Channel Auth Fix. Source: `idea/idea7-runtime-integration-fix.md`. Captures defects D-13~D-17 + L-1~L-3 discovered during the first end-to-end real-data run on 2026-05-07 (one week after idea6 Phase 4 closure). idea6 fixed static boundaries (paths, scopes, silent-skip); idea7 fixes runtime boundaries (project resolution defaults, multi-channel token routing, OAuth callback robustness, transcript metadata)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Multi-channel-aware data collection that does not get blocked at auth (Priority: P1)

A department operator (e.g. RISE 사업단 / DX지원센터) has registered one or more YouTube channel aliases with `auth --channel <alias>` and now wants to run the full data-collection chain (videos → transcripts → retention → comments → analytics) on one of those channels without the tool re-prompting for OAuth, hanging on a redirect callback, or rejecting refresh because of a legacy token.

Today this fails: `collect retention` reaches for a stale single-channel default token, requests scopes the original consent never covered, and Google rejects with `invalid_scope`. The operator has no path forward except deleting the legacy token and going through OAuth again — and that OAuth attempt itself hangs in a multi-account browser environment with no recovery.

**Why this priority**: This is the only critical-blocker user story. Every downstream pipeline stage (content reuse detection, PDF bundle, web UI) depends on retention/analytics succeeding. Until P1 is fixed, no operator can complete an end-to-end run.

**Independent Test**: On a machine with a registered channel alias whose `tokens/<alias>.json` covers all required scopes, run `collect retention --channel <alias>` and `collect analytics --channel <alias>` (each with `--project latest`). Both must succeed without prompting for re-auth, without falling back to a legacy `token.json`, and without the OAuth callback hanging.

**Acceptance Scenarios**:

1. **Given** an operator has one alias `nursing` registered (with both required scopes) and a stale legacy `token.json` from a prior single-channel-era install, **When** they run `collect retention --channel nursing --project latest`, **Then** the command routes auth through `tokens/nursing.json`, ignores `token.json`, and successfully calls the YouTube Analytics API.
2. **Given** an operator runs `auth --channel <alias>` for the first time on a multi-account browser environment, **When** OAuth begins, **Then** the tool prints a verification URL and a device code to the terminal (the operator does NOT need a browser redirect to complete consent).
3. **Given** an OAuth attempt is in progress and the operator is unable to complete it within a bounded time, **When** the timeout elapses, **Then** the tool fails fast with an actionable error (no silent hang, no orphaned listener on a TCP port).
4. **Given** a legacy `token.json` exists at the user config directory and its embedded `channel_id` matches an alias in the channels registry, **When** any auth-using command runs for the first time after upgrade, **Then** the legacy file is migrated to `tokens/<alias>.json` (newer mtime wins) and is no longer consulted on subsequent runs.
5. **Given** a legacy `token.json` exists but its embedded `channel_id` does not match any registered alias, **When** any auth-using command runs, **Then** the legacy file is removed and the operator is told to run `auth --channel <name>` to register the channel.

---

### User Story 2 — Sequential collection without manual project plumbing (Priority: P1)

The same operator wants to run a sequence like `collect videos → collect transcripts → collect retention → content scan → report bundle` and have each step automatically use the data the previous step produced. Today, omitting `--project` causes every step except `collect videos` to create a fresh empty project and report "No videos found", and `projects/latest` is not auto-updated by the producer step, so the operator has to manually `ln -sfn` between commands.

**Why this priority**: This is also a P1 because it is hit by every operator on the very first chained command, even before they reach the auth blocker in Story 1. Without P2, the auth fix in P1 is not reachable in a normal workflow.

**Independent Test**: Starting from a clean `projects/` directory, run `collect videos --channel <alias>`, then `collect transcripts --channel <alias>`, **with no `--project` flag on either command**. The transcripts step must find the videos collected by step 1 and produce transcript JSON files. No empty sibling project directories may be created during the sequence.

**Acceptance Scenarios**:

1. **Given** the operator runs `collect videos --channel <alias>` and the command succeeds, **When** the command completes, **Then** `projects/latest` resolves to the project directory that just received the videos data — automatically, with no manual symlink edit.
2. **Given** the operator immediately runs `collect transcripts --channel <alias>` (no `--project` flag), **When** the command starts, **Then** it operates on the same project as the previous `collect videos`, finds the videos, and proceeds to fetch transcripts.
3. **Given** the operator re-runs `collect transcripts --channel <alias>` (no `--project` flag) without first running `collect videos`, **When** the command starts, **Then** it does not create a new empty project; instead it operates on the most recent project that already contains video data (or fails fast with guidance if none exists).
4. **Given** an operator passes `--project latest` or an explicit `--project <path>` flag, **When** the command runs, **Then** behavior matches today's documented semantics for those explicit forms (no regression for explicit usage).

---

### User Story 3 — Symmetric `--channel` API across the collect command group (Priority: P2)

The operator expects every `collect <subcommand>` to accept `--channel <alias>` and route auth through the corresponding multi-channel token. Today, `collect videos`, `collect transcripts`, and `collect comments` accept `--channel`, while `collect retention`, `collect analytics`, and (likely) `collect bulk` do not.

**Why this priority**: P2 because it is closely related to Story 1's outcome but is partially mitigated by Story 1's auto-routing behavior (with one alias registered, the system can pick it automatically). However, multi-alias environments require explicit `--channel`, and without symmetric API surface those environments cannot select the right channel for retention/analytics at all.

**Independent Test**: With two aliases registered, run `collect retention --channel <alias-2>` and verify the command (a) accepts the flag, (b) routes through `tokens/<alias-2>.json`, and (c) does not silently fall back to a different alias.

**Acceptance Scenarios**:

1. **Given** the registry has two registered aliases, **When** the operator runs any `collect <subcommand>` (where `<subcommand>` requires auth) without `--channel`, **Then** the command refuses with a message listing the registered aliases and showing the corrected command. It does not auto-pick.
2. **Given** the registry has exactly one registered alias, **When** the operator runs any `collect <subcommand>` without `--channel`, **Then** the command auto-selects that single alias and prints a notice indicating the auto-selection.
3. **Given** the registry is empty, **When** the operator runs any `collect <subcommand>` requiring auth, **Then** the command refuses with a message instructing them to run `auth --channel <name>` first.
4. **Given** any of `collect videos | transcripts | retention | comments | analytics | bulk`, **When** the operator passes `--channel <alias>`, **Then** the flag is accepted and the alias's token is used end-to-end (no fallback to `token.json`).

---

### User Story 4 — Diagnostic transcript collection (Priority: P3)

After collecting transcripts, the operator wants to know (a) which videos got transcripts, from which source (manual / auto_generated / Captions API fallback), and (b) why every miss was missed. Today, the JSON files do not record the source, the verbose 1st-step exception per private video drowns the progress output, and there is no audit of the misses.

**Why this priority**: P3 because the transcripts that did succeed are already usable for downstream content scan and reports. This story improves operational confidence and feeds quality reports, but it does not block the end-to-end pipeline.

**Independent Test**: Run `collect transcripts --channel <alias>`. Inspect any produced transcript JSON and confirm a `source` field is present. Verify a separate per-channel audit artifact exists that classifies every video missed (no transcript) by reason. Confirm that for private videos where the 1st-step library raised an exception but the 2nd-step fallback succeeded, the terminal output shows at most a brief one-line dim notice for the 1st-step failure.

**Acceptance Scenarios**:

1. **Given** a video's transcript was retrieved via the primary library (manual or auto-generated), **When** the JSON is written, **Then** the JSON carries a `source` field with value `manual` or `auto_generated`.
2. **Given** a video's transcript was retrieved via the Captions API fallback, **When** the JSON is written, **Then** the JSON carries `source: captions_api`.
3. **Given** the primary library throws (e.g. "video is private") and the fallback later succeeds, **When** the operator watches the terminal output, **Then** the primary failure is shown as a single dimmed line (not a full multi-line stack trace).
4. **Given** the operator runs `collect transcripts --channel <alias>` against a channel with N videos and M of them produce no transcript, **When** the command finishes, **Then** an audit artifact exists that lists every one of the M missed videos with `(video_id, title, primary_error_class, fallback_error_class, classification, hint)` rows.

---

### Edge Cases

- A legacy `token.json` and a `tokens/<alias>.json` both exist with the same `channel_id`. The newer mtime wins; the older is removed. The operator is informed in a single line.
- A legacy `token.json` exists with credentials whose `channel_id` does not appear in the channels registry. The legacy file is deleted and the operator is told how to register that channel.
- A legacy `token_forcessl.json` (older 2026-04-07 single-channel variant) exists alongside `token.json`. Both follow the same migration logic.
- The operator runs `collect retention` immediately after `collect videos` from a brand-new install, with exactly one alias registered. Both commands succeed without any explicit flags beyond `--channel`.
- The operator's terminal is non-interactive (e.g. CI, systemd, SSH without TTY). OAuth flow refuses to start the device-code prompt and prints guidance, instead of silently blocking on a TCP listener (consistency with idea6 NFR-IDEA6-003 / B7).
- Two `collect` commands run in parallel against the same project. The second to finish must not corrupt the `latest` reference; project commit must be atomic.
- Device-code flow polling reaches its timeout while the operator is still entering the code. The CLI fails fast with an actionable error and removes any partial token file.
- `collect videos` fails partway through (network drop). `latest` is NOT advanced to point at a partially-collected project; the previous good project remains the reference.

## Requirements *(mandatory)*

### Functional Requirements

#### Project resolution

- **FR-001**: For every CLI command in the `collect`, `content`, and `report` groups (i.e. any command that operates on a project), when the operator does not pass `--project`, the system MUST resolve the project to the most recently committed (`latest`) project and operate on it; the system MUST NOT create an empty new project as a side effect.
- **FR-002**: Exactly one CLI command (the producer of fresh data, currently `collect videos`) MAY create a new project when invoked without `--project`. All other commands MUST consume the existing latest. Producer commands MUST be explicitly listed in code, not inferred at runtime.
- **FR-003**: Any producer command that successfully creates and populates a new project MUST atomically advance the `latest` reference to that new project (using the atomic commit_latest semantics already defined in idea6 ADR-006). A producer command that fails before finishing data write MUST NOT advance `latest`.
- **FR-004**: Operator-explicit `--project latest` and `--project <path>` MUST keep their current semantics. The default change applies only to `project=None`.

#### Multi-channel auth routing

- **FR-005**: Every command that performs an authenticated YouTube API call (Data API, Analytics API, Reporting API) MUST route credentials through the multi-channel auth path keyed by an alias. No code path may consult the legacy single-channel default token file once an alias is resolvable.
- **FR-006**: When `--channel` is omitted and exactly one alias is registered in the channels registry, the system MUST auto-select that alias and emit a one-line notice. When zero aliases are registered, the system MUST refuse and emit guidance to run `auth --channel <name>`. When two or more aliases are registered, the system MUST refuse and list the registered aliases with their `channel_id` and last-used date and the corrected command.
- **FR-007**: `collect retention`, `collect analytics`, and `collect bulk` MUST accept `--channel <alias>` with the same semantics as `collect videos`, `collect transcripts`, and `collect comments`. The CLI surface across the collect group MUST be symmetric.

#### Legacy token migration

- **FR-008**: On the first invocation of any auth-using command after upgrade, the system MUST detect any legacy token files (`token.json`, `token_forcessl.json` under the user config directory) and, for each one whose embedded credentials carry a `channel_id` that matches a registered alias in the channels registry, atomically migrate the file to `tokens/<alias>.json`. If a `tokens/<alias>.json` already exists, the file with the newer mtime wins and the older one is deleted.
- **FR-009**: For any legacy token file whose embedded `channel_id` does not match any registered alias, the system MUST delete it and emit a single-line notice instructing the operator to run `auth --channel <name>` to register that channel.
- **FR-010**: After migration runs successfully, no command MUST read from any legacy single-channel token path. The deprecated paths are not re-created on subsequent runs.

#### OAuth flow

- **FR-011**: The default OAuth flow used by `auth --channel <alias>` (and any implicit re-auth triggered by a collect command) MUST be the device-code flow: print a verification URL and a short device code to the terminal, poll the token endpoint until the operator confirms in any browser, then persist the credentials atomically to `tokens/<alias>.json`.
- **FR-012**: An opt-in flag `--browser-redirect` MUST be available on `auth --channel <alias>` to use the legacy local-server redirect flow. When this flag is passed but the process detects a non-interactive environment (no TTY), the system MUST refuse the redirect flow and fall back to device-code, consistent with idea6 NFR-IDEA6-003.
- **FR-013**: Device-code polling MUST have a bounded timeout. On timeout, the system MUST fail fast with an actionable error message, MUST NOT leave any partial token file on disk, and MUST NOT block indefinitely.

#### Transcript metadata and audit

- **FR-014**: Every transcript JSON file produced by `collect transcripts` MUST carry a `source` field whose value is one of `manual`, `auto_generated`, or `captions_api`. Existing JSON files without this field MUST be re-collectable to backfill the field, but no transparent migration of legacy files is required.
- **FR-015**: When the primary transcript library raises an exception but the Captions API fallback succeeds for the same video, the terminal output MUST display the primary failure as at most a single dimmed line (or an aggregated summary at end of run). The full multi-line exception is shown only when both primary and fallback fail.
- **FR-016**: `collect transcripts` MUST produce a per-channel audit artifact listing every video for which no transcript was obtained. Each row MUST carry `video_id`, `video_title`, `primary_error_class`, `fallback_error_class`, `classification` (e.g. `asr_not_generated`, `private_no_owner_access`, `rate_limited`, `library_bug`, `quota_exhausted`), and `hint` (a short, operator-actionable next step).

#### Cross-cutting

- **FR-017**: All error messages introduced or modified by this feature MUST include a one-line cause and a suggested next command, consistent with the project's existing user-facing error pattern (idea6 ADR-007).
- **FR-018**: The system MUST NOT introduce any silent skip path. If a command cannot resolve a project, an alias, or a token, it MUST fail with a non-zero exit code and an actionable message — never proceed and report success on zero work, consistent with idea6 ADR-007.

### Key Entities

- **Project**: A timestamped directory under `projects/` carrying `01_collect/`, `02_analyze/`, and `checkpoints/`. Has a status (empty / partial / complete) and a commit timestamp. Only one project at a time is the `latest`.
- **Channel Alias Registration**: A row in the channels registry mapping an operator-chosen alias (e.g. `nursing`) to a YouTube `channel_id`, a `channel_name`, a registration timestamp, and a last-used timestamp. Owns its OAuth token at `tokens/<alias>.json`.
- **OAuth Token**: Credentials produced by either the device-code flow or the browser-redirect flow. Carries the granted scope set, an access token, a refresh token, and an expiry. Stored 0600 and atomically replaced on rotation.
- **Transcript Record**: A JSON file produced by `collect transcripts` for one video, carrying segments, language, and (new in this feature) a `source` field.
- **Transcript Audit Row**: A row in the per-channel transcripts audit artifact for a video that did not produce a transcript, carrying classification and operator-actionable hint.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator returning to the tool one week after their last successful run can complete the full chain `auth → collect videos → collect transcripts → collect retention → content scan → report bundle` against one registered channel using only the channel alias as a flag, with **no manual symlink edits, no `--project` flags, and no token-file deletion** between commands.
- **SC-002**: On a machine where the OAuth callback redirect previously hung (e.g. multi-account browser, VPN, redirect interception), the operator can complete OAuth registration in **under 2 minutes** using the default device-code flow, without killing the process or restarting it.
- **SC-003**: Running any `collect <subcommand>` without `--project` after a successful `collect videos` finds the just-collected videos **on the first attempt**, with **zero empty sibling project directories** created during the operation.
- **SC-004**: After upgrade, on a machine that carried a legacy `token.json` from a prior single-channel install, the first auth-using command **migrates** the legacy token rather than failing — the operator is not forced through a fresh OAuth round.
- **SC-005**: When the channels registry has two or more aliases and the operator omits `--channel`, the command refuses with a message that includes the **exact corrected command** for at least one available alias. The command does not silently pick one.
- **SC-006**: For a 200-video private channel, the operator's terminal output during `collect transcripts` is readable enough that the per-video success / fallback / failure status is identifiable at a glance — the verbose primary-library stack trace is **not** emitted line-by-line for fallback-succeeded videos.
- **SC-007**: For every video that did not produce a transcript in a given run, the operator can answer "why?" by reading **one row** in the audit artifact — without re-reading terminal logs or looking at YouTube directly.
- **SC-008**: 100% of newly written transcript JSON files include a `source` field, and 0% of code paths consult the deprecated `token.json` / `token_forcessl.json` after migration completes.
- **SC-009**: An OAuth flow that times out (device-code expires, operator does not finish in time) leaves the system in a clean state — no partial token files, no half-written registry rows, no orphaned listening sockets.

## Assumptions

- The operator already has `idea6` (Phase 4 closure, 2026-04-30) merged into the codebase. This feature depends on idea6's atomic project commit, the multi-channel-aware project layout, the secret loader, the OAuth scope verifier, the user-facing error pattern, and the silent-skip lint guard.
- The channels registry (`channels.json`) and per-alias token format (`tokens/<alias>.json`) introduced by idea6 are the canonical multi-channel state. No competing schema is introduced by this feature.
- The OAuth client secret continues to be supplied via `TUBE_SCOUT_CLIENT_SECRET_B64` (or the file-path equivalent), per idea6 D-4 fix. This feature does not change secret loading.
- A future `--all-channels` flag for batch operations is **out of scope**. Operators who need to operate on every registered alias must script the loop externally for now.
- The content of legacy `token.json` is trustworthy enough to read and use for `channel_id` lookup. No malicious-token threat model is introduced (the file is already at 0600 in the operator's user config directory).
- "Producer commands" that may create a new project are explicitly enumerated in code; this feature establishes the enumeration but reuses today's pipeline meaning where `collect videos` is the producer and all others are consumers.
