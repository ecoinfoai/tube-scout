# Feature Specification: 보고서 필터링 및 PDF 종합 출력

**Feature Branch**: `006-report-filter-pdf-bundle`
**Created**: 2026-04-07
**Status**: Draft
**Input**: User description: "idea/idea3.1.md"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 조건별 영상 필터링 (Priority: P1)

학과 관리자(DX지원센터장)는 214개 영상 중 특정 교수, 교과목, 기간의 영상만 선별하고 싶다. 왜냐하면 학과장에게 "홍길동 교수의 2025년 2학기 감염미생물학 영상 현황"처럼 특정 범위의 보고서를 제출해야 하기 때문이다.

**Why this priority**: 필터링 없이는 나머지 기능(미리보기, PDF 번들)이 모두 의미 없다. 전체 기능의 기반.

**Independent Test**: "감염미생물학" 키워드로 필터 시 해당 교과목 영상만 정확히 추출되고, 무관한 영상은 제외되는지 확인.

**Acceptance Scenarios**:

1. **Given** 214개 영상이 수집된 채널, **When** 키워드 "감염미생물학"으로 필터, **Then** 제목에 "감염미생물학"이 포함된 영상만 반환
2. **Given** 214개 영상, **When** 게시일 범위 2025-09-01 ~ 2026-02-28 지정, **Then** 해당 기간 내 게시된 영상만 반환
3. **Given** 214개 영상, **When** 키워드 + 기간 필터 동시 적용, **Then** 두 조건을 모두 만족하는 영상만 반환
4. **Given** 필터 조건이 어떤 영상과도 일치하지 않음, **When** 필터 실행, **Then** 빈 결과와 안내 메시지 표시

---

### User Story 2 - 필터 결과 미리보기 (Priority: P2)

학과 관리자는 보고서 생성 전에 필터 결과를 미리 확인하고 싶다. 왜냐하면 214개 중 의도한 영상만 포함되었는지 검증한 뒤 출력해야 하기 때문이다.

**Why this priority**: PDF 생성은 시간이 걸리므로, 잘못된 필터로 불필요한 생성을 방지해야 한다.

**Independent Test**: 필터 조건 입력 후 대상 영상 목록(제목, 게시일, 조회수)이 테이블로 표시되고, 사용자가 진행/취소를 선택할 수 있는지 확인.

**Acceptance Scenarios**:

1. **Given** 필터 조건이 15개 영상과 일치, **When** 미리보기 실행, **Then** 15개 영상의 제목, 게시일, 조회수가 테이블로 표시
2. **Given** 미리보기 결과 확인 후, **When** 사용자가 진행 선택, **Then** PDF 번들 생성 시작
3. **Given** 미리보기 결과 확인 후, **When** 사용자가 취소 선택, **Then** 생성하지 않고 종료

---

### User Story 3 - PDF 종합 보고서 생성 (Priority: P1)

학과 관리자는 필터된 영상의 분석 결과를 하나의 PDF로 묶어 출력하고 싶다. 왜냐하면 교무과에 제출할 때 개별 HTML 214개가 아닌 단일 문서가 필요하기 때문이다.

**Why this priority**: 이 기능이 idea3.1의 핵심 가치 — 실무에서 바로 사용 가능한 보고서 산출물.

**Independent Test**: 필터된 영상에 대해 표지, 목차, 페이지번호가 포함된 단일 PDF가 생성되고, 각 영상 보고서가 새 페이지에서 시작하는지 확인.

**Acceptance Scenarios**:

1. **Given** 필터로 10개 영상 선택, **When** PDF 번들 생성, **Then** 표지 + 채널 요약 + 영상별 상세가 포함된 단일 PDF 생성
2. **Given** PDF 생성, **When** 목차 확인, **Then** 각 영상 제목이 페이지 번호와 함께 자동 생성된 목차에 표시
3. **Given** PDF 생성, **When** 페이지 하단 확인, **Then** "p. N / Total" 형식의 페이지 번호 표시
4. **Given** PDF 생성, **When** 영상 간 경계 확인, **Then** 각 영상 보고서가 새 페이지에서 시작
5. **Given** 차트/테이블이 포함된 영상 보고서, **When** PDF 인쇄, **Then** 차트/테이블이 페이지 경계에서 잘리지 않음

---

### User Story 4 - 정렬 옵션 (Priority: P3)

학과 관리자는 보고서 내 영상 순서를 선택하고 싶다. 왜냐하면 보고 목적에 따라 게시일순, 교과목→주차순, 조회수순이 각각 필요하기 때문이다.

**Why this priority**: 기본 정렬(게시일순)만으로도 사용 가능하지만, 추가 정렬이 보고서 활용도를 높인다.

**Independent Test**: 같은 필터 결과에 대해 3가지 정렬을 각각 적용했을 때 영상 순서가 달라지는지 확인.

**Acceptance Scenarios**:

1. **Given** 필터 결과 15개 영상, **When** 게시일 오름차순 정렬, **Then** 가장 오래된 영상이 첫 번째
2. **Given** 필터 결과 15개 영상, **When** 교과목→주차 정렬, **Then** 교과목 가나다순 → 같은 교과목 내 주차순
3. **Given** 필터 결과 15개 영상, **When** 조회수 내림차순 정렬, **Then** 가장 많이 조회된 영상이 첫 번째

---

### User Story 5 - 표지 및 채널 요약 (Priority: P2)

학과 관리자는 보고서에 공식 문서로서의 체계를 갖추고 싶다. 왜냐하면 교무과에 제출하는 문서에 채널명, 필터 조건, 영상 수, 생성일이 명시되어야 하기 때문이다.

**Why this priority**: 표지 없는 PDF는 공식 문서로 부적합. 채널 요약 1페이지가 전체 맥락을 제공.

**Independent Test**: PDF 첫 페이지가 표지이고 필터 조건이 명시되어 있으며, 두 번째 페이지에 채널 개요가 있는지 확인.

**Acceptance Scenarios**:

1. **Given** PDF 생성, **When** 첫 페이지 확인, **Then** 채널명, 적용된 필터 조건, 포함 영상 수, 총 재생시간, 생성일이 표시
2. **Given** PDF 생성, **When** 두 번째 페이지 확인, **Then** 채널 개요 (총 영상 수, 교수별 분포, 교과목 목록 등) 표시

---

### Edge Cases

- 필터 결과가 0건일 때: PDF를 생성하지 않고 명확한 안내 메시지 표시
- 영상에 분석 데이터(retention, analytics)가 없을 때: 해당 섹션을 우아하게 생략
- 댓글이 0건인 채널: 댓글 관련 섹션 자동 생략 (현재 대상 채널은 댓글 비활성화 상태)
- 자막이 없는 영상: EQS/세그먼트 분석 섹션 생략
- 필터 결과가 100건 이상일 때: 대용량 PDF 생성 시 메모리 안정성 유지
- PDF 렌더링 도구 미설치 시: 명확한 설치 안내 메시지 + HTML 폴백 제공

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST filter videos by keyword matching against video title
- **FR-002**: System MUST filter videos by published date range (start date, end date)
- **FR-003**: System MUST support combining keyword and date range filters (AND logic)
- **FR-004**: System MUST display a preview table of filtered results (title, published date, view count) before generating the report
- **FR-005**: System MUST allow user to confirm or cancel after preview
- **FR-006**: System MUST generate a single PDF document containing all filtered video reports
- **FR-007**: PDF MUST include a cover page with: channel name, applied filter conditions, included video count, total duration, generation date
- **FR-008**: PDF MUST include a channel summary page after the cover (total videos, professor distribution, course list)
- **FR-009**: PDF MUST include an auto-generated table of contents with video titles and page numbers
- **FR-010**: PDF MUST display page numbers in "p. N / Total" format
- **FR-011**: Each video report MUST start on a new page (page break between videos)
- **FR-012**: Charts and tables MUST NOT be split across page boundaries
- **FR-013**: System MUST support three sort orders: published date ascending, course→week order, view count descending
- **FR-014**: Report sections that have no data (comments, retention, transcripts, EQS) MUST be gracefully omitted
- **FR-015**: System MUST provide a clear error message when the PDF rendering tool is not installed, with installation guidance
- **FR-016**: System MUST fall back to HTML bundle output when PDF rendering is unavailable
- **FR-017**: System MUST work with existing collected data (videos_meta.json) without requiring re-collection

### Key Entities

- **VideoFilter**: Represents filter criteria — keyword, date range, sort order
- **FilterResult**: List of videos matching filter criteria with metadata for preview
- **BundleReport**: Composed document — cover page + channel summary + ordered video reports
- **CoverPage**: Channel name, filter conditions, video count, total duration, generation date

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Keyword filter accurately extracts matching videos — "감염미생물학" returns only videos with that term in the title, zero false positives
- **SC-002**: Date range filter includes only videos published within the specified range
- **SC-003**: Generated PDF contains cover page, auto-generated table of contents, and page numbers ("p. N / Total")
- **SC-004**: Each video report starts on a new page — no two video reports share a page
- **SC-005**: Preview shows filtered video list before generation, user can confirm or cancel
- **SC-006**: All three sort orders (date, course→week, views) produce correctly ordered output
- **SC-007**: PDF is printable with charts and tables not split across page boundaries
- **SC-008**: When data sections are missing (comments, retention), those sections are omitted without errors

## Assumptions

- 기존 수집 데이터(videos_meta.json, parsed_titles.json)가 프로젝트 디렉터리에 존재한다
- PDF 렌더링에 weasyprint를 사용하지만, 미설치 시 HTML 번들로 폴백한다
- 현재 대상 채널은 댓글이 비활성화되어 있으므로 댓글 섹션은 항상 생략된다
- 자막 분석(EQS/세그먼트)은 LLM API 키가 있을 때만 포함된다
- 표지에 대학 로고는 포함하지 않는다 (향후 확장 가능)
- PDF 외 xlsx 종합 출력은 이번 범위에 포함하지 않는다 (idea3에서 개별 xlsx는 이미 구현됨)
- v0.1.1 감사에서 수정된 모든 모듈(reporting, json_store, excel_export 등)은 안정적으로 동작한다
