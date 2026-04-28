# Feature Specification: Multi-Channel Administration

**Feature Branch**: `003-multichannel-admin`
**Created**: 2026-04-04
**Status**: Draft
**Input**: User description: "idea/idea3.md — Multi-channel token management, title parsing, structured search, department reports, title validation"

## Clarifications

### Session 2026-04-04

- Q: How is channel ID resolved during registration — admin provides it, auto-detected from OAuth, or extracted from URL? → A: OAuth 로그인 후 `channels.list(mine=True)`로 채널 ID 자동 감지. 관리자는 별칭만 제공. 계정에 채널이 여러 개면 선택 목록 표시.
- Q: Should title parsing rules be customizable per department or use a universal parser? → A: 복수 패턴을 우선순위로 시도하는 범용 파서. 패턴 추가 시 코드 수정. 학과별 설정 파일 불필요.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Multi-Channel Token Management (Priority: P1)

As an academic affairs administrator, I want to register multiple department YouTube channels once and access them without re-authentication, so that I can manage all departments efficiently from a single workstation.

**Why this priority**: Without multi-channel authentication, every other feature (reports, validation, search) is blocked. This is the foundation for all administrative workflows.

**Independent Test**: Can be fully tested by registering 2+ channels, listing them, revoking one, and verifying the remaining channel still works without browser login.

**Acceptance Scenarios**:

1. **Given** no channels are registered, **When** the admin runs the auth command for a department, **Then** a browser window opens for OAuth login and the token is stored under the department's alias.
2. **Given** a channel is already registered, **When** the admin runs a data collection command for that channel, **Then** the system authenticates automatically using the stored token without opening a browser.
3. **Given** a stored token has expired, **When** the admin runs a command for that channel, **Then** the system silently refreshes the token using the refresh_token and proceeds without interruption.
4. **Given** multiple channels are registered, **When** the admin lists registered channels, **Then** all channels are displayed with their aliases, channel names, and last-used timestamps.
5. **Given** the admin wants to remove a channel, **When** the revoke command is run, **Then** the token file is deleted and subsequent commands for that channel prompt re-authentication.
6. **Given** the admin sets an environment variable for the token directory, **When** commands are run, **Then** the system uses the overridden directory for all token operations.

---

### User Story 2 - Video Title Parsing and Structured Data (Priority: P1)

As an academic affairs administrator, I want video titles automatically parsed into structured fields (professor, course, year, semester, week, session) so that I can search, filter, and analyze videos by any of these dimensions.

**Why this priority**: Title parsing is the backbone of all downstream features — reports, validation, and search all depend on structured data extracted from titles. Without it, analysis is limited to manual inspection.

**Independent Test**: Can be tested by feeding a list of real video titles and verifying each is parsed into correct structured fields, with parse failures clearly flagged.

**Acceptance Scenarios**:

1. **Given** a list of videos with standard titles (e.g., "홍길동 2026 간호학과 인체구조와기능 4주차 2차시"), **When** parsing is run, **Then** each title is decomposed into professor, course, year, week, session, and department fields.
2. **Given** a title with multiple professors (e.g., "홍길동/김영희 융합헬스케어4.0"), **When** parsing is run, **Then** both professors are extracted and the video is attributed to both.
3. **Given** a title that does not match any known pattern, **When** parsing is run, **Then** the original title is preserved with a `parse_error` flag and the system continues without crashing.
4. **Given** parsed data exists, **When** the admin views the results, **Then** a summary shows total videos parsed, parse success rate, and a list of unparseable titles.
5. **Given** parsed data exists, **When** the admin exports it, **Then** the structured data is saved as a JSON file in the timestamped output directory.

---

### User Story 3 - Structured Search via YAML Configuration (Priority: P2)

As an academic affairs administrator, I want to define complex search criteria in a YAML file and filter videos by professor, course, year, semester, week range, and exclusion patterns, so that I can quickly identify specific subsets of lecture videos.

**Why this priority**: Enables targeted analysis and report generation for specific professors, courses, or time periods. Depends on title parsing (P1) being functional.

**Independent Test**: Can be tested by providing a search_clips.yaml with specific filters and verifying the returned video list matches expected results against known data.

**Acceptance Scenarios**:

1. **Given** a search_clips.yaml with a single filter (professor + year), **When** the search command is run, **Then** only videos matching both criteria are returned.
2. **Given** a search_clips.yaml with multiple queries (OR conditions), **When** the search command is run, **Then** videos matching any of the queries are returned without duplicates.
3. **Given** a search_clips.yaml with exclude rules, **When** the search command is run, **Then** videos containing excluded title keywords are omitted from results.
4. **Given** no search_clips.yaml exists, **When** the admin uses CLI flags directly (--professor, --year), **Then** the search works identically to YAML-based search.
5. **Given** search results are returned, **When** the admin views them, **Then** results are displayed as a table with parsed fields and can be exported to JSON.

---

### User Story 4 - Department Report Generation (Priority: P2)

As an academic affairs administrator, I want to generate a comprehensive department report that shows per-professor video counts, weekly coverage, compliance rates, and upload timing, so that I can present quantitative evidence for administrative review.

**Why this priority**: The primary deliverable of the system — turns raw data into actionable administrative reports. Depends on title parsing (P1) and optionally on search (P2) for scoping.

**Independent Test**: Can be tested by providing a set of parsed video data and verifying the generated report contains all required sections with correct calculations.

**Acceptance Scenarios**:

1. **Given** a channel with parsed video data, **When** the department report is generated, **Then** it includes a department overview with total videos, professor count, course count, and total views.
2. **Given** a channel with parsed video data, **When** the department report is generated, **Then** it includes per-professor detail with video count, courses taught, weekly coverage percentage, average duration, and average views.
3. **Given** a channel with parsed video data and an academic calendar, **When** the department report is generated, **Then** it includes a compliance analysis with a professor-by-week upload heatmap and a list of missing weeks.
4. **Given** the report format is Excel, **When** the report is generated, **Then** it contains separate sheets for department overview, professor detail, compliance, and validation findings.
5. **Given** the report format is HTML, **When** the report is generated, **Then** it includes interactive charts (upload heatmap, duration distribution) viewable in a browser.
6. **Given** the admin specifies a year and semester, **When** the report is generated, **Then** only videos from that academic period are included in the analysis.

---

### User Story 5 - Title Validation and Anomaly Detection (Priority: P2)

As an academic affairs administrator, I want the system to automatically detect title errors, naming inconsistencies, missing weeks, and metadata anomalies, so that I can correct issues before they affect academic records.

**Why this priority**: Prevents data quality issues from propagating. Complements reports by flagging items that need human attention. Depends on title parsing (P1).

**Independent Test**: Can be tested by providing a set of videos with known title errors and verifying each error is detected with the correct rule ID and severity.

**Acceptance Scenarios**:

1. **Given** a video with title year "2024" uploaded in April 2026, **When** validation is run, **Then** rule V-001 (year mismatch) is triggered with WARNING severity.
2. **Given** two videos with identical professor+course+week+session, **When** validation is run, **Then** rule V-002 (duplicate) is triggered with ERROR severity.
3. **Given** a video with week number 18, **When** validation is run, **Then** rule V-003 (invalid week) is triggered with ERROR severity.
4. **Given** a professor name "홍길 동" (with space) alongside "홍길동", **When** validation is run, **Then** rule V-004 (name inconsistency) is triggered with WARNING severity.
5. **Given** weeks 1, 2, 4, 5 exist but week 3 is missing, **When** validation is run, **Then** rule V-008 (missing week) is triggered with WARNING severity.
6. **Given** validation results exist, **When** the admin views them, **Then** results are grouped by severity (ERROR first, then WARNING, then INFO) with per-professor summary counts.
7. **Given** a supplementary video titled "핵심영상" or "보완영상", **When** validation is run, **Then** it is categorized separately and not counted as a missing regular session.

---

### User Story 6 - Timestamped Output Management (Priority: P3)

As an academic affairs administrator, I want all extracted data and reports saved in timestamped directories, so that I can compare results across different analysis runs without re-extracting data.

**Why this priority**: Supports longitudinal tracking and avoids redundant data extraction. Enhances all other features but is not functionally blocking.

**Independent Test**: Can be tested by running the pipeline twice and verifying two separate output directories exist with independent data, and a "latest" shortcut points to the newest run.

**Acceptance Scenarios**:

1. **Given** the admin runs any collection or analysis command, **When** output is generated, **Then** it is saved under `./output/report-YYYYMMDD-HHMM/` with the current timestamp.
2. **Given** multiple runs have been performed, **When** the admin checks the output directory, **Then** each run's data is in a separate timestamped directory, and `output/latest` points to the most recent run.
3. **Given** a previous run exists, **When** the admin runs a new analysis, **Then** the previous run's data is not modified or deleted.
4. **Given** the admin specifies `--output-dir`, **When** output is generated, **Then** it uses the specified directory instead of the default timestamped path.

---

### Edge Cases

- What happens when a channel's OAuth app credentials (client_secret) are revoked by Google?
- How does the system handle a video title entirely in English with no Korean structure?
- What happens when two departments use the same professor name but different people?
- How does the system handle a title with no week/session information (e.g., "홍길동 특강")?
- What happens when the academic calendar is not provided for compliance analysis?
- How does the system handle a channel with 10,000+ videos for title parsing performance?
- What happens when the token directory path contains non-ASCII characters?

## Requirements *(mandatory)*

### Functional Requirements

**Multi-Channel Authentication**

- **FR-001**: System MUST store OAuth tokens per channel alias in a configurable directory, defaulting to `~/.config/tube-scout/tokens/`.
- **FR-002**: System MUST support registering a new channel via browser-based OAuth flow with a user-specified alias. After OAuth login, the system auto-detects the channel ID from the authenticated account. If the account owns multiple channels, the system displays a selection list.
- **FR-003**: System MUST automatically refresh expired tokens using stored refresh_tokens without user intervention.
- **FR-004**: System MUST allow listing all registered channels with their aliases, channel names, and registration dates.
- **FR-005**: System MUST allow revoking (deleting) a channel's token by alias.
- **FR-006**: System MUST support overriding the token directory via the `TUBE_SCOUT_TOKENS_DIR` environment variable.

**Title Parsing**

- **FR-007**: System MUST parse video titles into structured fields: professor, course, year, semester, week, session, and department. The parser uses multiple regex patterns tried in priority order (universal parser). No per-department configuration is required; new patterns are added by extending the parser's pattern list.
- **FR-008**: System MUST handle multiple professors in a single title (e.g., slash-separated) by attributing the video to all listed professors.
- **FR-009**: System MUST flag unparseable titles with a `parse_error` flag and preserve the original title.
- **FR-010**: System MUST store all parsed title data as structured JSON in the timestamped output directory.

**Structured Search**

- **FR-011**: System MUST support filtering videos by any combination of professor, course, year, semester, week range, and session via YAML configuration.
- **FR-012**: System MUST support multiple OR-combined query groups in a single YAML file.
- **FR-013**: System MUST support excluding videos by title keyword patterns.
- **FR-014**: System MUST support equivalent search via CLI flags as an alternative to YAML.

**Department Reports**

- **FR-015**: System MUST generate a department overview with total videos, professors, courses, total duration, and total views.
- **FR-016**: System MUST generate per-professor detail with video count, courses, weekly coverage (percentage of weeks with uploads), session completeness, average duration, average views, and upload timing relative to week start date.
- **FR-017**: System MUST generate a compliance analysis with professor-by-week upload heatmap, missing weeks list, upload deadline compliance rate, and zero-upload professor list.
- **FR-018**: System MUST support report output in HTML (with interactive charts), Excel (with separate sheets per section), and PDF formats.
- **FR-019**: System MUST scope reports by year and semester when specified.

**Title Validation**

- **FR-020**: System MUST detect year mismatches (title year vs upload year difference > 1 year) as V-001 WARNING.
- **FR-021**: System MUST detect duplicate videos (same professor+course+week+session) as V-002 ERROR.
- **FR-022**: System MUST detect invalid week numbers (> 16 or ≤ 0) as V-003 ERROR.
- **FR-023**: System MUST detect professor name inconsistencies (edit distance ≤ 2) as V-004 WARNING.
- **FR-024**: System MUST detect title pattern deviations (parse failures) as V-005 WARNING.
- **FR-025**: System MUST detect session continuity gaps (e.g., session 2 without session 1) as V-006 WARNING.
- **FR-026**: System MUST detect duration outliers (> ±3σ from course average) as V-007 INFO.
- **FR-027**: System MUST detect missing weeks in a sequence as V-008 WARNING.
- **FR-028**: System MUST detect extended upload gaps (2+ consecutive weeks) as V-009 INFO.
- **FR-029**: System MUST classify supplementary videos (titles containing "핵심영상", "보완영상", "질문응답") as a separate category.
- **FR-030**: System MUST include validation results as a dedicated section in department reports and as a separate sheet in Excel output.

**Output Management**

- **FR-031**: System MUST save all output (raw data, parsed data, validation results, reports) in a timestamped directory under `./output/report-YYYYMMDD-HHMM/`.
- **FR-032**: System MUST maintain a `latest` symbolic link pointing to the most recent output directory.
- **FR-033**: System MUST not modify or delete previous output directories when running a new analysis.
- **FR-034**: System MUST support overriding the output directory via `--output-dir` CLI flag.

### Key Entities

- **ChannelRegistration**: A registered department channel with alias, channel ID, channel name, registration date, and token file reference.
- **ParsedTitle**: Structured data extracted from a video title — professor, course, year, semester, week, session, department, original title, and parse_error flag.
- **SearchFilter**: A set of filtering criteria (professor, course, year, semester, week range, session, exclusion patterns) applied to parsed video data.
- **DepartmentReport**: A generated report containing department overview, per-professor detail, compliance analysis, and validation findings.
- **ValidationFinding**: A detected anomaly with rule ID (V-001 to V-009), severity (ERROR/WARNING/INFO), affected video(s), and description.
- **OutputRun**: A timestamped output directory containing all data and reports from a single analysis execution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Administrator can register and use 5+ department channels without any re-authentication during a single work session.
- **SC-002**: Title parsing achieves ≥ 85% success rate on real university lecture video titles (structured fields correctly extracted).
- **SC-003**: Search with YAML filters returns results within 5 seconds for a channel with up to 5,000 videos.
- **SC-004**: Department report generation completes within 2 minutes for a channel with up to 3,000 videos.
- **SC-005**: Validation detects 100% of synthetically injected title errors (year mismatch, duplicates, invalid weeks) with correct severity classification.
- **SC-006**: All output data is preserved across multiple runs — no data loss or overwriting between timestamped directories.
- **SC-007**: Reports include all required sections with correct calculations verified against manually computed values for a test dataset.

## Assumptions

- Each department has exactly one YouTube channel. Multi-channel per department is not supported.
- The OAuth client_secret file is shared across all departments (single Google Cloud project owned by academic affairs).
- Video title naming conventions follow Korean university patterns with professor name, course name, week, and session information. Titles in other languages or without structured information will have low parse rates.
- Academic calendar (semester dates, week boundaries) is available from the existing v2 `academic_calendar.json` format.
- The system runs on a single administrator's workstation, not as a multi-user web service.
- Content-based video reuse detection (subtitle hash comparison) is out of scope for this feature and covered in idea4 (content quality management).
- PDF report generation may require additional system-level dependencies (e.g., a headless browser or PDF rendering library). If PDF is not feasible, HTML and Excel are the minimum required formats.
