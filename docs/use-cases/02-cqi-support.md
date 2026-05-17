# Use case 2 — Transcript-driven CQI support

## Audience

A faculty member or department chair who wants data to drive
**continuous quality improvement (CQI)** of their lecture videos.
The pipeline answers questions like *"Which segments do students
rewatch?"*, *"What are they asking in the comments?"*, and *"How
does this video compare to the rest of my channel on educational
quality?"*.

Tube Scout does not pretend to evaluate teaching itself; it surfaces
the data so the instructor can decide what to change.

## What the pipeline produces

- **Per-video HTML report** — retention curve, rewatch hotspots,
  skip zones, transcript chapters, EQS (RACED 5-axis) score.
- **Per-channel HTML report** — side-by-side comparison across all
  videos belonging to one instructor.
- **Comment insights** — sentiment, topics, auto-extracted student
  questions cross-referenced with retention hotspots.
- **Forecast + anomaly report** — view-count trend with confidence
  intervals, plus flagged spikes (exam weeks) and drops (breaks).

## Prerequisites

- A registered department channel (see use case 1, step 1).
- OAuth credentials for the channel owner role — retention,
  Analytics, and Captions APIs all require this scope. Add them
  with `--channel-id-env`, `--client-secret-env`, and
  `--api-key-env` on `admin add-department`.
- For LLM-backed analyses (sentiment, transcript chapters), an
  Anthropic or OpenAI key in the operator environment via agenix.

## Scenarios

### Scenario 1 — "Show my own videos and their basic metrics"

```bash
tube-scout collect videos --channel nursing
tube-scout list --channel nursing --professor "Jane Smith" \
    --sort view_count --limit 30
```

You see the videos that contain your name, sorted by view count,
with likes / comments / length in one table.

### Scenario 2 — "Where do students get stuck?"

```bash
tube-scout collect retention --channel nursing
tube-scout analyze retention --video-id VIDEO_ID
tube-scout report video --video-id VIDEO_ID
```

The retention analysis surfaces:

- **Rewatch hotspots** — segments students replay. Often the hard
  parts.
- **Skip zones** — segments students skip. Often the irrelevant or
  slow-paced parts.
- The full retention curve so the overall flow is visible.

| Finding | Interpretation | Action |
|---|---|---|
| Rewatch hotspot at 15:00–18:00 | Concept explanation is hard | Add a supplementary clip or on-screen diagram |
| Skip zone at 25:00–30:00 | Historical background drags | Trim or split into a separate video |
| Steep drop in the first 3 min | Intro is too long | Start with the core content sooner |

### Scenario 3 — "Summarize the comments and the questions"

```bash
tube-scout collect comments --channel nursing
tube-scout analyze sentiment --channel nursing
tube-scout report comment-insight --video-id VIDEO_ID
```

The comment-insight report extracts:

- **Sentiment** — positive / negative / neutral ratio.
- **Topics** — clustered themes (e.g. "exam scope", "slide
  errors", "thanks for the explanation").
- **Auto-extracted questions** — only the comments shaped like
  *"Could you re-explain X?"* or *"Will this be on the exam?"*.
- **Cross-references** — when a question topic aligns with a
  retention hotspot, both are linked in the report so the
  instructor sees the strongest signal first.

### Scenario 4 — "Vet an upcoming lecture's transcript before recording"

```bash
tube-scout collect transcripts --video-id PREVIOUS_VIDEO_ID \
    --channel nursing
tube-scout analyze transcript --video-id PREVIOUS_VIDEO_ID
```

For each chapter the analysis reports:

- **Automatic chapter splits** — natural topic boundaries.
- **Per-chapter summaries** — gist in one or two sentences.
- **Difficulty scores** — vocabulary and concept density, 0.0–1.0.
- **Topic tags** — keywords.

Chapters above 0.7 difficulty are flagged so the instructor can
plan visuals, animations, or step-by-step explanations before
the next recording.

### Scenario 5 — "Plan operations across the term"

```bash
tube-scout analyze forecast --channel nursing
tube-scout report channel --channel nursing
```

The forecast model (ARIMA / Prophet, requires ~6 months of
history) predicts the next 30 days of view counts with
confidence intervals and flags anomalies:

```
2026-04-15 to 04-22: views +320%  → midterm week
2026-06-20 to 07-31: views −85%   → summer break
2026-09-01 to 09-07: views +250%  → first week of fall semester
```

Operational responses the data tends to support:

- Upload "key-points review" videos two weeks before exams.
- Upload "preview / get-ready" content during breaks.
- Use orientation videos in the first week of term to attract new
  students.

### Scenario 6 — "Educational-quality scoring"

```bash
tube-scout analyze eqs --video-id VIDEO_ID
```

EQS evaluates the lecture on the RACED 5-axis rubric:

| Axis | Meaning | Action when low |
|---|---|---|
| **R**elevance | Aligned with the stated learning goal | State the learning goal explicitly at the start |
| **A**ccuracy | Content is correct | Cross-check against current textbooks and papers |
| **C**larity | Easy to follow | Define jargon on-screen, add visuals |
| **E**ngagement | Students stay attentive | Ask questions, embed quizzes, show worked examples |
| **D**epth | Topic is treated thoroughly | Add advanced material or related cases |

The output renders each axis as a bar chart and surfaces the
lowest-scoring axis as the recommended next CQI cycle target.

### Scenario 7 — "Compare lecture formats"

```bash
tube-scout collect all --channel nursing
tube-scout analyze all --channel nursing
tube-scout report channel --channel nursing --professor "Jane Smith"
```

The channel report includes a side-by-side comparison table across
all videos of one instructor (format, length, views, hotspot
count, skip count, EQS). Patterns the data often reveals:

- Shorter videos (15–25 min) typically outperform longer ones
  (45 min) on both views and EQS.
- Hands-on demo videos tend to have the fewest hotspots and
  skips — students stay attentive.
- Slide-format lectures often score higher on Clarity than
  chalk-talk format.

### Scenario 8 — "I just uploaded my first video"

```bash
# Step 1 — see the lay of the land (5 min)
tube-scout collect videos --channel nursing
tube-scout list --channel nursing --professor "Your Name"

# Step 2 — see what students say (10 min)
tube-scout collect comments --channel nursing
tube-scout analyze sentiment --channel nursing

# Step 3 — full report for the first video (5 min)
tube-scout report video --video-id FIRST_VIDEO_ID
```

`collect videos` + `list` is enough to start. Once you have 10+
videos, `report channel` gives the wider picture. Retention
analysis requires channel-owner permissions — coordinate with the
department channel admin.

## Frequently asked questions

### Can I analyze videos by other instructors?

Basic metrics (views, likes, comments) work for any public video.
Audience retention requires channel-owner permissions, so it is
available only on the channels you administer.

### Can private videos be analyzed?

Private videos cannot be reached through the public APIs. Some
unlisted videos work if you already know the video ID.

### Are there API costs?

The YouTube Data API is free under the standard 10,000-unit
daily quota. If you use an LLM provider for sentiment or
transcript analysis, you pay a small amount — roughly $0.02 per
1,000 comments.

### My channel has hundreds of videos and I keep hitting the quota.

When the quota runs out mid-collection, Tube Scout persists
progress automatically. Re-run the same command the next day and
it resumes from where it stopped.

### My department channel has many faculty members. Can I filter just my videos?

Yes — pass `--professor "Your Name"`. Videos that do not contain
your name are skipped from the report.

### What about videos without subtitles?

Tube Scout uses YouTube's auto-generated captions when available.
If captions are missing and `faster-whisper` (speech recognition)
is installed, it generates captions automatically. If neither path
works, transcript analysis is skipped for that video and the
remaining analyses still run.

## Related references

- [Quickstart](../quickstart.md#scenario-2-cqi-support)
- [Tutorial — analyze + report commands](../tutorial.md#4-data-analysis-analyze)
