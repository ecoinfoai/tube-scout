# Quickstart: 005-oauth-ratelimit-gpu

**Date**: 2026-04-05

## Prerequisites

- Python 3.11
- NixOS with agenix configured
- Google Cloud project with OAuth 2.0 credentials (YouTube Data API v3 + Analytics API v2)

## Setup

### 1. OAuth Client Secret (agenix)

```nix
# secrets/tube-scout-client-secret.age — encrypt the Google OAuth client_secret.json
age.secrets.tube-scout-client-secret = {
  file = ./secrets/tube-scout-client-secret.age;
  owner = "kjeong";
};
```

In your NixOS module or shell:
```nix
environment.variables.TUBE_SCOUT_CLIENT_SECRET = config.age.secrets.tube-scout-client-secret.path;
```

After `nixos-rebuild switch`, the env var points to the decrypted JSON file.

### 2. Register a Channel

```bash
tube-scout auth register --alias dept-nursing-science
# Opens browser for OAuth authorization
```

Token saved to `~/.config/tube-scout/tokens/dept-nursing-science.json`.

### 3. Run Full Collection

```bash
tube-scout collect all --channel dept-nursing-science
```

Pipeline executes 5 stages with rate limiting and stage-level resume.

### 4. GPU Configuration (optional)

```bash
export TUBE_SCOUT_DEVICE=cuda  # or leave unset for CPU
tube-scout analyze sentiment --channel dept-nursing-science
```

## Key Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TUBE_SCOUT_CLIENT_SECRET` | Yes | Path to OAuth client secret JSON |
| `TUBE_SCOUT_DEVICE` | No | `cpu` (default) or `cuda` |
| `TUBE_SCOUT_TOKENS_DIR` | No | Override token storage directory |

## Secret vs Token Separation

| Item | Managed By | Location | Scope |
|------|-----------|----------|-------|
| OAuth client secret (`client_secret.json`) | agenix | `TUBE_SCOUT_CLIENT_SECRET` env var path | Shared across machines |
| Runtime tokens (`token.json`, per-channel tokens) | tube-scout | `~/.config/tube-scout/tokens/` | Machine-local only |

Runtime tokens are **NOT** managed by agenix. They are created per-machine during the OAuth browser flow and stored locally. Do not include them in agenix secrets or deployment configs.

## Migration from API Key

1. Remove `YOUTUBE_API_KEY` from your environment
2. Set `TUBE_SCOUT_CLIENT_SECRET` via agenix (or direct path for dev)
3. Register channels: `tube-scout auth register --alias <name>`
4. All `collect` commands now use OAuth exclusively

## Rate Limiting Defaults

| Service | Base Delay | Backoff | Max Retries |
|---------|-----------|---------|-------------|
| Transcript scraping | 2.0s | 3x | 5 |
| YouTube Data/Analytics API | 0.1s | 2x | 3 |

Override via config if defaults need tuning.
