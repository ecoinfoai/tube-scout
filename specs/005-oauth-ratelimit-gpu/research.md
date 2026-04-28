# Research: 005-oauth-ratelimit-gpu

**Date**: 2026-04-05

## R-001: YouTube Transcript API Rate Limiting

**Decision**: Use per-request delay with jitter + exponential backoff on failure.

**Rationale**: `youtube-transcript-api` is an unofficial library that scrapes YouTube's web interface. YouTube detects rapid sequential requests from the same IP and blocks them. Unlike the official Data API (which uses quota-based limits with clear HTTP 429 responses), transcript scraping triggers opaque IP blocks after ~50-100 rapid requests.

**Alternatives considered**:
- Request batching: Not supported by youtube-transcript-api (one video per request)
- Proxy rotation: Adds operational complexity, unnecessary for ~200 videos with proper delays
- YouTube Data API captions endpoint: Requires caption owner permissions, not available for third-party channels

**Implementation**: Base delay of 2.0s with ±0.5s random jitter between requests. On HTTP error/connection reset: exponential backoff starting at 5s, multiplier 3x, max 5 retries. These defaults are conservative for 214 videos (~7-8 min total wait time).

## R-002: OAuth Client Migration from API Key

**Decision**: Remove `api_key` parameter from `YouTubeDataService.__init__()`, require pre-built OAuth client via dependency injection.

**Rationale**: The codebase already has full multi-channel OAuth support in `auth.py` with `build_data_client()`. The API key path in `youtube_data.py:35-48` is a legacy fallback that creates confusion. The university's academic affairs office manages all channel credentials centrally via OAuth, making API keys unnecessary.

**Alternatives considered**:
- Keep API key as fallback: Contradicts FR-001 (remove entirely); causes auth path confusion
- Environment variable toggle: Adds complexity for a path that will never be used

**Implementation**: `YouTubeDataService.__init__(client)` accepts only a pre-built client (the existing `client` param). Remove `api_key` param, `YOUTUBE_API_KEY` lookup, and `developerKey` usage. All CLI commands use `auth.build_data_client()` to construct the client.

## R-003: collect all --channel Integration

**Decision**: Add `--channel` option that maps to multi-channel auth alias, passing authenticated client to each pipeline stage.

**Rationale**: Current `collect_all_command` (line 733-819) has no `--channel` parameter. Individual subcommands like `collect_videos_command` already accept `--channel` (line 63). The gap is in the orchestrator. Multi-channel auth via `authenticate_channel(alias)` is already implemented in `auth.py`.

**Alternatives considered**:
- Config-file-based channel selection: Less ergonomic than CLI flag
- Interactive channel picker: Doesn't support scripting/automation

**Implementation**: Add `--channel` optional param to `collect_all_command`. When provided, call `authenticate_channel(alias)` once, pass the resulting client to all 5 stages. When omitted, fall back to current default config behavior.

## R-004: Stage-Level Resume Strategy

**Decision**: Use output file existence + checkpoint state for stage completion detection.

**Rationale**: The checkpoint system (`storage/checkpoint.py`) already tracks `CollectionState` per `{channel_id}:{phase}`. Extending this to track stage-level completion in `collect all` is straightforward. Checking both checkpoint JSON and output directory contents provides double-verification.

**Alternatives considered**:
- Video-level resume within stages: Too complex for v3.2; better suited for v4 if needed
- Timestamp-based freshness check: Hard to define "fresh enough" threshold

**Implementation**: Before each stage in `collect all`, check if `checkpoints/collection_state.json` marks the stage as complete AND the expected output directory is non-empty. If both conditions met, skip stage with log message. `--force-refresh` flag overrides resume behavior.

## R-005: GPU Device Configuration Pattern

**Decision**: Single `get_device()` function in `models/config.py` reading `TUBE_SCOUT_DEVICE` env var.

**Rationale**: Current sentiment service loads `transformers.pipeline()` without explicit device configuration, relying on PyTorch auto-detection. This is unreliable across NixOS machines. A single env var provides explicit control and a consistent interface for all current and future ML services (v4: sentence-transformers, KoBERT/KoELECTRA).

**Alternatives considered**:
- Config file setting: Env var is simpler for NixOS/agenix integration, no persistence needed
- Auto-detect with override: Contradicts spec requirement for explicit opt-in (CPU default)
- Per-service device setting: Unnecessary; all ML tasks should use the same device

**Implementation**: `get_device()` reads `TUBE_SCOUT_DEVICE`, validates against `{"cpu", "cuda"}`, defaults to `"cpu"`. Returns string suitable for `torch.device()` and `transformers.pipeline(device=...)`. Sentinel function used by all ML services.

## R-006: Rate Limiter Architecture

**Decision**: Synchronous `RateLimiter` class with per-service profile presets and optional progress callback.

**Rationale**: tube-scout is a synchronous CLI tool (no async). Rate limiting needs to be simple: sleep between requests with exponential backoff on errors. Two default profiles cover the distinct external services: transcript scraping (IP-based, aggressive delays) and YouTube Data API (quota-based, moderate delays).

**Alternatives considered**:
- Token bucket algorithm: Over-engineered for sequential CLI requests
- Async rate limiter: Not needed; tube-scout is sync
- Decorator-based: Less flexible than explicit limiter instance

**Implementation**: `RateLimiter(profile: RateLimitProfile, on_backoff: Callback | None)` class with `wait()` (inter-request delay) and `wait_on_error(attempt: int)` (exponential backoff). Two preset profiles: `TRANSCRIPT_PROFILE` (2.0s base, 3x backoff, 5 retries) and `YOUTUBE_API_PROFILE` (0.1s base, 2x backoff, 3 retries). Profiles stored as `RateLimitProfile` pydantic models, overridable via config.
