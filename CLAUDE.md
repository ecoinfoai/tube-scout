# tube-scout Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-04

## Active Technologies
- Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pandas, polars, plotly, jinja2, pydantic v2, nbformat, anthropic (new), openai (new), statsmodels (new — ARIMA), prophet (new), transformers + torch (new — KoBERT/KoELECTRA) (002-v2-analytics-expansion)
- JSON (atomic write) + Parquet (polars) — existing pattern preserved (002-v2-analytics-expansion)
- Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, pydantic v2, pyyaml (new), openpyxl (new), plotly, jinja2, Levenshtein (new — for name similarity V-004) (003-multichannel-admin)
- JSON (structured data) + timestamped output directories under `./output/` (003-multichannel-admin)
- Python 3.11 + typer, rich, jinja2, weasyprint, pydantic v2, plotly (static image export) (004-report-filter-pdf-bundle)
- JSON (videos_meta.json), Parquet (retention), HTML (existing reports) (004-report-filter-pdf-bundle)

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
- 004-report-filter-pdf-bundle: Added Python 3.11 + typer, rich, jinja2, weasyprint, pydantic v2, plotly (static image export)
- 003-multichannel-admin: Added Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, pydantic v2, pyyaml (new), openpyxl (new), plotly, jinja2, Levenshtein (new — for name similarity V-004)
- 002-v2-analytics-expansion: Added Python 3.11 + typer, rich, google-api-python-client, google-auth-oauthlib, youtube-transcript-api, pandas, polars, plotly, jinja2, pydantic v2, nbformat, anthropic (new), openai (new), statsmodels (new — ARIMA), prophet (new), transformers + torch (new — KoBERT/KoELECTRA)


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
