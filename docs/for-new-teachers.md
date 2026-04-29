# Tube Scout for Educators

Posting lecture videos to YouTube? Tube Scout shows you, with data, **how**
your students actually watch the videos and gives you concrete suggestions for
making **better lectures next time**.

This document walks through Tube Scout in real teaching scenarios.

---

## Scenario 1: "I want to see, at a glance, how many of my videos are on the channel and how much they are being watched"

### Situation

Your department's YouTube channel hosts videos from many faculty members.
You want to filter only the videos with your name and review view counts,
likes, and other basic metrics in one place.

### Solution

```bash
# 1. One-time setup
tube-scout init --channel-id "UCxxxxxxxxxx" --professor "Jane Smith"

# 2. Collect the videos
tube-scout collect videos

# 3. Top results, sorted by views
tube-scout list --sort view_count --limit 30
```

### What you learn

- How many videos contain your name
- Which videos are watched the most
- Likes and comments side by side
- Distribution of video lengths

### Tip

Compare your highest-viewed and lowest-viewed videos. Look for patterns in
title, length, and topic — that is where your audience is telling you what
works.

---

## Scenario 2: "I want to know which parts of my lecture students struggle with"

### Situation

You posted a 50-minute anatomy lecture, but students often drop off in the
middle. You want to pinpoint which segments are the problem.

### Solution

```bash
# 1. Collect retention data (channel-owner OAuth required)
tube-scout collect retention

# 2. Analyze retention
tube-scout analyze retention --video-id "VIDEO_ID"

# 3. Visualize as a report
tube-scout report video --video-id "VIDEO_ID"
```

### What you learn

- **Rewatch hotspots**: segments students replay → "hard to understand"
- **Skip zones**: segments students skip → "irrelevant or boring"
- The full retention curve so you can read the overall flow

### How to act on it

| Finding | Meaning | Action |
|---------|---------|--------|
| Rewatch hotspot at 15:00–18:00 | Muscle-contraction explanation is hard | Add a supplementary clip or visuals |
| Skip zone at 25:00–30:00 | Historical background is dragging | Trim or move to a separate video |
| Steep drop in the first 3 minutes | Intro is too long | Get to the core content faster |

### Note

Retention data requires **channel owner / manager** permissions. Ask your
department channel admin for YouTube Analytics API access.

---

## Scenario 3: "I want comments and questions summarized automatically"

### Situation

Each video collects dozens of comments. You do not have time to read every
one. You want to extract just the questions and get a feel for the overall
reaction.

### Solution

```bash
# 1. Collect comments
tube-scout collect comments

# 2. Auto-classify sentiment, topics, and questions
tube-scout analyze sentiment

# 3. For a single video
tube-scout analyze sentiment --video-id "VIDEO_ID"
```

### What you learn

- **Sentiment**: ratio of positive / negative / neutral reactions
- **Topics**: themes discussed in the comments (for example, "exam scope",
  "slide errors", "thanks for the explanation")
- **Auto-extracted questions**: only the comments that ask things like
  "Could you re-explain this?" or "Will this be on the exam?"

### Cross-analysis example

Extracted questions are cross-referenced with rewatch hotspots:

```
[Cross-analysis result]
- Topic: "proximal-tubule reabsorption" → rewatch hotspot 12:30–15:00
  3 student questions: "I'm confused about reabsorption",
                       "What's the difference between active and passive transport?"
  → This segment needs supplementary explanation.
```

---

## Scenario 4: "I want to vet the structure of an upcoming video before I record it"

### Situation

Next week you will record a "Circulatory system" lecture. Before recording,
you want to use the script (or the transcript of an earlier lecture) to
predict which sections will feel difficult.

### Solution

```bash
# Analyze the transcript of an earlier video
tube-scout collect transcripts --video-id "PREVIOUS_VIDEO_ID"
tube-scout analyze transcript --video-id "PREVIOUS_VIDEO_ID"
```

### What you learn

- **Automatic chapter splits**: natural topic boundaries in the video
- **Per-chapter summaries**: the gist of each chapter
- **Difficulty scores**: based on vocabulary and concept density (0.0 = easy,
  1.0 = very hard)
- **Topic tags**: keywords for each chapter

### Example output

```
[Transcript analysis]
Chapter 1: "Heart anatomy"            (0:00–8:30)  — difficulty 0.3 (easy)
Chapter 2: "Cardiac conduction"       (8:30–15:00) — difficulty 0.7 (hard)        ← attention
Chapter 3: "Blood-pressure regulation"(15:00–22:00)— difficulty 0.8 (very hard)   ← supplement needed
Chapter 4: "Recap"                    (22:00–25:00)— difficulty 0.2 (easy)
```

For chapters above 0.7, consider adding **visuals, animation, or step-by-step
explanations**.

---

## Scenario 5: "I want to understand the term-to-term viewing trend so I can plan operations"

### Situation

You uploaded videos consistently for a semester. You want to see whether
viewership spikes during exams and dips during breaks, and use that to plan
upload strategy for the next term.

### Solution

```bash
# Forecast (requires 6+ months of data)
tube-scout analyze forecast

# Inspect the trend in the channel report
tube-scout report channel
```

### What you learn

- **Forecast** of view counts for the next 30 days, with confidence intervals
- **Anomaly detection**: spikes during exam weeks, drops during breaks
- **Term-cycle patterns**: differences between early / mid / late semester

### Example

```
[Anomaly detection]
- 2025-04-15 to 04-22: views up 320%   → midterm week
- 2025-06-20 to 07-31: views down 85%  → summer break
- 2025-09-01 to 09-07: views up 250%   → first week of fall semester
```

**Strategy ideas**:

- Upload "key-points review" videos two weeks before exams
- Upload "preview / get-ready" content during breaks
- Use orientation videos in the first week to attract new students

---

## Scenario 6: "I want my videos evaluated objectively for educational quality"

### Situation

A high view count does not mean a great lecture. You want an objective
measure of how educationally effective your video is.

### Solution

```bash
# Per video
tube-scout analyze eqs --video-id "VIDEO_ID"

# All videos at once
tube-scout analyze eqs
```

### What you learn

The RACED 5-axis evaluation:

| Axis | Meaning | If the score is low |
|------|---------|---------------------|
| **R**elevance | Aligned with the learning goal | State the learning goal at the start |
| **A**ccuracy | Content is correct | Cross-check with current textbooks and papers |
| **C**larity | Easy to understand | Define jargon on screen, add visuals |
| **E**ngagement | Students stay attentive | Ask questions, embed quizzes, show examples |
| **D**epth | Topic is covered well | Add advanced material, related cases |

### Example

```
[EQS result]
Relevance:   0.85 ■■■■■■■■░░
Accuracy:    0.92 ■■■■■■■■■░
Clarity:     0.58 ■■■■■░░░░░  ← needs improvement
Engagement:  0.65 ■■■■■■░░░░  ← needs improvement
Depth:       0.78 ■■■■■■■░░░
Overall:     0.76
```

Low Clarity → "Show definitions on screen when you introduce difficult terms."

---

## Scenario 7: "I want to compare videos and find the most effective lecture style"

### Situation

You recorded the same subject in different formats — chalk talk, slide
lecture, hands-on demo. You want a data-backed comparison of which format is
most effective for students.

### Solution

```bash
# Collect and analyze everything
tube-scout collect all
tube-scout analyze all

# Compare in the channel report
tube-scout report channel
```

### What you learn

The channel report includes a side-by-side table:

| Video | Format | Length | Views | Hotspots | Skips | EQS |
|-------|--------|--------|-------|----------|-------|-----|
| Anatomy 1 | Chalk talk | 45 min | 2,340 | 5 | 3 | 0.72 |
| Anatomy 2 | Slides | 25 min | 3,120 | 2 | 1 | 0.81 |
| Anatomy lab | Demo | 15 min | 4,560 | 1 | 0 | 0.88 |

Insights you can read off the data:

- Shorter videos (15–25 min) outperform longer ones (45 min) on both views
  and EQS
- Demo videos have the fewest hotspots and skips → highest student attention
- Slide format scores higher on Clarity than chalk-talk format

---

## Scenario 8: "I'm new to teaching on video and don't know where to start"

### Situation

You uploaded your first lecture to the department channel. You want to check
how students are watching and what to improve, but YouTube Studio is
overwhelming.

### Step-by-step

**Step 1 — Lay of the land (5 minutes)**

```bash
tube-scout init --channel-id "DEPARTMENT_CHANNEL_ID" --professor "Your Name"
tube-scout collect videos
tube-scout list
```

That alone gives you views / likes / comments for every video of yours.

**Step 2 — Student reactions (10 minutes)**

```bash
tube-scout collect comments
tube-scout analyze sentiment
```

You will see what students say and what they ask, organized for you.

**Step 3 — Comprehensive report (5 minutes)**

```bash
tube-scout report video --video-id "FIRST_VIDEO_ID"
```

Open the HTML report in a browser. You get a single page with summary
metrics and improvement suggestions.

### Tips for first-time uploaders

- `collect videos` + `list` is enough to start
- Once you have 10+ videos, run `report channel` for a wider view
- Retention analysis (`collect retention`) needs channel-admin permission;
  ask your department TA or channel admin for help

---

## FAQ

### Q: Can I analyze videos by other instructors?

Basic metrics (views, likes, comments) work for any public video. Only
audience retention requires channel-owner permissions.

### Q: Can private videos be analyzed?

Private videos cannot be reached via the API. Some unlisted videos can be
collected if you know the video ID.

### Q: Are there API costs?

The YouTube Data API is free (subject to a 10,000-unit daily quota). If you
use an LLM provider for sentiment / transcript analysis, you pay a small
amount (about $0.02 per 1,000 comments).

### Q: My channel has hundreds of videos and I keep hitting the quota.

When the quota runs out mid-collection, Tube Scout saves progress
automatically. Run the same command the next day and it resumes from where
it stopped.

### Q: My channel has many faculty members. Can I filter only my videos?

Yes — use `--professor` with your name. Videos that do not contain your name
are skipped.

### Q: What about videos without subtitles?

Tube Scout uses YouTube's auto-generated captions when available. If
captions are missing and Whisper (speech recognition) is installed, it
generates captions automatically. If neither path works, the transcript
analysis is skipped for that video and the rest of the analyses still run.
