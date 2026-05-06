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

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11: Follow standard conventions

## Recent Changes
- 009-runtime-auth-fix: Added Python 3.11 (pinned via flake.nix devShell + pyproject.toml). + typer, rich, google-api-python-client,
- 008-admin-web-ui: Added starlette, uvicorn[standard], itsdangerous, bcrypt, python-multipart, pytest-asyncio, httpx, jinja2 for the operator admin web UI (US1+US2+US3)
- 007-content-reuse-detection: Added Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pydantic v2, sentence-transformers, polars, plotly, jinja2, openpyxl


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
