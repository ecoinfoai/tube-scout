# Feature Specification: OAuth Migration, Rate Limiting, Pipeline Enhancement & GPU Support

**Feature Branch**: `005-oauth-ratelimit-gpu`
**Created**: 2026-04-05
**Status**: Draft
**Input**: User description: "idea/idea3.2.md"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - OAuth-Only Authentication (Priority: P1)

The DX Support Center operator manages YouTube channels for multiple departments through the university's central academic affairs office. The operator needs a single, clean authentication path using OAuth — without any API key options — so that all department channels can be accessed through one authorized flow.

**Why this priority**: Authentication is foundational. Every other feature (pipeline, rate limiting, data collection) depends on a working auth system. Removing the API key/OAuth hybrid eliminates confusion and errors at the entry point of all workflows.

**Independent Test**: Can be fully tested by authenticating via OAuth and running any single data collection command against a department channel. Delivers value by simplifying auth and removing a known source of operator errors.

**Acceptance Scenarios**:

1. **Given** a fresh installation with OAuth client secret available via environment variable, **When** the operator runs any tube-scout command for the first time, **Then** the system initiates OAuth browser-based authorization and stores the resulting token locally.
2. **Given** a valid stored OAuth token, **When** the operator runs a data collection command, **Then** the system uses the token without prompting for re-authentication.
3. **Given** the codebase after migration, **When** searching for any API key references (YOUTUBE_API_KEY, api_key parameter, key-based auth), **Then** zero references are found.
4. **Given** an expired OAuth token with a valid refresh token, **When** the operator runs a command, **Then** the system silently refreshes the token and proceeds.

---

### User Story 2 - Rate-Limited Transcript Collection (Priority: P1)

The operator needs to collect transcripts for 200+ videos without triggering YouTube's IP blocking. Currently, rapid-fire requests cause the IP to be blocked within seconds of starting collection.

**Why this priority**: IP blocking makes large-scale data collection impossible, which is the core use case. Without rate limiting, the tool cannot fulfill its primary purpose for departments with many videos.

**Independent Test**: Can be fully tested by running transcript collection against a channel with 50+ videos and verifying all transcripts are collected without any HTTP 429 or IP block errors. Delivers value by making bulk collection reliable.

**Acceptance Scenarios**:

1. **Given** a channel with 214 videos, **When** the operator runs transcript collection, **Then** all transcripts are collected without IP blocking or HTTP 429 errors.
2. **Given** a transient rate limit response from YouTube, **When** the system receives an HTTP 429 or similar throttle signal, **Then** it applies exponential backoff and retries automatically.
3. **Given** operator-customized rate limit settings, **When** the operator specifies delay and backoff parameters, **Then** the system respects those settings for all external API calls.
4. **Given** a collection in progress, **When** the operator observes progress output, **Then** the current request rate and any backoff events are visible.

---

### User Story 3 - Single-Command Multi-Step Collection (Priority: P2)

The operator wants to run `collect all --channel <alias>` to execute the entire 5-step data collection pipeline (video listing, metadata, transcripts, retention, analytics) for a specific department channel in one command.

**Why this priority**: Reduces a 5-command manual workflow to one command. High operational value but depends on OAuth (P1) being in place first.

**Independent Test**: Can be fully tested by running `collect all --channel <alias>` for a department channel and verifying that all 5 collection stages complete and produce expected output files. Delivers value by reducing operator effort from 5 commands to 1.

**Acceptance Scenarios**:

1. **Given** a configured department channel alias, **When** the operator runs `collect all --channel dept-nursing-science`, **Then** all 5 collection stages execute sequentially and produce output in the project directory.
2. **Given** a failure in the video listing stage (first stage), **When** the error occurs, **Then** the pipeline stops immediately because all subsequent stages depend on the video list.
3. **Given** a failure in any stage after video listing, **When** the error occurs, **Then** the system logs the error, skips dependent processing, continues to the next independent stage, and reports all failures in a summary at the end.
3. **Given** a previously interrupted `collect all` run, **When** the operator re-runs the same command, **Then** the system detects completed stages and resumes from the first incomplete stage.
4. **Given** `collect all` without `--channel`, **When** the operator runs the command, **Then** the system uses the default channel configuration (existing behavior preserved).

---

### User Story 4 - Cross-Machine OAuth Secret Sync (Priority: P2)

When deploying tube-scout on a new NixOS machine, the operator expects the OAuth client secret to be available immediately after `nixos-rebuild switch`, managed through the existing agenix infrastructure.

**Why this priority**: Enables multi-machine deployment, which is an operational necessity for the team. Depends on OAuth-only auth (P1) being complete.

**Independent Test**: Can be fully tested by provisioning a new machine with agenix-managed secrets, running `nixos-rebuild switch`, and then executing a tube-scout command that requires OAuth. Delivers value by enabling zero-manual-setup deployment.

**Acceptance Scenarios**:

1. **Given** a new NixOS machine with agenix configured, **When** `nixos-rebuild switch` completes, **Then** the OAuth client secret is available at the expected path or environment variable.
2. **Given** the client secret is available, **When** the operator runs tube-scout for the first time on the new machine, **Then** only the OAuth browser authorization flow is needed (no manual secret file copying).
3. **Given** the runtime token store (`~/.config/tube-scout/tokens/`), **When** checking agenix-managed secrets, **Then** runtime tokens are NOT included in agenix (they remain machine-local).

---

### User Story 5 - GPU-Accelerated ML Processing (Priority: P3)

The GPU server operator wants ML tasks (sentiment analysis, STT) to automatically use the GPU when available, significantly reducing processing time for large video collections.

**Why this priority**: Performance optimization for large-scale processing. The tool works without GPU (CPU fallback), so this is an enhancement rather than a blocker. Also establishes the device infrastructure for future v4 ML features.

**Independent Test**: Can be fully tested by setting `TUBE_SCOUT_DEVICE=cuda` on a GPU-equipped machine, running sentiment analysis on a batch of videos, and comparing execution time against CPU-only mode. Delivers value by reducing hours-long ML processing to minutes.

**Acceptance Scenarios**:

1. **Given** a machine with a CUDA-capable GPU and `TUBE_SCOUT_DEVICE=cuda`, **When** the operator runs sentiment analysis or STT, **Then** the ML models execute on the GPU.
2. **Given** a machine without GPU (or `TUBE_SCOUT_DEVICE=cpu`), **When** the operator runs the same ML tasks, **Then** the system falls back to CPU without errors.
3. **Given** `TUBE_SCOUT_DEVICE` is not set, **When** the operator runs ML tasks, **Then** the system defaults to CPU (explicit opt-in for GPU).
4. **Given** a GPU environment, **When** any current or future ML service initializes, **Then** it reads the device setting from a single shared configuration point.

---

### Edge Cases

- What happens when the OAuth token expires mid-collection of 200+ videos?
- How does the system behave when YouTube changes its rate limiting thresholds unexpectedly?
- What happens if the agenix-managed client secret is rotated while a collection is in progress?
- How does the system handle a GPU running out of memory during ML processing?
- What happens when `collect all` is interrupted mid-pipeline and re-run? → Resolved: stage-level resume (skip completed stages).
- How does rate limiting behave when multiple tube-scout instances run concurrently on the same IP?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST authenticate exclusively via OAuth 2.0; all API key-based authentication code and configuration MUST be removed entirely.
- **FR-002**: System MUST apply per-service rate limiting with sensible defaults: transcript retrieval (aggressive delays — longer base delay, conservative backoff to avoid IP blocking) and YouTube Data API (moderate delays — shorter base delay, standard backoff for quota management). Each service profile MUST be independently configurable.
- **FR-003**: System MUST support a `collect all --channel <alias>` command that executes all collection stages (video listing, metadata, transcripts, retention, analytics) sequentially for the specified channel.
- **FR-004**: System MUST read the OAuth client secret from an environment variable (populated by agenix) rather than from a project-local file.
- **FR-005**: System MUST store runtime OAuth tokens (access + refresh) in `~/.config/tube-scout/tokens/` per machine, separate from agenix-managed secrets.
- **FR-006**: System MUST provide a device configuration mechanism (via `TUBE_SCOUT_DEVICE` environment variable) that all ML services reference for compute device selection.
- **FR-007**: System MUST fall back to CPU when GPU is unavailable or when `TUBE_SCOUT_DEVICE` is not set or set to `cpu`.
- **FR-008**: System MUST display progress information during rate-limited operations, including current throughput and any backoff events.
- **FR-009**: System MUST handle token refresh transparently during long-running collection operations without interrupting the workflow.
- **FR-010**: System MUST allow operators to configure rate limit parameters (base delay, max retries, backoff multiplier) through settings.
- **FR-011**: System MUST abort `collect all` pipeline if the video listing stage (first stage) fails. For any subsequent stage failure, the system MUST log the error, skip dependent processing, continue to the next independent stage, and present a failure summary at pipeline completion.
- **FR-012**: System MUST detect previously completed pipeline stages on re-run and resume from the first incomplete stage, avoiding redundant re-collection of already-gathered data.

### Key Entities

- **OAuth Credential**: Consists of a client secret (app-level, agenix-managed) and runtime tokens (access + refresh, machine-local). The client secret is shared across machines; tokens are per-machine.
- **Rate Limit Configuration**: Per-service profiles (transcript retrieval, YouTube Data API) each defining base delay, maximum retry count, and backoff multiplier. Each profile has sensible defaults tuned to its blocking mechanism (IP-based for transcripts, quota-based for API) and is independently configurable by the operator.
- **Device Configuration**: A single shared setting (`TUBE_SCOUT_DEVICE`) that determines compute device (cpu/cuda) for all ML services, with CPU as the safe default.
- **Collection Pipeline**: An ordered sequence of 5 stages (video listing, metadata, transcripts, retention, analytics) that can be executed individually or as a unified `collect all` operation scoped to a specific channel.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero references to API key authentication remain in the codebase after migration (searchable verification: `YOUTUBE_API_KEY`, `api_key`, `developerKey`).
- **SC-002**: A single `collect all --channel <alias>` command completes all 5 collection stages for a department channel without manual intervention.
- **SC-003**: Transcript collection for 214 videos completes without IP blocking or HTTP 429 errors, with configurable delays between requests.
- **SC-004**: On a new NixOS machine, after `nixos-rebuild switch`, the OAuth client secret is available and tube-scout can initiate OAuth flow without manual file copying.
- **SC-005**: When `TUBE_SCOUT_DEVICE=cuda` is set on a GPU-equipped machine, all ML tasks (sentiment analysis, STT) execute on the GPU; when unset or set to `cpu`, they execute on CPU without errors.
- **SC-006**: All ML services (current and future) read device configuration from a single shared configuration point, verified by code inspection.

## Clarifications

### Session 2026-04-05

- Q: How should `collect all` pipeline handle mid-stage failures? → A: Continue on failure except for video listing (first stage); skip dependent stages, report all errors at end.
- Q: How should `collect all` behave when re-run after interruption? → A: Detect completed stages and skip them; resume from the first incomplete stage.
- Q: Should rate limiting use a single config or per-service profiles? → A: Per-service rate limit profiles with sensible defaults (transcript: aggressive, API: moderate).

## Assumptions

- The university's academic affairs office manages OAuth credentials for all department YouTube channels centrally.
- All deployment targets are NixOS machines with agenix already configured for secret management.
- YouTube's rate limiting is primarily triggered by request frequency, and configurable delays with exponential backoff are sufficient to avoid IP blocking.
- Operators explicitly opt in to GPU usage via environment variable; automatic GPU detection is not desired (CPU is the safe default).
- The existing `collect all` command structure supports adding a `--channel` parameter without breaking current workflows (backward compatible when `--channel` is omitted).
- Runtime OAuth tokens (`token.json`) are ephemeral and machine-specific; they do not need cross-machine synchronization.
- The 5-stage collection pipeline order (video listing, metadata, transcripts, retention, analytics) is fixed and does not need to be configurable.
