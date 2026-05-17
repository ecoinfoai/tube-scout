# Tube Scout

A toolkit for university lecture-video pipelines. The same `tube-scout`
CLI now serves three distinct audiences — pick the use case that matches
your role and follow the linked guide.

## Pick your use case

| Use case | Who runs it | What it produces |
|---|---|---|
| **1. Cross-faculty duplication detection** | Academic affairs office / DX center | HTML + PDF report of suspect lecture pairs, scored across captions, time-axis, and audio fingerprint |
| **2. Transcript-driven CQI support** | Faculty member / department chair | Per-video and per-channel analytics on retention, sentiment, transcript difficulty, and educational quality |
| **3. YouTube caption extraction** | Engineer building another data pipeline | Clean transcript JSON / Markdown / JSONL that a downstream project can ingest |

For each use case there is a dedicated walkthrough:

- [Duplication detection →](use-cases/01-duplication-detection.md)
- [CQI support →](use-cases/02-cqi-support.md)
- [Caption extraction →](use-cases/03-caption-extraction.md)

If you only have 10 minutes, the [Quickstart](quickstart.md) installs
the toolkit and runs the smallest meaningful command for each use case.
The [Tutorial](tutorial.md) is the long-form CLI reference for engineers
who want every flag and every output path.

## What is the same across all three use cases

- **CLI first** — every capability ships as a `tube-scout …` Typer
  command. No required GUI.
- **Local-first persistence** — JSON, Parquet, and SQLite under
  `data/` and `projects/`. No external database server.
- **Multi-channel alias system** — one operator manages many
  department channels through
  `~/.config/tube-scout/tokens/{alias}_token.json`.
- **Optional admin web UI** — a Starlette-based ASGI layer
  (`src/tube_scout/web/`) exposes the same pipelines behind a
  single-account login for non-developer staff.
- **agenix-managed secrets** — every secret is read from environment
  variables provisioned by agenix; nothing is committed to the
  repository.

## What is different across the three use cases

| Use case | Heaviest dependency | Typical input | Typical output |
|---|---|---|---|
| 1. Duplication detection | `faster-whisper` (ASR) + `fpcalc` (audio fingerprint) | A Google Takeout archive of the department channel | `02_analyze/content/`, HTML + PDF report under `03_report/` |
| 2. CQI support | YouTube Data + Analytics + Captions APIs (OAuth) | A registered department channel + faculty filter | `report/video/`, `report/channel/`, per-axis CSV / HTML |
| 3. Caption extraction | YouTube Captions API (no OAuth required for auto-generated captions) | A list of video IDs or a channel ID | Transcript files in `txt` / `md` / `jsonl` formats |

## Architecture

```
src/tube_scout/
├── cli/         # Typer commands (collect/analyze/report/admin/content/transcript)
├── services/    # YouTube API wrappers, ASR, fingerprint, evidence scoring, …
├── reporting/   # HTML, PDF, Excel report generators
├── storage/     # JSON, Parquet, SQLite readers and writers
├── visualization/
└── web/         # Starlette admin UI (routes, middleware, repos, templates)
```

## Source

The full source lives at
[ecoinfoai/tube-scout](https://github.com/ecoinfoai/tube-scout).
