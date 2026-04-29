# Tube Scout

YouTube lecture-video analytics — collect, analyze, and report on lecture
content from a single channel.

Tube Scout is a Python 3.11 CLI plus a thin admin web UI built for educators
and academic departments. It pulls data from the YouTube Data, Captions, and
Analytics APIs (with proper OAuth scopes), runs analyses across audience
retention, transcripts, and comments, and produces HTML / PDF / Excel
reports per video and per channel.

## Highlights

- **CLI first.** Every capability ships as a `tube-scout …` Typer command.
- **Local-first persistence.** JSON + Parquet + SQLite under `data/` and
  `projects/`. No external database server is required.
- **OAuth-aware.** Multi-channel alias system lets one operator manage many
  department channels through `~/.config/tube-scout/tokens/{alias}_token.json`.
- **Educator-oriented analyses.** Rewatch hotspots, skip zones, transcript
  difficulty estimation, comment sentiment / topics / questions, EQS
  (RACED-axis) educational-quality scoring, and time-series forecasting.
- **Admin web UI.** A Starlette-based ASGI layer (`src/tube_scout/web/`)
  exposes the same pipeline behind a single-account login for non-developer
  staff. See `docs/quickstart.md` and `docs/tutorial.md`.
- **agenix-managed secrets.** Every secret is read from environment
  variables provisioned by agenix; nothing is committed to the repository.

## Quickstart

```bash
git clone https://github.com/ecoinfoai/tube-scout.git
cd tube-scout
nix develop          # or: uv sync

export YOUTUBE_API_KEY="AIzaSy..."
tube-scout init --channel-id "UCxxxxxxxxxx" --professor "Jane Smith"
tube-scout collect videos
tube-scout list --sort view_count --limit 10
```

A full walkthrough lives in [`docs/quickstart.md`](docs/quickstart.md). For
the complete command reference and advanced workflows, read
[`docs/tutorial.md`](docs/tutorial.md). Educator-focused recipes are in
[`docs/for-new-teachers.md`](docs/for-new-teachers.md).

## Architecture

```
src/tube_scout/
├── cli/         # Typer commands (init/status/list/collect/analyze/report/admin)
├── services/    # YouTube Data, Analytics, Captions wrappers + analysis services
├── reporting/   # HTML / PDF / Excel report generators
├── storage/     # JSON / Parquet readers and writers
├── visualization/
└── web/         # Starlette admin UI (routes, middleware, repos, templates)
```

Data and runtime artifacts:

```
data/                 # project-scoped raw + processed + reports
projects/{job-id}/    # admin-UI run outputs (YYYYMMDD-HHMMSS[-N])
~/.config/tube-scout/ # token files, departments.json
~/.local/share/tube-scout/admin.db  # admin-UI history (SQLite WAL)
```

## Requirements

- Python 3.11+
- A YouTube Data API v3 key (and optional OAuth credentials for retention)
- Optional: Anthropic or OpenAI key for LLM-backed sentiment / transcript
  analyses
- Optional: NixOS + agenix for secret management
- Optional: Whisper for speech-to-text fallback when transcripts are missing

## Running tests

```bash
uv run pytest                                                 # full suite
uv run pytest tests/contract tests/integration -q             # routes + flows
uv run pytest --cov=tube_scout.web --cov-report=term-missing  # coverage
uv run ruff check . && uv run ruff format --check .
```

## Documentation

| Document | Audience |
|----------|----------|
| [`docs/quickstart.md`](docs/quickstart.md) | Anyone — five-minute first run |
| [`docs/tutorial.md`](docs/tutorial.md) | Engineers and analysts — every command |
| [`docs/for-new-teachers.md`](docs/for-new-teachers.md) | Educators — scenario-based usage |

The `specs/` directory holds the spec-driven development artifacts (one
folder per feature, each with `spec.md`, `plan.md`, `tasks.md`,
`research.md`, `data-model.md`, `contracts/`, and `quickstart.md`). The
`idea/` directory contains the brainstorming notes that became those specs.

## License

MIT — see [`LICENSE`](LICENSE) if present, or contact the maintainers.

## Acknowledgements

Tube Scout is developed at the Busan Health University Department for
Innovation eXperience Support (DX지원센터) under the RISE programme. Spec /
plan / task documents are produced with the [Spec
Kit](https://github.com/github/spec-kit) workflow.
