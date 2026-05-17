# Tube Scout

A toolkit for university lecture-video pipelines. The same CLI serves
three distinct audiences:

1. **Cross-faculty duplication detection** for academic affairs / DX
   centers — finds substantially overlapping lectures across
   instructors or terms.
2. **Transcript-driven CQI support** for faculty members — surfaces
   rewatch hotspots, comment sentiment, EQS scoring, and forecast
   anomalies so an instructor can act on the next teaching cycle.
3. **YouTube caption extraction** for downstream data pipelines —
   collects API captions (with local `faster-whisper` fallback) and
   exports them in `txt` / `md` / `jsonl` formats ready for a
   separate RAG or knowledge-base project.

Each use case has a dedicated walkthrough under
[`docs/use-cases/`](docs/use-cases/).

## Highlights

- **CLI first.** Every capability ships as a `tube-scout …` Typer
  command.
- **Local-first persistence.** JSON + Parquet + SQLite under `data/`
  and `projects/`. No external database server is required.
- **Multi-channel alias system.** One operator manages many
  department channels through
  `~/.config/tube-scout/tokens/{alias}_token.json`.
- **Admin web UI.** A Starlette-based ASGI layer
  (`src/tube_scout/web/`) exposes the same pipelines behind a
  single-account login for non-developer staff.
- **agenix-managed secrets.** Every secret is read from environment
  variables provisioned by agenix; nothing is committed to the
  repository.

## Quickstart

```bash
git clone https://github.com/ecoinfoai/tube-scout.git
cd tube-scout
nix develop          # or: uv sync

# Register a department (one-time)
tube-scout admin add-department --alias nursing --display "Department of Nursing"

# Smallest meaningful run for each use case lives in docs/quickstart.md
tube-scout doctor    # verify the environment first
```

A full walkthrough lives in
[`docs/quickstart.md`](docs/quickstart.md). The complete CLI
reference is in [`docs/tutorial.md`](docs/tutorial.md).

## Architecture

```
src/tube_scout/
├── cli/         # Typer commands (collect/analyze/report/admin/content/transcript)
├── services/    # YouTube API wrappers, ASR, fingerprint, evidence scoring, …
├── reporting/   # HTML / PDF / Excel report generators
├── storage/     # JSON / Parquet / SQLite readers and writers
├── visualization/
└── web/         # Starlette admin UI (routes, middleware, repos, templates)
```

Data and runtime artifacts:

```
data/                                # project-scoped raw + processed + reports
projects/{job-id}/                   # admin-UI run outputs (YYYYMMDD-HHMMSS[-N])
~/.config/tube-scout/                # token files, departments.json
~/.local/share/tube-scout/admin.db   # admin-UI history (SQLite WAL)
```

## Requirements

- Python 3.11+
- `ffmpeg` and `libchromaprint-tools` (provides `fpcalc`) on `PATH`
  for use cases 1 and 3 — the Nix devShell ships both
- A YouTube Data API v3 key (and channel-owner OAuth credentials for
  use case 2's retention / Analytics calls)
- Optional: Anthropic or OpenAI key for LLM-backed sentiment /
  transcript analyses
- Optional: NixOS + agenix for secret management
- Optional: `faster-whisper` (`uv sync --extra asr`) for ASR fallback
  when YouTube captions are missing

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
| [`docs/index.md`](docs/index.md) | Routing — pick a use case |
| [`docs/quickstart.md`](docs/quickstart.md) | Anyone — installs + smallest meaningful run for each use case |
| [`docs/use-cases/01-duplication-detection.md`](docs/use-cases/01-duplication-detection.md) | Academic affairs office, DX center |
| [`docs/use-cases/02-cqi-support.md`](docs/use-cases/02-cqi-support.md) | Faculty members, department chairs |
| [`docs/use-cases/03-caption-extraction.md`](docs/use-cases/03-caption-extraction.md) | Engineers building a downstream data pipeline |
| [`docs/tutorial.md`](docs/tutorial.md) | Engineers and analysts — every command |

## License

MIT — see [`LICENSE`](LICENSE) if present, or contact the maintainers.

## Acknowledgements

Tube Scout is developed at the Busan Health University Department for
Innovation eXperience Support under the RISE programme. Spec / plan /
task documents are produced with the
[Spec Kit](https://github.com/github/spec-kit) workflow.
