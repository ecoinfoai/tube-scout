# tube-scout Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-13

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
- Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`) + typer, rich, pydantic v2, polars, sentence-transformers (spec 007 인계), jinja2, plotly, openpyxl. **신규 0건** — 기존 의존성 surface 안에서 충분. (011-reuse-fullstack-subtitle)
- 기존 spec 007 `02_analyze/content/content_reuse.db`(SQLite) + `embeddings.parquet`(polars) + caption JSON. 신규 테이블 5개 추가, 신규 storage 엔진 도입 없음. (011-reuse-fullstack-subtitle)
- Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`) + typer, rich, pydantic v2, polars, jinja2, plotly, weasyprint(optional `pdf`), chromaprint/ffmpeg 재사용. 신규 PyPI: `faster-whisper>=1.0.0` (CTranslate2 backend, int8 양자화, GPU/CPU 분기). 신규 Nix: `cudnn`, `cuda-nvrtc` (faster-whisper GPU 런타임). optional extra `asr`로 분리. (013-takeout-local-asr-reuse)
- SQLite v4 마이그레이션 — `channel_metadata`, `video_metadata` 신규 테이블 + `processing_status` (+`match_confidence`, `caption_source_detail`) + `quality_results` (+`asr_quality_flags` JSON) + `comparison_results` (+`audio_fp_*`, `source_type_pair`) ALTER. JSON(channel_meta, videos_meta) 이중 적재. 임시 WAV는 비영구(통합 모드 즉시 삭제, C-1). (013-takeout-local-asr-reuse)

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
| Speech-to-text (local) | `uv sync --extra asr` | + faster-whisper (~1.5 GB int8 quantized weights via huggingface-hub) |
| Everything | `uv sync --all-extras` | every extra above |

All heavy imports in `src/` are function-local (lazy) — calling a
sentiment/forecast/PDF code path without the matching extra raises a
clear `ImportError` with the exact `uv sync --extra …` recipe.

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11: Follow standard conventions

## Recent Changes
- 013-takeout-local-asr-reuse (v0.5.0 released, 2026-05-14): Takeout-based local ASR + lecture-video reuse detection + KB transcript export. Adds `faster-whisper>=1.0.0` (CTranslate2 backend, int8/float16) behind the new `[asr]` optional extra. SQLite migration v3 → v4: 2 new tables (`channel_metadata`, `video_metadata`) + 4 ALTER columns (`processing_status.match_confidence`, `processing_status.caption_source_detail`, `quality_results.asr_quality_flags`, `comparison_results.audio_fp_*` / `source_type_pair`). 9 new CLI commands: `collect takeout`, `collect audio-extract`, `collect process-audio`, `collect transcripts --source asr`, `collect fingerprint --source local`, `process normalize-transcripts`, `analyze content-reuse`, `report content-reuse`, `transcript export`/`export-bulk`. New services: `takeout_ingest.py`, `audio_extract.py`, `asr.py`, `text_normalizer.py`, `worker_pool.py`, `progress_reporter.py`, `evidence_score.py`. New reporting template `professor_nC2_report.html` (multi-axis Phase 3, aggregate-score deferred 30 days — see `_workspace/measurement/30day_followup_plan.md`). audit_writer.py generalized to 8 stages. C-3/C-4/C-5 clarifications drive multi-axis report sort, TTY auto-detect progress, atomic claim retry-failed. Phase 5 fully removes the previous-generation media adapter surface (public-sector ops policy, FR-046). `flake.nix` splits into `devShells.default` (CPU) and `devShells.gpu` (unfree opt-in, adds `cudaPackages.cudnn` + `cudaPackages.cuda_nvrtc`).
- 013-takeout-local-asr-reuse: Added Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`)
- 012 media adapter (v0.4.0, removed in spec 013): Predecessor media-adapter spec — provided 3 CLI subcommands and SQLite v3 schema (`audio_fingerprint` table). The chromaprint pipeline (`services/audio_fingerprint.py` plus `chromaprint`, `ffmpeg`, `zlib`, `stdenv.cc.cc.lib` in `flake.nix`) is retained by spec 013; the rest of the adapter surface is deleted (FR-046).


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
