# tube-scout Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-16

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
- Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`) + typer, rich, pydantic v2, polars, faster-whisper (≥1.0.0, [asr] optional extra), CTranslate2 4.x, ffmpeg (chromaprint 패키지에 동봉). agenix 환경변수는 OAuth 흐름에서만 선택적 사용. **신규 PyPI 의존성 0건** — 기존 [asr] / [dev] / 기본 surface 안에서 모두 처리. (016-takeout-ingest-rebuild)
- SQLite v4 (스키마 변경 없음 — spec 013 의 channel_metadata + video_metadata + processing_status + quality_results + comparison_results 보존), JSON atomic write (channel_meta.json, videos_meta.json, channels.json, departments.json), 적재 audit CSV (`audit_writer.py` 의 stage `takeout_ingest`). (016-takeout-ingest-rebuild)
- Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`) + typer, rich, pydantic v2, polars, faster-whisper (≥1.0.0, `[asr]` optional extra), CTranslate2 4.x, ffmpeg (chromaprint 패키지에 동봉). 신규 PyPI 의존성 0 건 — 기존 `[asr]` / `[dev]` / 기본 surface 안에서 모두 처리. (017-takeout-unified-ingest)
- SQLite v4 (스키마 변경 없음 — spec 013 의 channel_metadata + video_metadata + processing_status + quality_results + comparison_results 보존), JSON atomic write (channel_meta.json, videos_meta.json, channels.json, departments.json, **신규 retry_pending.json**), 감사 CSV (`audit_writer.py` 의 stage `takeout_ingest` + 신규 stage `ingest_orchestrator` / `source_video_cleanup`). (017-takeout-unified-ingest)

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
- 017-takeout-unified-ingest (v0.6.0.dev0, 2026-05-16): collect ingest 통합 명령 (takeout → ASR → fingerprint → retry manifest → optional cleanup) 신설 + retry_pending.json 자동 매니페스트 (FR-015/FR-018) + ffprobe per-mp4 메모이즈로 적재 1061s → 1.7s (SC-001 ≤ 60s 충족) + --delete-source 두 단계 interactive prompt. SQLite v4 스키마 변경 없음. 7 파일 수정 (services/evidence_score.py, services/unified_ingest.py, services/retry_manifest.py, services/source_video_cleanup.py, services/audit_writer.py, models/content.py, cli/collect.py) + 회귀 테스트 11개 (unit/integration/contract).
- 017-takeout-unified-ingest: Added Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`) + typer, rich, pydantic v2, polars, faster-whisper (≥1.0.0, `[asr]` optional extra), CTranslate2 4.x, ffmpeg (chromaprint 패키지에 동봉). 신규 PyPI 의존성 0 건 — 기존 `[asr]` / `[dev]` / 기본 surface 안에서 모두 처리.
- 016-takeout-ingest-rebuild (v0.5.1.dev0, 2026-05-15): Takeout 적재 모듈 재작성 — 결함 11개 수정 (채널 CSV 헤더, privacy 한글 매핑, glob 패턴 등) + `--source youtube` exit 2 deprecation + ASR 단일 경로 기본값 + `admin list` 두 등록부 union 출력 + consistency 컬럼. SQLite v4 스키마 변경 없음. 5 파일 수정 (cli/admin.py, cli/collect.py, services/takeout_ingest.py, services/audit_writer.py, models/content.py) + 회귀 테스트 8개 (unit/integration/contract).
- 016-takeout-ingest-rebuild: Added Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`) + typer, rich, pydantic v2, polars, faster-whisper (≥1.0.0, [asr] optional extra), CTranslate2 4.x, ffmpeg (chromaprint 패키지에 동봉). agenix 환경변수는 OAuth 흐름에서만 선택적 사용. **신규 PyPI 의존성 0건** — 기존 [asr] / [dev] / 기본 surface 안에서 모두 처리.


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
