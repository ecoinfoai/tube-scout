# Quickstart

Get Tube Scout configured and run your first analysis in five minutes.

## 1. Prerequisites

- Python 3.11 or newer
- A YouTube Data API v3 key (issue one at the [Google Cloud Console](https://console.cloud.google.com/apis/credentials))

## 2. Install

```bash
git clone https://github.com/ecoinfoai/tube-scout.git
cd tube-scout

# NixOS users
nix develop

# Or install directly with uv
uv sync
```

## 3. Environment variables

```bash
# YouTube Data API key (required)
export YOUTUBE_API_KEY="AIzaSy..."

# LLM API key (optional — needed for sentiment / transcript analysis)
export ANTHROPIC_API_KEY="sk-ant-..."
# or
export OPENAI_API_KEY="sk-..."
```

> When you use NixOS with agenix, the `flake.nix` devShell injects these
> automatically.

## 4. Initialize a project

```bash
tube-scout init \
  --channel-id "UCxxxxxxxxxxxxxxxxxx" \
  --professor "Jane Smith"
```

- `--channel-id`: the YouTube channel ID (a 24-character string starting with `UC`)
- `--professor`: the instructor name to filter video titles by

You can find the channel ID on the YouTube channel page URL, or with any
"YouTube channel ID lookup" utility.

## 5. Collect data

```bash
# Collect the video list and basic metrics
tube-scout collect videos
```

This step lists every video on the channel whose title contains the supplied
professor name and records view count, likes, comment count, and duration.

## 6. Inspect results

```bash
# Show the collected videos
tube-scout list

# Top 10 by view count
tube-scout list --sort view_count --limit 10

# Current project status
tube-scout status
```

## 7. Optional collection steps

```bash
# Comments
tube-scout collect comments

# Transcripts
tube-scout collect transcripts

# Audience retention (requires owner OAuth)
tube-scout collect retention

# Or collect everything in one go
tube-scout collect all
```

## 8. Run analyses

```bash
# Retention analysis (rewind / skip segment detection)
tube-scout analyze retention

# Comment sentiment, topics, and questions
tube-scout analyze sentiment

# Transcript chapter splitting and difficulty estimation
tube-scout analyze transcript

# Or run every analysis at once
tube-scout analyze all
```

## 9. Generate reports

```bash
# Per-video report
tube-scout report video --video-id "xxxxxxxxxxx"

# Channel-wide report
tube-scout report channel

# Export to Jupyter notebook
tube-scout report video --format notebook
```

Reports land under `data/reports/`. Open the HTML file in your browser to view
each report.

## End-to-end workflow

```
init → collect videos → list (verify)
     → collect comments    → analyze sentiment
     → collect transcripts → analyze transcript
     → collect retention   → analyze retention
     → report video / report channel
```

Every step runs independently. If a step is missing earlier data, the CLI
prints a guiding message instead of failing silently.

## API quota exhaustion

The YouTube Data API has a daily quota of 10,000 units. When the quota is
exceeded mid-collection, Tube Scout saves progress and exits gracefully.

```bash
# Resume collection on the next day (resumes automatically)
tube-scout collect videos

# Restart from scratch
tube-scout collect videos --force-refresh
```
