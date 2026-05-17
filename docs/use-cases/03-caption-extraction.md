# Use case 3 — YouTube caption extraction for downstream consumers

## Audience

Engineers building **another** data pipeline (RAG, knowledge base,
research corpus, accessibility tooling) who need clean lecture
transcripts and want a stable, scriptable extractor — not an
analytics product.

Tube Scout is positioned as the caption acquisition layer; semantic
analysis of the captions happens in your downstream project.

## What this pipeline produces

- **Per-video transcript JSON** under
  `data/{channel}/02_analyze/transcripts/{video_id}.json` with
  segments, timestamps, language, and quality flags.
- **Export bundles** in `txt`, `md`, or `jsonl` formats ready to be
  ingested by a downstream RAG / KB pipeline.
- **Source provenance** — every transcript records whether it came
  from the YouTube auto-generated captions API or from local
  faster-whisper ASR fallback. Downstream consumers can filter on
  source quality.

## Prerequisites

- A YouTube Data API key (caption fetch). Auto-generated captions
  do **not** require channel-owner OAuth.
- For private / unlisted videos: channel-owner OAuth on the
  registered alias.
- For ASR fallback (videos with captions disabled by the uploader):
  `faster-whisper` from the `[asr]` extra, plus `ffmpeg` on
  `PATH`. The Nix devShell ships both.

## Workflow

### 1. Fetch captions for a video list

```bash
tube-scout collect transcripts \
  --channel nursing \
  --video-ids-file ./input/video_ids.txt
```

`--video-ids-file` accepts one video ID per line. The collector:

1. Tries the YouTube Captions API first.
2. Falls back to local ASR (`faster-whisper`) when captions are
   disabled or auto-generated tracks are unavailable.
3. Writes one JSON per video under
   `data/{channel}/02_analyze/transcripts/{video_id}.json`.
4. Records the source (`api:auto` / `asr:faster-whisper:large-v3`)
   in each file so downstream code can branch on quality.

To pull every video in the channel instead, omit
`--video-ids-file` and add `--all`.

### 2. Normalize the transcripts

```bash
tube-scout process normalize-transcripts \
  --channel nursing
```

Normalization performs:

- Unicode NFC + zero-width-character stripping.
- Filler removal (configurable, defaults targeted at Korean ASR
  hallucinations like `"음 어 그"`).
- Timestamp re-anchoring so adjacent segments do not overlap.

The output is written next to the raw transcript with a
`.normalized.json` suffix. Idempotent: a second run on the same
file is a no-op unless `--force` is passed.

### 3. Export in a downstream-friendly format

```bash
# Single video, plain text with timestamps
tube-scout transcript export \
  --video-id VIDEO_ID \
  --format txt \
  --keep-timestamps \
  --output-dir ./output/transcripts/

# Bulk export, Markdown with cleaned fillers
tube-scout transcript export-bulk \
  --transcripts-dir data/nursing/02_analyze/transcripts \
  --output-dir ./output/kb-ingest/ \
  --format md \
  --clean-fillers

# JSONL for direct chunking + embedding
tube-scout transcript export-bulk \
  --transcripts-dir data/nursing/02_analyze/transcripts \
  --output-dir ./output/kb-ingest/ \
  --format jsonl
```

Available `--format` values:

| Format | Shape | Best fit |
|---|---|---|
| `txt` | Plain UTF-8, one segment per line, optional `[hh:mm:ss]` prefix | Human review, grep, lightweight diff |
| `md` | Markdown with `## Chapter` headings (if chapters present) and optional timestamps | Documentation, static-site ingest |
| `jsonl` | One JSON object per segment: `{"start", "end", "text", "video_id"}` | Direct chunking + embedding pipelines |

### 4. Re-run for newly added videos

`collect transcripts` is per-video idempotent. Pointing the same
command at an updated `video_ids.txt` only fetches the IDs that do
not yet have a transcript JSON on disk. Add `--force` to
re-fetch.

## Quality flags downstream consumers should respect

Each transcript JSON includes an `asr_quality_flags` object when
the source is ASR:

| Flag | Meaning | Downstream action |
|---|---|---|
| `hallucination_repeat` | The same n-gram repeats abnormally often | Drop or quarantine the segment |
| `vad_over_truncated` | VAD removed >50% of the audio | Re-extract with VAD disabled |
| `language_mismatch` | Detected language ≠ expected | Skip non-target-language chunks |
| `short_segments_excess` | More than 30% of segments are < 1 sec | Treat as low confidence |
| `silence_hallucination` | ASR produced text over a silent span | Drop the segment |
| `compression_ratio_violations` | Whisper compression-ratio sanity check failed N times | Inspect; usually drop |

API-sourced transcripts carry no quality flags — YouTube does
not expose them. Downstream consumers can treat
`source.startswith("api:")` as a higher-trust baseline.

## What this pipeline deliberately does **not** do

- **No embedding generation.** Vectorization, chunking strategy,
  and chunk overlap belong in the downstream project.
- **No semantic analysis.** Topic modeling, summarization, and
  question generation are out of scope for this use case (use
  use case 2 if you want analytics).
- **No long-term archival.** `data/{channel}/02_analyze/` is the
  staging area; downstream consumers are responsible for moving
  approved transcripts into their own store.

## Related references

- [Quickstart](../quickstart.md#scenario-3-caption-extraction)
- [Tutorial — collect + transcript commands](../tutorial.md#3-data-collection-collect)
