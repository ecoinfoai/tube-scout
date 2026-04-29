# Tube Scout

YouTube lecture-video analytics — collect, analyze, and report on lecture
content from a single channel.

Tube Scout is a Python 3.11 CLI plus a thin admin web UI built for educators
and academic departments. It pulls data from the YouTube Data, Captions, and
Analytics APIs (with proper OAuth scopes), runs analyses across audience
retention, transcripts, and comments, and produces HTML / PDF / Excel
reports per video and per channel.

## Where to start

| If you are… | Read |
|-------------|------|
| in a hurry | [Quickstart](quickstart.md) |
| an engineer or analyst | [Tutorial](tutorial.md) |
| an educator who wants outcomes, not commands | [For Educators](for-new-teachers.md) |

## Highlights

- **CLI first** — every capability ships as a `tube-scout …` Typer command.
- **Local-first persistence** — JSON, Parquet, and SQLite under `data/` and
  `projects/`. No external database server required.
- **OAuth-aware** — multi-channel alias system manages many department
  channels through `~/.config/tube-scout/tokens/{alias}_token.json`.
- **Educator-oriented analyses** — rewatch hotspots, skip zones, transcript
  difficulty, comment sentiment / topics / questions, EQS (RACED-axis)
  educational-quality scoring, and time-series forecasting.
- **Admin web UI** — Starlette-based ASGI layer (`src/tube_scout/web/`) puts
  the same pipeline behind a single-account login for non-developer staff.
- **agenix-managed secrets** — every secret is read from environment
  variables provisioned by agenix; nothing is committed to the repository.

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

## Source

The full source is hosted at
[ecoinfoai/tube-scout](https://github.com/ecoinfoai/tube-scout). The
`specs/` directory holds spec-driven development artifacts (one folder per
feature) and the `idea/` directory contains the brainstorming notes that
became those specs.
