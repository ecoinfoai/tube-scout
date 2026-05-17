# Quickstart

Installs Tube Scout and runs the smallest meaningful command for each
of the three use cases — about 30 minutes end-to-end if you already
have the input data ready.

If you do not know which use case applies to you, read the
[home page](index.md) first.

---

## 1. Environment setup

### 1.1 Pick a devShell

| Variant | Command | When to use |
|---|---|---|
| direnv (recommended) | Configure `.envrc.local`, then `cd` into the repo | Auto-activates on every shell |
| Manual CPU | `nix develop` | Quick checks; no GPU dependencies |
| Manual GPU | `nix develop .#gpu` | Use case 1 (ASR), use case 3 ASR fallback |

Direnv removes the failure mode where a developer forgets to activate
the right shell; the CUDA libraries follow the devShell automatically.

### 1.2 Enable direnv on a GPU host

```bash
echo 'use flake .#gpu' > .envrc.local
direnv allow
```

`.envrc.local` is gitignored, so each developer manages it
independently.

> **Important.** Right after `direnv allow`, the current shell's
> `LD_LIBRARY_PATH` is *not* updated. Open a new terminal
> (`exec $SHELL`) or run `direnv reload` to pull in the new
> environment. Existing terminals keep their old environment.

CPU hosts simply omit the file (or comment out the `use flake` line):

```bash
echo '# use flake .#gpu' > .envrc.local
direnv allow
```

### 1.3 Verify the environment

```bash
# Confirm you are inside the devShell
echo $IN_NIX_SHELL    # → "impure" (direnv) or "pure" (manual)

# Confirm CUDA libraries are reachable (GPU hosts only)
echo $LD_LIBRARY_PATH | tr ':' '\n' | grep -i cuda

# Full diagnostic — exits non-zero on any FAIL when --exit-code is set
tube-scout doctor
```

A healthy GPU host prints something like:

```
                       tube-scout doctor
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳────────────────────────────┓
┃ 항목                         ┃ 상태   ┃ 세부 정보                  ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━╋────────────────────────────┫
│ Python interpreter           │ PASS   │ 3.11.15 — /path/to/python  │
│ devShell (Nix)               │ PASS   │ IN_NIX_SHELL='impure'      │
│ faster_whisper import        │ PASS   │ v1.2.1                     │
│ LD_LIBRARY_PATH (CUDA)       │ PASS   │ 4/4 CUDA libs resolvable   │
│ which fpcalc                 │ PASS   │ /nix/store/.../fpcalc      │
│ which ffmpeg                 │ PASS   │ /nix/store/.../ffmpeg      │
│ which sqlite3                │ PASS   │ /nix/store/.../sqlite3     │
│ nvidia-smi                   │ PASS   │ /run/.../nvidia-smi        │
│ torch.cuda.is_available      │ PASS   │ True — 1 device(s)         │
│ sqlite3 version              │ PASS   │ 3.51.2                     │
└──────────────────────────────┴────────┴────────────────────────────┘
```

`tube-scout doctor` is the canonical bootstrap check — the column
labels stay in Korean because operations staff read the output.

### 1.4 Install profiles

The dependency surface is split so day-to-day development, CI, and
operator deployments do not pay the cost of the heaviest ML/PDF
stacks unless they are actually used.

| Profile | Command | Adds |
|---|---|---|
| Lean (default) | `uv sync` | core CLI, auth, collect, report (HTML), web admin |
| Dev | `uv sync --extra dev` | + pytest, pytest-cov, pytest-asyncio, pytest-httpx, ruff |
| Sentiment (local) | `uv sync --extra ml-sentiment` | + transformers, torch (~1 GB) |
| Forecasting | `uv sync --extra ml-forecast` | + statsmodels, prophet (~700 MB, Stan compile) |
| PDF reports | `uv sync --extra pdf` | + weasyprint (cairo/pango) |
| Speech-to-text | `uv sync --extra asr` | + faster-whisper (~1.5 GB int8 weights) |
| Everything | `uv sync --all-extras` | every extra above |

All heavy imports in `src/` are function-local; calling a
sentiment / forecast / PDF / ASR code path without the matching extra
raises a clear `ImportError` naming the exact `uv sync --extra …`
recipe.

---

## 2. Register a department (one-time)

Every use case requires at least one registered alias.

```bash
tube-scout admin add-department \
  --alias nursing \
  --display "Department of Nursing"
```

For use case 2 (CQI) you additionally need OAuth env-var bindings:

```bash
tube-scout admin add-department \
  --alias nursing \
  --display "Department of Nursing" \
  --channel-id-env TUBE_SCOUT_CHANNEL_ID_NURSING \
  --client-secret-env TUBE_SCOUT_CLIENT_SECRET_NURSING \
  --api-key-env TUBE_SCOUT_API_KEY_NURSING
```

The env vars themselves are provisioned by agenix — Tube Scout
never stores raw secrets.

---

## 3. Scenario 1 — Duplication detection

The shortest meaningful run (one Takeout archive, one professor):

```bash
# Ingest the archive: parse CSVs, run ASR, extract fingerprints
tube-scout collect ingest \
  --takeout-dir /path/to/Takeout-export \
  --channel nursing

# Register a faculty pool
tube-scout content professor map \
  --professor-id prof-hong \
  --channel-alias nursing \
  --author-marker "홍길동"

# Scan, generate the report
tube-scout content scan --mode nc2 --professor prof-hong
tube-scout report content-reuse --professor prof-hong --mode nc2 --format both
```

The HTML + PDF report appears under
`data/nursing/03_report/prof-hong_nC2_report.{html,pdf}`.

Full walkthrough: [Use case 1 →](use-cases/01-duplication-detection.md)

---

## 4. Scenario 2 — CQI support

```bash
# Pull metadata + comments + retention (retention needs OAuth)
tube-scout collect videos    --channel nursing
tube-scout collect comments  --channel nursing
tube-scout collect retention --channel nursing

# Analyses
tube-scout analyze retention  --channel nursing
tube-scout analyze sentiment  --channel nursing
tube-scout analyze transcript --channel nursing
tube-scout analyze eqs        --channel nursing

# Reports
tube-scout report video   --video-id VIDEO_ID
tube-scout report channel --channel nursing --professor "Jane Smith"
```

Full walkthrough: [Use case 2 →](use-cases/02-cqi-support.md)

---

## 5. Scenario 3 — Caption extraction

```bash
# Fetch transcripts for a list of video IDs (API first, ASR fallback)
tube-scout collect transcripts \
  --channel nursing \
  --video-ids-file ./input/video_ids.txt

# Normalize (NFC, zero-width strip, filler removal, timestamp re-anchor)
tube-scout process normalize-transcripts --channel nursing

# Export for a downstream RAG / KB pipeline
tube-scout transcript export-bulk \
  --transcripts-dir data/nursing/02_analyze/transcripts \
  --output-dir ./output/kb-ingest/ \
  --format jsonl
```

Full walkthrough: [Use case 3 →](use-cases/03-caption-extraction.md)

---

## 6. Common follow-ups

| Need | Command |
|---|---|
| Re-run a failed ingest stage only | `tube-scout collect ingest --resume --channel <alias>` |
| Inspect the audit trail | `_workspace/audit/` (per-stage CSV) |
| Find broken DB symlinks | `tube-scout doctor` (FAIL row names the path) |
| Roll back a CUDA install regression | `nix develop .#gpu` in a fresh shell + `tube-scout doctor` |
| Validate `policy.yaml` for content scan | `tube-scout content policy validate --channel <alias>` |
