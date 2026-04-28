# Implementation Plan: OAuth Migration, Rate Limiting, Pipeline Enhancement & GPU Support

**Branch**: `005-oauth-ratelimit-gpu` | **Date**: 2026-04-05 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-oauth-ratelimit-gpu/spec.md`

## Summary

Migrate tube-scout from hybrid API key/OAuth authentication to OAuth-only, add per-service rate limiting (transcript scraping vs YouTube Data API), enhance `collect all` with `--channel` support and stage-level resume, synchronize OAuth client secret via agenix, and introduce a shared `TUBE_SCOUT_DEVICE` configuration for GPU-accelerated ML tasks.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pydantic v2, transformers, torch
**Storage**: JSON (atomic write) + Parquet (polars), checkpoint JSON
**Testing**: pytest (unit, integration, adversary)
**Target Platform**: NixOS Linux (agenix for secrets)
**Project Type**: CLI tool
**Performance Goals**: 214 videos transcript collection without IP block; GPU ML ~10x faster than CPU
**Constraints**: No API keys in codebase; OAuth client secret via env var only; CPU fallback mandatory
**Scale/Scope**: ~20 department channels, 50-500 videos per channel

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution is template (not customized for this project). No project-specific gates defined.
Applying CLAUDE.md principles as governance:

| Gate | Status | Notes |
|------|--------|-------|
| TDD mandatory | PASS | All changes will follow RED-GREEN-REFACTOR |
| No hardcoded secrets | PASS | OAuth client secret via env var (agenix); tokens in ~/.config |
| Fail-Fast | PASS | Input validation at function entry; pipeline aborts on video listing failure |
| Type annotations | PASS | All new functions will have full type annotations |
| Conventional commits | PASS | Will use feat/refactor/fix(scope) format |

## Project Structure

### Documentation (this feature)

```text
specs/005-oauth-ratelimit-gpu/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli-commands.md  # CLI contract changes
└── tasks.md             # Phase 2 output (via /speckit.tasks)
```

### Source Code (repository root)

```text
src/tube_scout/
├── services/
│   ├── auth.py              # MODIFY: Remove API key paths, OAuth-only
│   ├── youtube_data.py      # MODIFY: Remove api_key param, require OAuth client
│   ├── youtube_analytics.py # MODIFY: Extract rate limit to shared module
│   ├── transcript.py        # MODIFY: Add rate limiting wrapper
│   ├── sentiment.py         # MODIFY: Add device configuration
│   └── rate_limiter.py      # NEW: Per-service rate limiting with backoff
├── models/
│   └── config.py            # MODIFY: Add RateLimitProfile, DeviceConfig
├── cli/
│   └── collect.py           # MODIFY: Add --channel to collect_all, error handling
├── storage/
│   └── checkpoint.py        # MODIFY: Stage-level completion tracking
└── output/
    └── manager.py           # No changes expected

tests/
├── unit/
│   ├── test_rate_limiter.py     # NEW
│   ├── test_device_config.py    # NEW
│   ├── test_auth.py             # MODIFY: Update for OAuth-only
│   ├── test_youtube_data.py     # MODIFY: Remove API key tests
│   ├── test_transcript.py       # MODIFY: Rate limiting tests
│   ├── test_sentiment.py        # MODIFY: Device config tests
│   └── test_collect_all.py      # MODIFY: --channel, error handling, resume
├── integration/
│   └── test_pipeline_resume.py  # NEW: Stage-level resume integration
└── adversary/
    └── test_rate_limit_edge.py  # NEW: Rate limiting edge cases
```

**Structure Decision**: Single project structure (existing). New file `rate_limiter.py` in services/ for shared rate limiting. All other changes are modifications to existing files.

## Complexity Tracking

No constitution violations requiring justification.

## Phase Summaries

### Phase A — OAuth-Only Migration (FR-001, FR-004, FR-005, FR-009)

**Scope**: Remove all API key authentication paths. `YouTubeDataService` must accept only an OAuth-built client (no `api_key` param). `TUBE_SCOUT_CLIENT_SECRET` env var becomes the sole credential source. Token storage remains at `~/.config/tube-scout/tokens/`.

**Key Changes**:
- `services/youtube_data.py`: Remove `api_key` param from `__init__`, remove `YOUTUBE_API_KEY` env var lookup, require pre-built OAuth client injection
- `services/auth.py`: Remove `_default_client_secret_path()` file-glob fallback; require `TUBE_SCOUT_CLIENT_SECRET` env var. Keep multi-channel token management as-is.
- `cli/collect.py`: Update all `YouTubeDataService` instantiation to use OAuth client from `auth.build_data_client()`
- Delete/update all tests referencing `YOUTUBE_API_KEY` or `developerKey`

**Risk**: Existing users with API key setups lose access. Mitigated by clear migration docs.

### Phase B — Per-Service Rate Limiting (FR-002, FR-008, FR-010)

**Scope**: New `rate_limiter.py` module with per-service profiles. Two default profiles: `transcript` (aggressive — 2s base delay, 3x backoff, 5 max retries) and `youtube_api` (moderate — 0.1s base delay, 2x backoff, 3 max retries). Configurable via `RateLimitProfile` in config.

**Key Changes**:
- `services/rate_limiter.py` (NEW): `RateLimiter` class with `async_wait()` / `wait()`, exponential backoff, progress callback for Rich display
- `models/config.py`: Add `RateLimitProfile` pydantic model (base_delay, max_retries, backoff_multiplier)
- `services/transcript.py`: Wrap `YouTubeTranscriptApi` calls with transcript rate limiter
- `services/youtube_analytics.py`: Replace inline retry logic with shared `RateLimiter`
- `cli/collect.py`: Wire progress display for backoff events

**Risk**: Default delays may be too aggressive or too conservative. Mitigated by configurability.

### Phase C — Pipeline Enhancement (FR-003, FR-011, FR-012)

**Scope**: Add `--channel` option to `collect all`. Implement stage-level error handling (abort on video listing failure, continue otherwise). Add stage completion detection for resume.

**Key Changes**:
- `cli/collect.py`: Add `--channel` param to `collect_all_command`; replace bare `except SystemExit: pass` with proper error tracking per stage; add summary report at end
- `storage/checkpoint.py`: Add `is_stage_complete(stage_name)` and `mark_stage_complete(stage_name)` methods for stage-level tracking
- `cli/collect.py`: Check stage completion before executing each stage on re-run

**Risk**: Stage completion detection may produce false positives if a stage partially completed. Mitigated by checking output file existence + checkpoint state.

### Phase D — GPU Device Configuration (FR-006, FR-007)

**Scope**: Introduce `TUBE_SCOUT_DEVICE` env var read by a shared `get_device()` function. All ML services call this function. Default: `cpu`.

**Key Changes**:
- `models/config.py`: Add `get_device() -> str` function reading `TUBE_SCOUT_DEVICE` env var, validating `cpu`/`cuda`, defaulting to `cpu`
- `services/sentiment.py`: Pass `device=get_device()` to `transformers.pipeline()`
- Future ML services (v4): Will call same `get_device()`

**Risk**: Minimal — additive change with CPU as safe default.

### Phase E — Agenix Integration (FR-004, SC-004)

**Scope**: NixOS module configuration for tube-scout OAuth client secret via agenix. This is infrastructure-as-code, not application code.

**Key Changes**:
- Documentation in `quickstart.md` for agenix setup
- `TUBE_SCOUT_CLIENT_SECRET` env var expected to point to agenix-decrypted file path
- No application code changes beyond Phase A (env var already required)

**Risk**: Depends on user's NixOS/agenix setup. Mitigated by clear documentation.
