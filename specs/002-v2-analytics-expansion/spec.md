# Feature Specification: Tube Scout v2 Analytics Expansion

**Feature Branch**: `002-v2-analytics-expansion`
**Created**: 2026-04-03
**Status**: Draft
**Input**: User description: "idea/idea2.md — Tube Scout v2: extended data collection, comment analysis, LLM integration, advanced forecasting, and reporting"

## Clarifications

### Session 2026-04-03

- Q: Should academic calendar patterns (FR-021) be auto-detected from data or user-provided? → A: User provides academic calendar dates (semester start/end, exam weeks) as input. Auto-detection may be added later as an enhancement.
- Q: What is the default historical window for daily analytics collection? → A: Default to last 2 years, with a user-configurable start date override.
- Q: Which LLM provider is the default and how are multiple providers handled? → A: Claude as default, configurable to GPT-4o via environment variable. Single adapter with provider selection, not multi-provider orchestration.
- Q: Is sentiment backend fallback automatic or user-selected? → A: User explicitly selects backend per run (default: LLM), no automatic fallback. Clear error if selected backend is unavailable.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Comprehensive Analytics Data Collection (Priority: P1)

As a channel owner, I want to collect all available YouTube Analytics data (traffic sources, demographics, devices, daily time series, playback locations, subscriber changes, engagement metrics) so that I have a complete dataset for analysis and forecasting.

**Why this priority**: Without comprehensive data collection, all downstream analysis features (forecasting, comparisons, reports) lack input data. This is the foundation for every other feature.

**Independent Test**: Can be fully tested by running the collection command for a configured channel and verifying that all analytics report types are stored with correct dimensions and metrics. Delivers immediate value by making previously inaccessible data available for manual inspection.

**Acceptance Scenarios**:

1. **Given** a channel is initialized with OAuth credentials, **When** the user runs the analytics collection command, **Then** the system collects and stores daily time-series data (views, watch time, average duration, average percentage) for the last 2 years by default (or from a user-specified start date).
2. **Given** a channel is initialized with OAuth credentials, **When** the user runs the analytics collection command, **Then** the system collects and stores traffic source, demographics, geography, device, and playback location reports.
3. **Given** the collection has been run before, **When** the user runs it again, **Then** only new data since the last collection is fetched (incremental collection).
4. **Given** the YouTube API returns an error or rate limit, **When** the collection encounters the error, **Then** the system retries with backoff and resumes from the last checkpoint.

---

### User Story 2 - Extended Video and Channel Metadata (Priority: P1)

As a channel owner, I want to collect complete video metadata (description, tags, category, thumbnail URL, language, privacy status, topic categories, caption availability) and extended channel info (subscriber count, total views, description) so that I can perform richer filtering and comparison.

**Why this priority**: Enriched metadata enables video comparison by topic/format/length and is required for LLM-based analysis (tags, descriptions feed into content analysis).

**Independent Test**: Can be tested by running video collection and verifying all extended fields are populated in storage. Delivers value by enabling metadata-based filtering and grouping.

**Acceptance Scenarios**:

1. **Given** a channel is initialized, **When** the user collects videos, **Then** each video record includes description, tags, category, thumbnail URL, default language, privacy status, topic categories, and caption availability.
2. **Given** a channel is initialized, **When** the user collects channel info, **Then** the channel record includes subscriber count, total view count, and description in addition to existing fields.
3. **Given** comments are collected for a video, **When** top-level comments have replies, **Then** the system also collects reply comments and stores the reply count per thread.

---

### User Story 3 - Comment Sentiment Analysis (Priority: P2)

As a channel analyst, I want to analyze comment sentiment using either an LLM service or a local Korean NLP model, so that I can understand student reactions to lecture content without manually reading every comment.

**Why this priority**: Comment analysis is the most immediate analytical value-add. The current channel has comments disabled, but this enables use with other channels and future activation. Two backends (LLM and local) provide flexibility in cost and connectivity.

**Independent Test**: Can be tested by providing a batch of sample comments and verifying sentiment labels and confidence scores are returned. Each backend (LLM, local) can be tested independently.

**Acceptance Scenarios**:

1. **Given** a set of collected comments, **When** the user runs sentiment analysis with the LLM backend, **Then** each comment receives a sentiment label (positive/neutral/negative) and a confidence score.
2. **Given** a set of Korean-language comments, **When** the user runs sentiment analysis with the local backend, **Then** sentiment classification accuracy is comparable to LLM results for Korean text.
3. **Given** a batch of comments that was previously analyzed, **When** the user runs analysis again with unchanged comments, **Then** cached results are returned without re-processing.
4. **Given** the LLM service is unavailable, **When** the user runs sentiment analysis with the LLM backend selected, **Then** the system reports a clear error message indicating the LLM service is unreachable and suggests using the local backend instead.

---

### User Story 4 - Topic-Sentiment Mapping and Question Extraction (Priority: P2)

As a channel analyst, I want comments automatically grouped by topic with per-topic sentiment, and student questions automatically extracted and cross-referenced with rewatch hotspots, so that I can identify which specific content areas cause confusion.

**Why this priority**: Goes beyond simple positive/negative to actionable insights. Cross-referencing questions with retention data provides double verification of difficulty zones.

**Independent Test**: Can be tested by providing comments with known topics and questions, then verifying topic clusters, per-topic sentiment, and question-hotspot matches.

**Acceptance Scenarios**:

1. **Given** a set of comments for a video, **When** topic extraction is run, **Then** comments are grouped into distinct topics with a label and per-topic sentiment distribution.
2. **Given** comments containing questions and retention data with hotspots, **When** cross-reference analysis is run, **Then** questions are matched to corresponding hotspot time ranges with a relevance score.
3. **Given** a video with no comments, **When** topic extraction is run, **Then** the system returns an empty result without errors.

---

### User Story 5 - LLM-Powered Transcript Analysis (Priority: P2)

As a channel owner, I want video transcripts automatically segmented into chapters with summaries, difficulty predictions, and topic tags, so that I can understand lecture structure and identify hard sections before reviewing retention data.

**Why this priority**: Transcript analysis unlocks content-level insights that retention curves alone cannot provide. Chapter segmentation and difficulty prediction are foundational for the EQS scoring and optimal segment length analysis.

**Independent Test**: Can be tested by providing a transcript and verifying chapter boundaries, summaries, difficulty scores, and topic tags are generated.

**Acceptance Scenarios**:

1. **Given** a video transcript, **When** segmentation is run, **Then** the transcript is divided into semantically coherent chapters, each with a title, summary, and difficulty score (0.0-1.0).
2. **Given** a segmented transcript and retention data, **When** comparison analysis is run, **Then** predicted difficulty zones are cross-referenced with actual hotspots/skip zones.
3. **Given** a transcript in Korean, **When** segmentation is run, **Then** the analysis correctly handles Korean text and produces Korean-language summaries.

---

### User Story 6 - Education Quality Scoring (EQS) (Priority: P3)

As a channel owner, I want each video automatically scored on 5 educational quality axes (Relevance, Accuracy, Clarity, Engagement, Depth) based on transcript and metadata analysis, so that I can evaluate lecture quality independently of popularity metrics.

**Why this priority**: Provides objective quality measurement that complements popularity-based metrics. Depends on transcript segmentation (P2) being functional first.

**Independent Test**: Can be tested by providing a transcript and verifying a RACED score is returned with values for each axis and an overall weighted average.

**Acceptance Scenarios**:

1. **Given** a video transcript and metadata, **When** EQS evaluation is run, **Then** the system returns scores for all 5 RACED axes and an overall weighted score.
2. **Given** multiple videos with EQS scores, **When** the user views results, **Then** scores are comparable across videos within the same channel.

---

### User Story 7 - Advanced Time Series Forecasting (Priority: P3)

As a channel owner, I want view count and watch time forecasted using statistical models (ARIMA, Prophet) with academic calendar awareness, so that I can anticipate viewing patterns and detect anomalies tied to academic events.

**Why this priority**: Upgrades the existing linear regression to production-quality forecasting. Depends on daily time-series data collection (P1) being available.

**Independent Test**: Can be tested by providing historical daily data and verifying forecast output with confidence intervals, and anomaly flags aligned with known academic calendar dates.

**Acceptance Scenarios**:

1. **Given** at least 180 days of daily view/watch-time data, **When** forecasting is run, **Then** the system produces predictions using ARIMA or Prophet with confidence intervals.
2. **Given** historical data and a user-provided academic calendar, **When** pattern analysis is run, **Then** the system annotates viewing trends with calendar events and identifies deviations from expected patterns around semester start/end, exam periods, and assignment deadlines.
3. **Given** daily data with sudden spikes or drops, **When** anomaly detection is run, **Then** anomalies are flagged with the detected date and magnitude.

---

### User Story 8 - Comment Insight Report (Priority: P3)

As a channel analyst, I want a dedicated comment insight report that summarizes topic-level student reactions and auto-extracted FAQs, so that I can quickly understand student needs without reading individual comments.

**Why this priority**: Consolidates comment analysis results into an actionable deliverable. Depends on sentiment and topic analysis (P2) being functional.

**Independent Test**: Can be tested by providing analyzed comment data and verifying the generated report contains topic summaries, sentiment distribution, and FAQ list.

**Acceptance Scenarios**:

1. **Given** comments with completed sentiment and topic analysis, **When** the comment insight report is generated, **Then** it includes per-topic sentiment summaries and an auto-extracted FAQ section.
2. **Given** the report format is HTML, **When** the report is generated, **Then** it renders correctly in a standard browser.

---

### User Story 9 - Channel-Level Comprehensive Report (Priority: P3)

As a channel owner, I want a comprehensive channel report that integrates video comparisons, trend analysis, time-series forecasts, and data-driven improvement suggestions, so that I can make informed decisions about lecture content strategy.

**Why this priority**: The culminating deliverable that ties all analysis together. Depends on most other features being functional.

**Independent Test**: Can be tested by providing a complete dataset (videos, analytics, analysis results) and verifying the report includes comparison tables, trend charts, forecasts, and actionable suggestions.

**Acceptance Scenarios**:

1. **Given** a channel with collected analytics and completed analysis, **When** the channel report is generated, **Then** it includes video performance comparisons (by topic, length, format).
2. **Given** forecast data and analysis results, **When** the channel report is generated, **Then** it includes time-series trend visualizations and data-driven improvement suggestions.

---

### User Story 10 - Bulk Data Download via Reporting API (Priority: P3)

As a channel owner with a large channel (thousands of videos), I want to download analytics data in bulk via the YouTube Reporting API, so that I can avoid API quota limits when collecting historical data.

**Why this priority**: Optimization for large channels. The Analytics API real-time queries work for smaller channels; this is needed at scale.

**Independent Test**: Can be tested by creating a reporting job, waiting for completion, and verifying the downloaded CSV data matches the expected schema.

**Acceptance Scenarios**:

1. **Given** a channel with OAuth credentials, **When** the user initiates bulk data download, **Then** the system creates a reporting job, polls for completion, and downloads the resulting CSV.
2. **Given** a reporting job is in progress, **When** the user checks status, **Then** the system displays the current job status and estimated completion.

---

### Edge Cases

- What happens when a video has no transcript available in any language and Whisper is not installed?
- How does the system handle videos with comments disabled when running comment analysis?
- What happens when the YouTube API quota is exhausted mid-collection?
- How does the system handle videos that have been deleted or made private since the last collection?
- What happens when the LLM service returns malformed or incomplete responses during transcript analysis?
- How does the system handle channels with zero videos matching the professor filter?
- What happens when daily time-series data has gaps (missing days)?
- How does the system handle mixed-language comments (Korean + English in same comment)?

## Requirements *(mandatory)*

### Functional Requirements

**Data Collection**

- **FR-001**: System MUST collect all available YouTube Analytics report types: daily time-series, traffic sources, demographics, geography, device/OS, playback location, subscriber changes, and engagement metrics. The default collection window is the last 2 years, with a user-configurable start date override.
- **FR-002**: System MUST collect extended video metadata including description, tags, category, thumbnail URL, default language, privacy status, topic categories, and caption availability.
- **FR-003**: System MUST collect extended channel metadata including subscriber count, total view count, and channel description.
- **FR-004**: System MUST collect comment replies (not just top-level comments) and store reply count per thread.
- **FR-005**: System MUST support incremental collection, fetching only new data since the last run.
- **FR-006**: System MUST support bulk data download via the YouTube Reporting API for large channels.
- **FR-007**: System MUST detect and collect newly uploaded videos when re-running video collection.

**Comment Analysis**

- **FR-008**: System MUST provide LLM-based comment sentiment analysis with sentiment labels (positive/neutral/negative) and confidence scores. The LLM backend is the default.
- **FR-009**: System MUST provide local Korean NLP model-based sentiment analysis as an explicitly user-selectable alternative backend. There is no automatic fallback between backends; the system reports a clear error if the selected backend is unavailable.
- **FR-010**: System MUST cache sentiment analysis results by content hash to avoid redundant processing.
- **FR-011**: System MUST extract discussion topics from comments and map sentiment per topic.
- **FR-012**: System MUST automatically identify and extract student questions from comments.
- **FR-013**: System MUST cross-reference extracted questions with rewatch hotspot time ranges.

**LLM Transcript Analysis**

- **FR-014**: System MUST segment video transcripts into semantically coherent chapters with titles and summaries.
- **FR-015**: System MUST predict difficulty scores (0.0-1.0) for each transcript segment based on vocabulary and concept density.
- **FR-016**: System MUST generate topic tags for each transcript segment.
- **FR-017**: System MUST support Korean-language transcripts for all analysis functions.

**Education Quality Scoring**

- **FR-018**: System MUST evaluate videos on 5 RACED axes (Relevance, Accuracy, Clarity, Engagement, Depth) and produce an overall weighted score.

**Time Series Forecasting**

- **FR-019**: System MUST connect daily time-series collection data to the forecasting pipeline as input.
- **FR-020**: System MUST support ARIMA and Prophet models in addition to existing linear regression.
- **FR-021**: System MUST accept user-provided academic calendar dates (semester start/end, exam weeks, assignment deadlines) and use them to annotate time-series data and contextualize anomalies.

**Reporting**

- **FR-022**: System MUST generate a comment insight report with per-topic sentiment summaries and auto-extracted FAQ.
- **FR-023**: System MUST generate a channel-level comprehensive report with video comparisons, trend analysis, forecasts, and improvement suggestions.
- **FR-024**: System MUST provide data-driven improvement suggestions in reports (optimal length, structure patterns, difficulty distribution).

### Key Entities

- **AnalyticsReport**: A collection of metrics for a specific report type (traffic, demographics, etc.) with dimensions, date range, and video scope.
- **Comment (extended)**: Extended with sentiment fields (label, confidence, backend, content hash) directly on the Comment model, plus parent_comment_id and reply_count for reply support.
- **TopicCluster**: A group of comments sharing a common discussion topic, with aggregate sentiment distribution.
- **TranscriptChapter**: A semantically coherent segment of a transcript with title, summary, difficulty score, and topic tags.
- **QualityScore**: RACED 5-axis evaluation result with per-axis and overall weighted scores.
- **ForecastResult**: Time-series prediction with model type (linear/ARIMA/Prophet), confidence intervals, and anomaly flags.
- **ImprovementSuggestion**: A data-driven recommendation derived from analysis results, with supporting evidence and priority.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 8 YouTube Analytics report types are collected successfully for a configured channel, covering 100% of available OAuth-accessible data.
- **SC-002**: Incremental collection reduces data transfer by at least 80% on subsequent runs compared to full collection.
- **SC-003**: Comment sentiment analysis processes a batch of 100 comments within 60 seconds using the LLM backend.
- **SC-004**: Korean-language comment sentiment classification achieves at least 80% agreement with manual labeling on a sample set.
- **SC-005**: Transcript segmentation produces chapter boundaries that align with manual segmentation within a 30-second tolerance for 70% of segments.
- **SC-006**: Time-series forecasting with ARIMA/Prophet achieves MAE below 10% on held-out test data (last 30 days).
- **SC-007**: Channel comprehensive report generation completes within 5 minutes for a channel with up to 500 videos.
- **SC-008**: All new features maintain the existing test pass rate (200+ tests) and add tests for each new functional requirement.

## Assumptions

- YouTube OAuth credentials with `youtube.readonly` and `yt-analytics.readonly` scopes are already configured (v1 infrastructure).
- The YouTube Analytics API provides all listed report types for channels with sufficient data history. Some reports may return empty results for channels with low traffic.
- LLM API access defaults to Claude (via `ANTHROPIC_API_KEY` environment variable). GPT-4o is supported as an alternative by setting `TUBE_SCOUT_LLM_PROVIDER=openai` and providing `OPENAI_API_KEY`.
- For local NLP models (KoBERT/KoELECTRA), the user's machine has sufficient resources (GPU optional, CPU inference acceptable with longer processing time).
- The existing v1 storage layer (JSON + Parquet), checkpoint system, and CLI framework are reused and extended.
- Comment analysis features will be developed and tested against channels with comments enabled, even though the primary target channel currently has comments disabled.
- agenix secret management setup is out of scope for this feature and will be configured by the user separately.
- YouTube Reporting API access requires the same OAuth credentials but may need additional API enablement in Google Cloud Console.
- Phase 5 features (optimal segment length, cross-modal alignment, A/B testing, video comparison dashboard) are explicitly out of scope for this specification and will be addressed in a future feature cycle.
