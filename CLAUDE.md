# tube-scout Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-28

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
- Python 3.11 (`pyproject.toml` `requires-python = ">=3.11"`) (008-admin-web-ui)

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
- 008-admin-web-ui: Added Python 3.11 (`pyproject.toml` `requires-python = ">=3.11"`)
- 006-report-filter-pdf-bundle: Added Python 3.11 + typer, rich, jinja2, weasyprint (optional), pydantic v2, plotly
- 005-oauth-ratelimit-gpu: Added Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pydantic v2, transformers, torch


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
