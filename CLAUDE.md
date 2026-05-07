# tube-scout Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-07

## Active Technologies
- Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pandas, polars, plotly, jinja2, pydantic v2, nbformat, anthropic (new), openai (new), statsmodels (new — ARIMA), prophet (new), transformers + torch (new — KoBERT/KoELECTRA) (002-v2-analytics-expansion)
- JSON (atomic write) + Parquet (polars) — existing pattern preserved (002-v2-analytics-expansion)
- Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, pydantic v2, pyyaml (new), openpyxl (new), plotly, jinja2, Levenshtein (new — for name similarity V-004) (003-multichannel-admin)
- JSON (structured data) + timestamped output directories under `./output/` (003-multichannel-admin)
- Python 3.11 + typer, rich, jinja2, weasyprint, pydantic v2, plotly (static image export) (004-report-filter-pdf-bundle)
- JSON (videos_meta.json), Parquet (retention), HTML (existing reports) (004-report-filter-pdf-bundle)
- Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pydantic v2, transformers, torch (005-oauth-ratelimit-gpu)
- JSON (atomic write) + Parquet (polars), checkpoint JSON (005-oauth-ratelimit-gpu)
- Python 3.11 + typer, rich, jinja2, weasyprint (optional), pydantic v2, plotly (006-report-filter-pdf-bundle)
- JSON (videos_meta.json, parsed_titles.json, channel_meta.json) — 기존 수집 데이터 사용 (006-report-filter-pdf-bundle)
- Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pydantic v2, sentence-transformers, polars, plotly, jinja2, openpyxl (007-content-reuse-detection)
- SQLite (processing status, comparison results, review status) + Parquet (embeddings) + JSON (captions, metadata) (007-content-reuse-detection)
- Python 3.11 + starlette, uvicorn[standard], itsdangerous, bcrypt, python-multipart, pytest-asyncio, httpx, jinja2 (008-admin-web-ui)
- Python 3.11 (pinned via flake.nix devShell + pyproject.toml). + typer, rich, google-api-python-client, (009-runtime-auth-fix)
- JSON (atomic write) under `~/.config/tube-scout/tokens/` for (009-runtime-auth-fix)

- Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pandas, polars, plotly, jinja2, statsmodels/prophet (001-lecture-video-analytics)

## Project Structure

```text
src/
tests/
```

## Install Profiles (uv extras)

The dependency surface is split so that day-to-day development, CI, and
operator deployments do not pay the cost of the heaviest ML/PDF stacks
unless they are actually used. Defaults stay under ~1 GB on disk and do
not OOM 13 GB dev hosts during pytest collection.

| Profile | Command | Adds |
|---|---|---|
| Lean (default) | `uv sync` | core CLI, auth, collect, report (HTML), web admin |
| Dev | `uv sync --extra dev` | + pytest, pytest-cov, pytest-asyncio, pytest-httpx, ruff |
| Sentiment (local) | `uv sync --extra ml-sentiment` | + transformers, torch (~1 GB) |
| Forecasting | `uv sync --extra ml-forecast` | + statsmodels, prophet (~700 MB, Stan compile) |
| All ML | `uv sync --extra ml` | both ML extras |
| PDF reports | `uv sync --extra pdf` | + weasyprint (cairo/pango) |
| Everything | `uv sync --all-extras` | every extra above |

All heavy imports in `src/` are function-local (lazy) — calling a
sentiment/forecast/PDF code path without the matching extra raises a
clear `ImportError` with the exact `uv sync --extra …` recipe.

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11: Follow standard conventions

## Recent Changes
- 2026-05-08 (deps hotfix): `transformers`, `torch`, `prophet`, `statsmodels`, `weasyprint` moved from hard `dependencies` into PEP 621 optional-extras (`ml-sentiment`, `ml-forecast`, `pdf`, aggregate `ml`/`all`). Default `uv sync` now installs ~1 GB of deps instead of ~5.4 GB and pytest collection no longer OOMs 13 GB dev hosts. Lazy-import error messages in `services/sentiment.py` and `services/forecaster.py` updated to point operators at the correct `uv sync --extra <name>` recipe; `tests/unit/test_forecaster_ext.py` gains a `prophet` `importorskip` guard. **Migration**: existing dev `.venv` may carry stale ML libs — run `uv sync` (no extras) to prune, or `uv sync --extra dev --extra ml` to keep ML on hand.
- 009-runtime-auth-fix: OAuth device-code flow (RFC 8628) is now the default for `tube-scout auth --channel <alias>`; `--browser-redirect` opt-in retains the legacy local-server flow with a 5-minute timeout fallback. One-shot legacy `~/.config/tube-scout/token{,_forcessl}.json` migration into `tokens/<alias>.json` runs at the first `authenticate_channel()` call (atomic rename, fcntl.flock). `resolve_project()` now distinguishes producer vs consumer commands: only `collect.videos` advances `projects/latest`. `--channel` flag is symmetric across every `collect` subcommand (videos/transcripts/comments/retention/analytics/bulk) with a single centralized `resolve_channel_alias()` call. Diagnostic transcript audit CSV emitted at `<project>/01_collect/transcripts_audit.csv`. Adds `httpx` as a direct dependency.
- 008-admin-web-ui: Added starlette, uvicorn[standard], itsdangerous, bcrypt, python-multipart, pytest-asyncio, httpx, jinja2 for the operator admin web UI (US1+US2+US3)
- 007-content-reuse-detection: Added Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pydantic v2, sentence-transformers, polars, plotly, jinja2, openpyxl


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
