# Quickstart: Tube Scout v2 Development

**Date**: 2026-04-04

## Prerequisites

- Python 3.11 (via flake.nix devShell)
- uv (Python package manager)
- Existing v1 tube-scout working installation

## Setup

```bash
# Enter dev environment
nix develop

# Install new dependencies
uv sync

# Verify existing tests still pass
cd src && pytest
```

## New Dependencies to Add

```toml
# pyproject.toml [project.dependencies]
anthropic = ">=0.40.0"        # Claude LLM API
openai = ">=1.50.0"           # GPT-4o LLM API (optional)
statsmodels = ">=0.14.0"      # ARIMA forecasting
prophet = ">=1.1.5"           # Facebook Prophet forecasting
transformers = ">=4.40.0"     # Korean NLP models (local sentiment)
torch = ">=2.2.0"             # PyTorch for transformers inference
```

## Development Order (by priority)

### Phase P1 — Data Collection Foundation

1. **Extended models**: Add new fields to Video, Channel, Comment, CollectionState
2. **Analytics collection**: Implement 8 report types in `youtube_analytics.py`
3. **Extended metadata**: Expand `youtube_data.py` for full video/channel fields
4. **Comment replies**: Add reply collection to `youtube_data.py`
5. **Incremental sync**: Add date tracking to checkpoint system

### Phase P2 — Analysis Core

6. **LLM adapter**: Create `llm_adapter.py` with Claude/GPT-4o support
7. **Sentiment LLM backend**: Implement `backend="llm"` in `sentiment.py`
8. **Sentiment local backend**: Implement `backend="local"` in `sentiment.py`
9. **Topic extractor**: Create `topic_extractor.py`
10. **Transcript segmenter**: Connect LLM to `segmenter.py`

### Phase P3 — Advanced Features

11. **EQS scoring**: Connect LLM to `eqs.py`
12. **ARIMA/Prophet forecaster**: Extend `forecaster.py`
13. **Academic calendar**: Add calendar model and CLI commands
14. **Reporting API**: Create `youtube_reporting.py`

### Phase P3 — Reports

15. **Comment insight report**: Create `comment_report.py`
16. **Channel comprehensive report**: Extend `channel_report.py`
17. **Improvement suggestions**: Add suggestion generation logic

## Running Tests

```bash
# All tests
cd src && pytest

# Specific test file
pytest tests/unit/test_llm_adapter.py

# With coverage
pytest --cov=tube_scout --cov-report=term-missing

# Lint
ruff check .
```

## Key Design Patterns to Follow

1. **Service class + module functions**: Each service is a class with injected client. Helper functions are module-level.
2. **Pydantic v2 models**: All data models use Pydantic with field validators.
3. **Atomic storage**: Use `write_json` / `write_parquet` for atomic writes.
4. **Checkpoint resume**: Extend `CollectionState` for new collection phases.
5. **TDD**: Write tests first (RED), then implement (GREEN), then refactor.
6. **Google docstrings in English**: All functions documented.
7. **Type annotations**: All function parameters and returns typed.
