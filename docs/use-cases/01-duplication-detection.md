# Use case 1 — Cross-faculty duplication detection

## Audience

Academic affairs office, DX center, department chair — anyone who
must answer the question *"Are any lectures on the department channel
substantially duplicated, either by the same instructor across terms
or across instructors?"*

## What the pipeline produces

- An **HTML + PDF report** that ranks the top suspect lecture pairs.
- For each pair, three independent signals are recorded:
  1. **Caption overlap** — normalized text similarity + longest
     contiguous matching span.
  2. **Time-axis indicators** — distribution, dispersion, and
     positional diversity of matching spans.
  3. **Audio fingerprint** — chromaprint hamming distance over the
     downmixed audio track.
- Reviewer decisions (`CONFIRMED_DUPLICATE`, `FALSE_POSITIVE`,
  `UNREVIEWED`) are persisted in SQLite so the next run can skip
  already-cleared pairs.

## Prerequisites

- A Google Takeout export of the department's YouTube channel that
  contains `Takeout/YouTube and YouTube Music/videos/*.mp4` and the
  metadata CSVs under `Takeout/YouTube and YouTube Music/동영상
  메타데이터/`. Korean directory names are matched as-is.
- `ffmpeg` and `libchromaprint-tools` (provides `fpcalc`) on `PATH`.
  The Nix devShell ships both.
- A registered department alias (see step 1 below).

## Workflow

### 1. Register the department (one-time)

```bash
tube-scout admin add-department \
  --alias nursing \
  --display "Department of Nursing"
```

`admin add-department` creates the department row in `admin.db` and
the per-alias directory under `~/.config/tube-scout/tokens/`. OAuth
credentials are optional for this use case — duplication detection
runs entirely on the Takeout archive.

### 2. Ingest the Takeout archive

```bash
tube-scout collect ingest \
  --takeout-dir /path/to/Takeout-20260511T130817Z-3-001 \
  --channel nursing
```

This single command runs four stages in order:

1. Parse the Takeout CSVs and persist `channel_metadata` +
   `video_metadata` rows.
2. ASR each mp4 with `faster-whisper` (GPU preset auto-detected;
   override with `--preset gpu-quantized` / `cpu`).
3. Extract a chromaprint audio fingerprint per mp4.
4. Update `retry_pending.json` with any failures so a `--resume` run
   re-picks them.

Use `--dry-run` to print the mapping report without writing anything.
Use `--force` to bypass the per-video idempotency guard and
reprocess everything.

### 3. Register the faculty pool

```bash
tube-scout content professor map \
  --professor-id prof-hong \
  --channel-alias nursing \
  --author-marker "홍길동"
```

The `author-marker` is the substring the system uses to recognise a
lecture as belonging to that instructor (e.g. their name as it
appears in the video title). Multiple author markers per professor
are supported with repeated `professor map` calls.

### 4. Scan for suspect pairs

```bash
tube-scout content scan \
  --mode nc2 \
  --professor prof-hong
```

`--mode nc2` performs an n-choose-2 sweep over every video pool the
professor owns. The scan writes candidate pairs into
`02_analyze/content/content_reuse.db`.

For the legacy "compare videos from year X to year Y" workflow, use
`--mode legacy --year-from 2025 --year-to 2026`.

### 5. Apply layer defenses (optional)

Before the report is generated, the pipeline subtracts known
non-duplicate text (lecturer self-introduction, lab safety announcements,
etc.). Bootstrap the baseline corpus and seed the per-professor phrase
whitelist:

```bash
# Baseline corpus from the department's full archive
tube-scout content baseline bootstrap --channel-alias nursing

# Optional per-professor whitelist for stock phrases
tube-scout content whitelist add-phrase \
  --professor-id prof-hong \
  --phrase "안녕하세요 홍길동 교수입니다" \
  --reason "Standard self-introduction"
```

Pairs that a human has already cleared can be added to the pair
whitelist so they never resurface:

```bash
tube-scout content whitelist add-pair \
  --video-a VID00001 --video-b VID00002 \
  --reason "Confirmed: same lecture re-uploaded after audio fix"
```

### 6. Generate the report

```bash
tube-scout report content-reuse \
  --professor prof-hong \
  --mode nc2 \
  --format both
```

This writes:

- `03_report/{professor-id}_nC2_report.html` — sortable table of
  suspect pairs, embedded charts of the time-axis indicators, and
  per-pair caption diff.
- `03_report/{professor-id}_nC2_report.pdf` — the same content
  rendered for archival sharing.

### 7. Review and persist decisions

```bash
tube-scout content review \
  --pair-id VID00001:VID00002 \
  --status CONFIRMED_DUPLICATE \
  --note "Same lecture re-uploaded with re-cut audio"
```

Reviewed pairs are flagged in subsequent scans so the team never
re-reviews the same pair twice.

## Operational tips

- Run the ingest step on a GPU host; ASR is the wall-clock
  bottleneck. The CPU preset works for small archives.
- `retry_pending.json` lives next to the channel's work directory.
  Re-run `tube-scout collect ingest --resume` after fixing the
  underlying failure (missing mp4, transient ASR crash, …).
- `tube-scout doctor` validates the entire dependency surface
  (Python, faster-whisper, LD_LIBRARY_PATH for CUDA, `fpcalc`,
  `ffmpeg`, `sqlite3 >= 3.35`) and exits non-zero with
  `--exit-code` for CI hooks.
- The audit CSV at `_workspace/audit/` records every stage outcome
  so a post-mortem can answer "which mp4 was skipped and why".

## Related references

- [Quickstart](../quickstart.md#scenario-1-duplication-detection)
- [Tutorial — content commands](../tutorial.md#content-commands)
