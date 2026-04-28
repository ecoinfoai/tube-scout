# Feature Specification: Lecture Video Content Reuse Detection

**Feature Branch**: `007-content-reuse-detection`
**Created**: 2026-04-07
**Status**: Draft
**Input**: idea/idea4.md — 강의 영상 재사용 탐지 및 콘텐츠 품질 관리

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Caption Collection for Private Videos (Priority: P1)

교무과 담당자가 학과 채널의 모든 영상(비공개 포함)에서 자막을 수집하여, 이후 재사용 탐지의 기초 데이터를 확보한다. 공개 영상은 기존 방식으로, 비공개 영상(채널의 88.6%)은 OAuth 인증된 Captions API로 자막을 내려받는다.

**Why this priority**: 자막이 없으면 이후 모든 분석(해시, 임베딩, diff, 품질 체크)이 불가능하다. 자막 수집은 전체 파이프라인의 필수 전제 조건이다.

**Independent Test**: 채널 별칭을 지정하여 자막 수집 명령을 실행하면, 공개 영상의 자막이 즉시 저장되고, 비공개 영상은 OAuth Captions API를 통해 자막이 저장된다. 저장된 파일 수와 영상 수가 일치하는지 확인한다.

**Acceptance Scenarios**:

1. **Given** 채널이 등록되어 있고 OAuth 인증이 완료된 상태, **When** 자막 수집 명령을 실행하면, **Then** 공개 영상의 자막이 JSON 파일로 저장되고 처리 상태가 기록된다
2. **Given** 비공개 영상이 존재하고 force-ssl scope가 확보된 상태, **When** 자막 수집 명령을 실행하면, **Then** Captions API로 비공개 영상의 SRT 자막이 다운로드되어 세그먼트 단위 JSON으로 변환 저장된다
3. **Given** 이전에 자막을 수집한 채널, **When** 같은 명령을 다시 실행하면, **Then** 이미 수집된 영상은 건너뛰고 신규 영상만 증분 수집한다
4. **Given** 일일 API quota가 소진된 상태, **When** 다음 날 같은 명령을 실행하면, **Then** 중단 지점부터 이어서 수집한다
5. **Given** ASR 자막이 없는 영상(대면강의 녹화본 등), **When** 자막 수집을 시도하면, **Then** 해당 영상을 "자막 없음"으로 기록하고 나머지 영상의 수집을 계속 진행한다

---

### User Story 2 - Multi-Indicator Reuse Detection (Priority: P1)

교무과 담당자가 같은 교과목·주차·차시의 연도별 영상을 비교하여, 전년도 영상을 재사용했는지 5가지 독립 지표로 복합 판정한다. 각 비교 쌍에 종합 의심도(0~100)가 산출되고 우선순위 등급(최우선/높음/참고/정상)이 부여된다.

**Why this priority**: 재사용 탐지가 이 기능의 핵심 목적이다. 단일 지표가 아닌 복합 증거 기반 판정으로 오탐을 최소화하고, 관리자가 우선순위를 두고 효율적으로 점검할 수 있게 한다.

**Independent Test**: 자막이 수집된 상태에서 비교 분석 명령을 실행하면, 교과목×주차×차시 매칭으로 비교 쌍이 생성되고, 각 쌍에 5가지 지표와 종합 의심도가 산출된다.

**Acceptance Scenarios**:

1. **Given** 같은 교수·교과목·주차·차시의 2025년과 2026년 영상 자막이 수집된 상태, **When** 비교 분석을 실행하면, **Then** 자막 해시(I-1), 의미 유사도(I-2), 텍스트 변경률(I-3), 신규 용어 수(I-4), 영상 길이 차이(I-5) 5가지 지표가 산출된다
2. **Given** 5가지 지표가 산출된 상태, **When** 종합 의심도를 계산하면, **Then** 0~100 범위의 점수와 우선순위 등급(최우선 80~100 / 높음 60~79 / 참고 40~59 / 정상 0~39)이 부여된다
3. **Given** 완전히 동일한 자막의 두 영상, **When** 비교하면, **Then** 해시 일치(I-1)가 감지되고 의심도 100으로 최우선 등급이 부여된다
4. **Given** 교수가 같은 슬라이드로 새로 녹음한 영상, **When** 비교하면, **Then** 자막이 다르므로 의미 유사도가 낮게 나오고 정상으로 판정된다
5. **Given** 인트로 문구만 "2025학년도"→"2026학년도"로 변경한 영상, **When** 비교하면, **Then** 유사도 0.95+ / 변경률 5% 이하로 높은 의심도가 산출된다

---

### User Story 3 - Administrator Review Workflow (Priority: P1)

교무과 담당자가 자동 분석 결과를 검토하고, 각 의심 영상에 대해 "확정 중복" 또는 "오탐(정상)"을 마킹한다. 마킹된 결과는 저장되어 다음 분석 시 동일 쌍을 재알림하지 않는다.

**Why this priority**: 자동 판정만으로 교수에게 통보하면 오탐 시 문제가 된다. 관리자 확인 단계는 제도적으로 필수이다.

**Independent Test**: 비교 결과가 존재하는 상태에서 리뷰 명령을 실행하면, 미검토 항목 목록이 표시되고, 상태 마킹 후 저장된다.

**Acceptance Scenarios**:

1. **Given** 비교 분석이 완료된 상태, **When** 리뷰 명령을 실행하면, **Then** 미검토(UNREVIEWED) 항목이 의심도 순으로 표시된다
2. **Given** 미검토 항목이 표시된 상태, **When** 담당자가 특정 쌍을 "확정 중복"으로 마킹하면, **Then** 상태가 CONFIRMED_DUPLICATE로 변경되고 저장된다
3. **Given** 미검토 항목이 표시된 상태, **When** 담당자가 특정 쌍을 "오탐"으로 마킹하면, **Then** 상태가 FALSE_POSITIVE로 변경되고 저장된다
4. **Given** 이전에 CONFIRMED_DUPLICATE로 마킹된 쌍, **When** 다음 학기에 같은 비교를 실행하면, **Then** 이미 확인된 쌍은 재알림하지 않는다

---

### User Story 4 - Content Quality Checklist (Priority: P2)

교무과 담당자가 영상의 교육적 기본 품질을 자동 검사하여, 음성 부재·짧은 영상·무음 과다 등 기본 품질 미달 영상을 식별한다.

**Why this priority**: 재사용 탐지가 핵심이나, 품질 체크리스트는 교무 부서가 요구하는 추가 관리 기능이다. 재사용 탐지 없이도 독립적으로 가치를 제공한다.

**Independent Test**: 자막과 메타데이터가 수집된 상태에서 품질 체크 명령을 실행하면, 각 영상에 Q-001~Q-005 결과가 산출된다.

**Acceptance Scenarios**:

1. **Given** 자막이 수집된 영상, **When** 품질 체크를 실행하면, **Then** 음성 존재(Q-001), 최소 길이(Q-002), 교과목 관련성(Q-003), 무음 비율(Q-004), 말하기 밀도(Q-005) 결과가 산출된다
2. **Given** 자막이 없는 영상, **When** 품질 체크를 실행하면, **Then** Q-001(음성 존재)이 미통과로 기록된다
3. **Given** 5분 미만 영상, **When** 품질 체크를 실행하면, **Then** Q-002(최소 길이)가 미통과로 기록된다

---

### User Story 5 - Content Quality Report (Priority: P2)

교무과 담당자가 재사용 의심 현황, 콘텐츠 업데이트 상세, 품질 체크 결과, 리뷰 현황을 종합한 보고서를 생성한다. HTML(인터랙티브 차트), Excel(시트별 데이터), JSON(프로그래밍용) 형식으로 출력한다.

**Why this priority**: 보고서는 분석 결과의 최종 산출물로, 교무 회의 자료 등으로 활용된다. 분석 기능이 있어야 의미가 있으므로 P2이다.

**Independent Test**: 비교 분석과 품질 체크가 완료된 상태에서 보고서 생성 명령을 실행하면, 지정 형식의 보고서 파일이 생성된다.

**Acceptance Scenarios**:

1. **Given** 비교 분석 결과가 존재하는 상태, **When** HTML 보고서를 생성하면, **Then** 의심도 순 정렬된 영상 목록과 교과목×주차 변경률 히트맵이 포함된 HTML 파일이 생성된다
2. **Given** 비교 분석 결과가 존재하는 상태, **When** Excel 보고서를 생성하면, **Then** 의심 현황, 업데이트 상세, 품질 체크, 리뷰 이력 시트가 포함된 xlsx 파일이 생성된다
3. **Given** 교수별로 의심 영상이 존재하는 상태, **When** 보고서를 생성하면, **Then** 교수별 의심 비율과 등급별 집계가 포함된다

---

### User Story 6 - Pipeline Scan Command (Priority: P2)

교무과 담당자가 단일 명령으로 fingerprint → compare → quality 전체 파이프라인을 실행한다. 개별 단계를 순서대로 호출할 필요 없이 한 번에 처리된다.

**Why this priority**: 편의 기능이며 개별 명령이 먼저 구현되어야 한다. 하지만 실제 운용에서 매번 3개 명령을 순서대로 치는 것은 불편하다.

**Independent Test**: scan 명령 한 줄로 fingerprint, compare, quality가 순차 실행되고 결과가 저장된다.

**Acceptance Scenarios**:

1. **Given** 자막이 수집된 채널, **When** scan 명령을 실행하면, **Then** fingerprint → compare → quality가 순차 실행되고 각 단계의 결과가 저장된다
2. **Given** fingerprint까지 완료된 상태에서 중단됨, **When** scan을 재실행하면, **Then** 완료된 단계는 건너뛰고 compare부터 이어서 실행된다

---

### Edge Cases

- 같은 교과목명이지만 다른 학과에서 운영되는 경우, 비교 쌍 매칭 시 교수+교과목+학과로 구분한다
- 제목 파싱이 실패한 영상(parse_error)은 비교 대상에서 제외하되, 파싱 실패 목록을 별도 보고한다
- 한 학기에 같은 교과목×주차에 2개 이상 영상이 있는 경우(재촬영 등), 같은 연도 내 최신 영상을 대표로 사용한다
- 자막 언어가 한국어가 아닌 영상(영어 전용 강의 등)은 다국어 임베딩 모델이 처리한다
- 비교 연도에 해당 교과목이 개설되지 않은 경우, 비교 쌍이 생성되지 않으며 보고서에 "해당 없음"으로 표시한다
- API quota 소진 중 네트워크 오류가 발생하면 처리 상태를 저장하고, 재실행 시 이어서 처리한다

## Requirements *(mandatory)*

### Functional Requirements

**자막 수집**
- **FR-001**: System MUST collect captions from public/unlisted videos using the existing transcript service without consuming API quota
- **FR-002**: System MUST collect captions from private videos using OAuth-authenticated Captions API with force-ssl scope
- **FR-003**: System MUST parse SRT-format captions from Captions API into timestamped segments consistent with the existing transcript format
- **FR-004**: System MUST track per-video processing status (pending, collecting, collected, failed, no_caption) and resume from the last checkpoint on re-execution
- **FR-005**: System MUST perform incremental collection — skip videos whose captions have already been collected

**재사용 탐지**
- **FR-006**: System MUST generate SHA-256 hash fingerprints from full caption text for each video
- **FR-007**: System MUST generate semantic embeddings from caption text using a multilingual sentence embedding model, running inference locally
- **FR-008**: System MUST automatically match comparison pairs using parsed title data: same professor + course + week + session across different years
- **FR-009**: System MUST compute 5 independent indicators for each comparison pair: hash match (I-1), cosine similarity (I-2), text change rate (I-3), new term count (I-4), duration difference (I-5)
- **FR-010**: System MUST calculate a composite suspicion score (0-100) from the 5 indicators and assign a priority grade (critical/high/moderate/normal)

**관리자 리뷰**
- **FR-011**: System MUST store comparison results with review status (UNREVIEWED, CONFIRMED_DUPLICATE, FALSE_POSITIVE)
- **FR-012**: System MUST allow administrators to update review status for each comparison pair
- **FR-013**: System MUST exclude previously reviewed pairs (CONFIRMED_DUPLICATE or FALSE_POSITIVE) from re-alerting in subsequent analyses

**품질 체크리스트**
- **FR-014**: System MUST check each video against quality rules: voice presence (Q-001), minimum duration (Q-002), course relevance (Q-003), silence ratio (Q-004), speech density (Q-005)
- **FR-015**: System MUST store per-video quality check results

**보고서**
- **FR-016**: System MUST generate content quality reports in HTML, Excel, and JSON formats
- **FR-017**: Reports MUST include: suspicion summary by priority grade, per-professor suspicion rates, content update details with term changes, quality checklist results, and review status summary

**파이프라인**
- **FR-018**: System MUST provide a single scan command that executes fingerprint → compare → quality sequentially with checkpoint support
- **FR-019**: System MUST provide individual commands for fingerprint, compare, quality, and review as separate steps

**데이터 저장**
- **FR-020**: System MUST use a local database for processing status, hash index, comparison results, and review status
- **FR-021**: System MUST store embedding vectors in columnar format for efficient vector operations
- **FR-022**: System MUST store raw caption data as per-video files consistent with existing project directory structure

### Key Entities

- **Video Caption**: Collected transcript text with timestamps, linked to a video ID. Source can be transcript-api (public) or Captions API (private)
- **Comparison Pair**: Two videos matched by professor + course + week + session across different years, forming the unit of reuse analysis
- **Comparison Result**: 5 indicator scores, composite suspicion score, priority grade, and administrator review status for a comparison pair
- **Caption Fingerprint**: SHA-256 hash and semantic embedding vector derived from a video's full caption text
- **Quality Check Result**: Per-video pass/fail results for quality rules Q-001 through Q-005
- **Processing Status**: Per-video tracking of collection and analysis pipeline stage, enabling resume and incremental processing

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Administrators can collect captions from all accessible videos in a department channel (including private videos) with a single command, resuming from checkpoint if interrupted
- **SC-002**: The system correctly identifies identical re-uploads (same caption text, different video IDs) with 100% accuracy via hash matching
- **SC-003**: The system produces a composite suspicion score for each comparison pair using at least 4 out of 5 indicators, with scores aligning to manual expert judgment in 90% of cases
- **SC-004**: Administrators can review all flagged videos by priority, spending less than 2 minutes per comparison pair to confirm or dismiss
- **SC-005**: Previously reviewed pairs are not re-flagged in subsequent analyses, reducing repeat review work to zero
- **SC-006**: The full analysis pipeline (fingerprint + compare + quality) for a department of 2,500 videos completes within 30 minutes of local processing time (excluding API quota wait time)
- **SC-007**: Quality checklist correctly identifies videos with no speech, under 5 minutes duration, or excessive silence in 95% of cases
- **SC-008**: Reports provide actionable information: administrators can identify the top 10 most suspicious videos within 1 minute of opening the report

## Assumptions

- OAuth authentication with youtube.force-ssl scope is available for all target department channels
- Existing title parsing (idea3) correctly extracts professor, course, week, and session for the majority of videos — parsing failures are expected for a small percentage
- Videos are primarily in Korean; the embedding model supports Korean text
- The system is operated by a single administrator at a time per department (no concurrent multi-user access required)
- Existing project directory structure (projects/{project}/01_collect, 02_analyze, 03_report) is preserved
- YouTube auto-generated captions (ASR) are available for approximately 99% of videos based on empirical measurement
- Daily API quota of 10,000 units is the baseline; quota increase requests may be filed separately
- idea3 metadata collection and title parsing have already been completed before running idea4 analysis
