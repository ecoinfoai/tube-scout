# Feature Specification: Subtitle Full-Stack Reuse Detection (nC2 + Time-axis + 4-Layer Defense)

**Feature Branch**: `011-reuse-fullstack-subtitle`
**Created**: 2026-05-09
**Status**: Draft
**Input**: idea/idea-2026-05-09-roadmap.md — tube-scout v0.4 자막 풀스택 출시. spec 007의 동일 교수·교과목·주차·차시 매칭 한계를 넘어, (1) nC2 cross-pair 매칭, (2) 시간축 지표 I-6/I-7/I-8, (3) Layer A/B/C/D 4계층 false-positive 방어, (4) 재활용 4 패턴 분리 검출을 추가한다. Cross-professor (spec 012), 외부 corpus (spec 013), 음원·프레임 신호 (v0.5+ spec X/Y/Z) 는 본 spec 의 scope OUT.

## Clarifications

### Session 2026-05-09

- Q: Phrase-level 화이트리스트의 적용 범위는? → A: Per-professor — 한 교수의 분석에만 적용 (Layer B baseline corpus와 동일 단위). Cross-professor 공유 화이트리스트는 v0.4 스코프에서 제외.
- Q: 장시간 nC2 분석이 중단됐을 때 재시작 단위는? → A: Per-pair — 각 비교 쌍 단위로 checkpoint 영속. 중단 시 미완료 쌍부터만 재개 (이미 산출된 쌍 결과는 재계산하지 않음).
- Q: Phrase 화이트리스트와 자막의 매칭 방식은? → A: Normalized exact — 공백·구두점·대소문자·전각/반각 정규화 후 exact 매칭. Raw exact는 ASR 노이즈에 취약, fuzzy는 과도 차단 위험으로 v0.4에서 채택하지 않음.
- Q: 한 교수 영상이 여러 채널에 분산된 경우 caption pool 경계는? → A: Cross-channel unified per professor — 채널 경계를 넘어 같은 교수 영상은 단일 풀로 통합 비교. 교수 동일성은 운영자가 등록한 명시적 매핑(별칭 → 교수 ID)에 근거.
- Q: Layer D 영속 계층(검토 상태 + phrase 화이트리스트)에 대한 동시 갱신 충돌 해결 정책은? → A: Single-active-admin assumption + advisory write lock — 프로젝트당 활성 관리자 1인 가정을 유지하되, 동시 쓰기 충돌이 실제 발생하면 두 번째 쓰기를 거부하고 명시적 경고를 사용자에게 표시 (silent data loss 차단). 다중 검토자 협업은 후속 spec에서.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - nC2 Cross-Pair Matching across Years and Courses (Priority: P1)

교무과 담당자가 한 교수의 자막 풀(여러 연도 × 여러 교과목)에서 가능한 모든 영상 쌍을 비교하여, 학기·교과목 경계를 넘는 재활용을 발견한다. spec 007의 강제 매칭(같은 교과목 + 같은 주차 + 같은 차시)에서는 누락되던 시나리오 — "2025년 1학기 A과목 4주차" vs "2026년 2학기 B과목 10주차" 같은 cross-course / cross-week 재활용 — 을 검출한다.

**Why this priority**: 운영자(홍길동·DX센터장)가 v0.4의 핵심 가치로 지목한 시나리오(PS-U-2/3a/3b/3c/3d). spec 007의 매칭은 같은 시점·같은 코스에서만 작동해 실제 재활용 패턴의 다수를 놓친다. 이 기능 없이는 v0.4 출시 의미가 없다.

**Independent Test**: 같은 교수의 2개 이상 영상 자막이 수집된 상태에서 nC2 매칭 모드를 지정해 분석을 실행하면, 모든 쌍에 대해 5+3 지표가 산출되고 의심 쌍이 정렬된다. spec 007의 default 모드와 결과를 비교하여 추가 검출 쌍이 드러난다.

**Acceptance Scenarios**:

1. **Given** 같은 교수의 2025년 A과목·2026년 B과목 자막이 수집된 상태, **When** nC2 매칭 모드로 분석을 실행하면, **Then** 두 영상 쌍이 비교 대상에 포함되고 종합 의심도가 산출된다
2. **Given** 한 교수가 4년치 6개 교과목 총 120개 영상의 자막을 보유한 상태, **When** nC2 매칭 모드로 분석을 실행하면, **Then** 120C2 = 7,140 쌍 중 의심도 임계 이상의 쌍만 결과에 노출된다 (전체 행렬을 보고서에 덤프하지 않는다)
3. **Given** 매칭 모드가 미지정인 상태, **When** 분석을 실행하면, **Then** spec 007의 default 모드(같은 교수·교과목·주차·차시)로 동작하여 기존 사용자 흐름이 깨지지 않는다
4. **Given** PS-U-3a (20분 통째 → 같은 주차) 와 PS-U-3c (20분 통째 → 다른 주차) 영상 쌍, **When** nC2 매칭으로 분석하면, **Then** 두 쌍 모두 검출되고 메타 차이(주차 동일 vs 상이)가 결과 레코드에 기록된다
5. **Given** 한 교수의 자막 풀에 다년 동일 과목(2025·2026 감염미생물학)과 다년 다른 과목이 섞여 있는 상태, **When** 분석을 실행하면, **Then** 결과가 (a) 같은 과목 다년 (b) 다른 과목 cross-pair 두 카테고리로 구분되어 보고된다

---

### User Story 2 - Time-axis Indicators (I-6 contiguous / I-7 distribution / I-8 position) (Priority: P1)

교무과 담당자가 의심 쌍에 대해 단순 cosine 유사도(I-2)뿐 아니라 "어디가, 얼마나 길게, 어떻게 분포되어 일치하는가"를 정량적으로 본다. 5분 차이 즉흥 응답과 20분 통째 재사용을 구별하고, 통째형(연속 일치)과 분산형(여러 짧은 일치)을 분리한다.

**Why this priority**: PS-U-3a/3b/3c/3d 4 패턴 구별은 시간축 지표 없이는 불가능하다. spec 007의 5 지표만으로는 "통째 20분"과 "5분×4 분산"이 같은 점수로 묻힌다. 등급 결정 + 검토 우선순위 + 정책 임계 모두 시간축 정보를 전제로 한다. P1로 분류되지만 US1의 nC2 매칭 위에 incremental하게 add되는 단계 — US1만 단독 출시 시 5-지표 cross-pair 검출은 가능하나 "통째/분산" 구별은 불가. 두 P1을 함께 출시하는 것이 v0.4 본 의미.

**Independent Test**: 의도적으로 (a) 20분 통째 일치 (b) 5분×4 분산 일치 (c) 즉흥 5분 차이 자막 쌍을 만들고 분석하면, I-6/I-7/I-8 지표가 세 케이스를 각각 다른 값으로 산출한다. (US1의 nC2 pair 생성 위에 동작하므로 US2 단독 RED→GREEN 사이클은 합성 caption 쌍 직접 입력으로도 가능 — 통합은 US1 산출 후.)

**Acceptance Scenarios**:

1. **Given** 두 영상 자막에 20분 연속 동일 구간이 있는 쌍, **When** 분석을 실행하면, **Then** I-6(최장 연속 일치 길이)이 ≥ 1,200초로 기록되고 I-7(일치 분포 표준편차) 은 작게 기록된다
2. **Given** 두 영상 자막에 5분×4회 분산 일치가 있는 쌍, **When** 분석을 실행하면, **Then** I-6 ≈ 300초, I-7 (분산도) ≥ 임계, I-8 (위치 다양성) 큰 값으로 통째형과 구별된다
3. **Given** 2분 짧은 즉흥 일치만 있는 쌍, **When** 분석을 실행하면, **Then** I-6 < Layer A 임계 → 의심 쌍 후보에서 자동 제외된다
4. **Given** I-6/I-7/I-8 결과가 산출된 상태, **When** 보고서를 생성하면, **Then** 각 의심 쌍에 4 패턴 라벨(통째-동일주 / 통째-다른주 / 분산-동일주 / 분산-다른주) 중 하나가 부여된다

---

### User Story 3 - 4-Layer False-Positive Defense (Layer A/B/C/D) (Priority: P1)

교무과 담당자가 "정상 진화" 또는 "교수 고유 어법 반복" 등 무해한 일치를 자동으로 걸러낸다. 길이 기반 사전 필터(A), 교수별 baseline corpus 차감(B), 등급 컷(C), 누적 화이트리스트(D)의 4단계 중 어느 하나가 통과를 막으면 의심 쌍에서 제외 또는 등급 강등된다.

**Why this priority**: nC2 + 시간축은 검출률을 높이지만 동시에 false positive도 폭증한다. 4계층 방어 없이는 검토자 부담이 운영 가능 수준을 넘는다. 운영자가 "교수의 대티역 비유" 같은 stylistic recurrence가 매번 의심 쌍에 등장하는 것을 명시적으로 거부했다(PS-U-4).

**Independent Test**: (a) 의도적으로 짧은 즉흥 일치만 있는 쌍 (b) 교수가 매년 반복하는 비유가 포함된 쌍 (c) 70% 동일하지만 30% 새로 갱신된 쌍 (d) 직전 분석에서 FALSE_POSITIVE 마킹된 쌍 — 네 케이스를 입력하면 각각 Layer A/B/C/D 가 차단/강등하고 그 이유가 결과 레코드에 기록된다.

**Acceptance Scenarios**:

1. **Given** 두 영상 자막의 일치 구간이 모두 Layer A 길이 임계 미만인 쌍, **When** 분석을 실행하면, **Then** 해당 쌍은 의심 쌍 목록에서 제외되고 사유 "filtered_by_layer_a"가 기록된다
2. **Given** 교수의 baseline corpus 가 등록되어 "대티역 비유" 등 반복어가 학습된 상태, **When** 같은 표현이 두 영상에 등장한 쌍을 분석하면, **Then** Layer B가 해당 일치 분량을 차감하여 I-2/I-6 수치가 baseline 차감 후 값으로 보정된다
3. **Given** 두 영상이 70% 동일하나 정상 연도별 진화에 해당하는 쌍, **When** 분석을 실행하면, **Then** Layer C 등급 컷에 따라 "정상 진화" 또는 "참고" 등급으로 분류되고 "최우선" 등급에서는 제외된다
4. **Given** 직전 분석에서 FALSE_POSITIVE로 마킹된 쌍, **When** 다음 분석을 실행하면, **Then** Layer D가 해당 쌍을 재알림 대상에서 자동 제외한다 (spec 007 의 review 행위가 nC2 결과에도 동일하게 작동)
5. **Given** 한 교수의 baseline corpus가 미등록 상태, **When** 분석을 실행하면, **Then** Layer B는 "no baseline" 으로 통과(차감 없음)하고 그 사실이 보고서에 명시된다 (정상 동작 — corpus 누적은 운영 시간이 필요하므로)

---

### User Story 4 - Whitelist-Accumulating Review Workflow (Layer D Operation) (Priority: P2)

교무과 담당자가 의심 쌍을 검토하면서 "오탐" 마킹을 누적해, 같은 쌍 또는 같은 어구가 다음 분석에서 재알림되지 않게 한다. 검토 단위는 (a) 쌍(pair-level) (b) 일치 어구(phrase-level) 둘 다 지원한다.

**Why this priority**: spec 007의 review (FR-013) 가 이미 pair-level whitelist 를 구현했으나, nC2 모드에서는 같은 어구가 여러 쌍에 반복 출현하므로 phrase-level 화이트리스트가 필수다. 운영 1년차에는 pair-level 만으로도 작동하므로 P2.

**Independent Test**: 검토 화면에서 (a) 쌍을 FALSE_POSITIVE 로 마킹 (b) 일치 어구를 화이트리스트에 추가한 후, 같은 분석을 재실행하면 두 입력 모두 재알림 0건으로 반영된다.

**Acceptance Scenarios**:

1. **Given** nC2 분석 결과의 의심 쌍 목록, **When** 담당자가 한 쌍을 "오탐" 으로 마킹하면, **Then** 해당 쌍이 Layer D whitelist 에 누적되고 다음 분석에서 자동 제외된다
2. **Given** 한 일치 어구("이 부분은 수업 시작 인사말입니다")가 여러 쌍에 반복 출현, **When** 담당자가 그 어구를 phrase-whitelist 에 추가하면, **Then** 다음 분석부터 해당 어구는 모든 쌍에서 일치 분량 계산에서 제외된다
3. **Given** 직전 분석에서 CONFIRMED_DUPLICATE 로 마킹된 쌍, **When** 다음 분석을 실행하면, **Then** 해당 쌍은 결과에 "이미 확인됨" 라벨로 표시되며 우선순위 큐에는 다시 올라가지 않는다
4. **Given** Layer D whitelist 가 누적된 상태, **When** 운영자가 화이트리스트를 export 하면, **Then** 사람이 읽을 수 있는 형식으로 항목·등록 사유·등록자·등록일이 함께 출력된다

---

### User Story 5 - Reports with 4-Pattern Classification and Time-axis Evidence (Priority: P2)

교무과 담당자가 분석 결과 보고서에서 의심 쌍을 4 재활용 패턴별로 분리하여 보고, 각 쌍의 시간축 증거(연속 일치 구간 위치 + 분포)를 시각적으로 확인한다.

**Why this priority**: 검출 + 방어가 작동하더라도 보고서가 4 패턴을 구별해 보여주지 않으면, 교무 회의에서 "통째 20분 재활용"과 "5분×4 분산 재활용"이 같은 등급으로 묻혀 정책 결정이 어렵다. spec 007 보고서 형식의 점진적 확장.

**Independent Test**: 4 패턴이 섞인 의심 쌍 데이터에서 보고서를 생성하면, 패턴별 섹션 분리 + 의심 쌍별 시간축 증거 시각화가 포함된다.

**Acceptance Scenarios**:

1. **Given** nC2 분석 결과에 4 패턴이 섞여 있는 상태, **When** HTML 보고서를 생성하면, **Then** 4 패턴별로 섹션이 분리되고 각 섹션에 의심 쌍 표가 표시된다
2. **Given** 의심 쌍 한 건, **When** 상세 화면을 열면, **Then** 두 영상의 시간축에 일치 구간이 색칠된 막대 그래프 + 일치 어구 샘플이 함께 표시된다
3. **Given** Layer B baseline 차감이 일어난 쌍, **When** 보고서를 생성하면, **Then** 차감 분량과 차감 후 의심도가 함께 표시되어 운영자가 baseline 작동을 확인할 수 있다
4. **Given** Layer D whitelist 에 의해 제외된 쌍이 직전 분석 대비 N건 존재하는 상태, **When** 보고서를 생성하면, **Then** "whitelist에 의해 제외된 쌍 N건" 요약 줄이 헤더에 명시된다 (검출 누락 우려 방지)

---

### Cross-Spec Boundaries *(mandatory — Constitution Principle VII)*

본 spec이 공유하는 모든 seam과 boundary contract. 각 항목은 plan.md `Cross-Spec Boundaries` 표(B-1~B-10)와 1:1 대응되며 contract 테스트로 강제된다.

| # | 상대 spec / 시스템 | 공유 자산 | 사전 측 보장 | 본 spec 가정 / 신규 산출 | 검증 acceptance |
|---|---|---|---|---|---|
| B-1 | spec 003 multichannel-admin | `channels.json` 별칭 레지스트리, `--channel <alias>` flag | 별칭 → channel_id 매핑은 spec 003이 권위 | 본 spec은 별칭만 받아 spec 003 레지스트리에서 channel_id 해석. 신규: `(channel_alias, author_marker)` → professor_id 매핑 테이블 추가 | US1 #5 + 신규 boundary 시나리오: 새 alias 등록 → professor map prompt → nC2 풀 산정 |
| B-2 | spec 007 content-reuse-detection | `content_reuse.db`, `embeddings.parquet`, `02_analyze/content/` | spec 007 schema·indicator 산출은 권위. fingerprint·embedding 변경 금지 | (a) `comparison_results` 컬럼 ALTER (i6/i7/i8/pattern/baseline_subtracted/layer_attribution/matching_mode/professor_id), (b) 신규 테이블 6개 추가, (c) `review_status` enum에 `PENDING` 추가 | FR-026 + SC-009: spec 007 데이터로 spec 011 분석 시 caption 재수집·embedding 재산출 0건 |
| B-3 | spec 010 prefer-captions-resume | `01_collect/transcripts/{video_id}.json`, `transcripts_audit.csv` | spec 010이 자막 수집 idempotent 보장 | 자막 수집 호출 0회. 누락 자막은 `transcripts_audit.csv` 참조 + 영문 actionable 메시지로 fail-fast | quickstart §3 대비 + 누락 자막 케이스 integration 테스트 |
| B-4 | spec 002/004/006 reporting | `03_report/` 트리, `bundle_report.py`, plotly/jinja2 templates | 기존 report bundling 권위 | (a) `03_report/content/v2/` 하위에 4 패턴 분리 HTML, (b) Excel 탭 추가, (c) 시간축 visualization plotly-static. 기존 보고서 변경 없음 | US5 acceptance + 기존 report 회귀 테스트 |
| B-5 | spec 008 admin-web-ui | `tube-scout-admin` web 서비스 | 본 spec service-layer 호출 | 신규 service-layer 시그니처 동결 (`contracts/service_layer.md`). spec 008은 CLI 우회하지 않고 동일 service 호출 | contract 테스트 — spec 008 web 라우트가 import해 호출하는 모든 함수 시그니처 일치 |
| B-6 | spec 009 runtime-auth-fix | `~/.config/tube-scout/tokens/{alias}.json`, `resolve_channel_alias()` | 별칭 인증 권위 | 본 spec은 token 사용 0회. 풀 정의 시 `resolve_channel_alias()` 재사용 (직접 channels.json 파싱 금지) | 모든 신규 CLI는 `--channel <alias>`만 받고 spec 009 helper 사용 |
| B-7 | 출력 디렉터리 컨벤션 | `projects/{job-id}/{01_collect,02_analyze,03_report}` | Constitution Principle V | `02_analyze/content/v2/` 하위 subdir 사용. 기존 `02_analyze/content/`는 유지 | quickstart §13: 같은 project_dir에 spec 007/011 두 결과 공존 |
| B-8 | spec 014 UI redesign (future) | 본 spec service 계층 + DB schema | 본 spec backend 산출물 안정 | review state mutation API + phrase whitelist mutation API + baseline mutation API 시그니처 `contracts/service_layer.md`에 동결 → spec 014가 binding | spec 014 specify 시 본 contracts 직접 인용 |
| B-9 | agenix secret store | (해당 없음) | — | 본 spec 신규 secret 0개 | — |
| B-10 | Constitution Principle II 영문 에러 | 모든 신규 에러 메시지 영문 | — | 영문 + actionable instruction (예: 누락 baseline corpus → `"No baseline corpus for professor <id>; run 'tube-scout content baseline bootstrap --professor <id>' first"`) | adversary 테스트: 누락 자막·매핑·baseline 케이스 영문 + actionable 검증 |

**Boundary failure-mode 원칙**: 위 어떤 경계 자산도 누락되면 본 spec의 명령은 silent fallback 없이 fail-fast하고, 영문 + 다음 명령을 알려주는 메시지를 반환한다 (Constitution II).

### Edge Cases

- 한 교수의 영상 풀이 1개뿐인 경우, nC2 비교 쌍이 0이므로 분석은 정상 종료되고 결과 0건이 보고된다
- 한 교수의 영상 풀이 200개 이상이어서 nC2가 ~20,000 쌍이 되는 경우, Layer A 사전 필터로 후보를 줄인 후에만 시간축 지표를 계산해 처리 시간을 운영 가능 범위로 유지한다
- 두 영상의 자막 길이가 극단적으로 다른 경우(5분 vs 90분), 짧은 쪽 전체와 긴 쪽 일부의 일치를 검출하되 일치 비율은 짧은 쪽을 분모로 한다
- baseline corpus 가 학습되기 전 첫 분석은 Layer B 비활성으로 동작하고, 이를 보고서에 명시한다
- 자막 일부 구간이 ASR 노이즈로 손상된 경우, 해당 구간은 일치 계산에서 제외하되 전체 분석은 계속 진행한다
- 두 영상의 발화 속도가 크게 다른 경우(예: 1.5배속 재녹화), v0.4 스코프에서는 일치 비율이 낮게 산출될 수 있고 이는 v0.8 DTW 도입까지의 알려진 한계로 명시한다
- 한 학기 내 같은 교과목의 재촬영 영상 2개 (재촬영 직후) — nC2 모드가 두 영상을 비교하면 자연히 매우 높은 의심도가 산출되며, 운영자가 검토에서 정상 사례로 마킹하면 다음 분석부터 화이트리스트로 제외된다

## Requirements *(mandatory)*

### Functional Requirements

**매칭 (nC2 모드)**

- **FR-001**: System MUST support an `M-nC2` matching mode that, for a single professor's caption pool, generates all nC2 video pairs across years and courses
- **FR-002**: System MUST preserve the existing `M-default` mode (same professor + course + week + session, from spec 007) as the default when no mode is specified, ensuring backward compatibility
- **FR-003**: System MUST tag each comparison result with metadata flags identifying whether the pair shares year / course / week / session, enabling 4-pattern classification downstream
- **FR-004**: System MUST scope `M-nC2` to a single professor's pool by default; cross-professor matching is explicitly out of scope and deferred to spec 012
- **FR-032**: System MUST unify a professor's caption pool across multiple channels — when a professor's videos exist on more than one registered channel (e.g., department main + course-specific + personal), `M-nC2` MUST treat them as a single pool. Professor identity across channels is established via an operator-maintained mapping (channel alias + author identifier → professor ID); pairs without an explicit mapping fall back to per-channel scoping

**시간축 지표 (I-6 / I-7 / I-8)**

- **FR-005**: System MUST compute I-6 (longest contiguous matching span, in seconds) for each comparison pair using aligned caption segments
- **FR-006**: System MUST compute I-7 (distribution of matching spans, expressed as a dispersion measure such as standard deviation of span lengths or count of distinct match clusters)
- **FR-007**: System MUST compute I-8 (positional diversity of matching spans across the video timeline, e.g., spread across early/middle/late thirds)
- **FR-008**: System MUST extend the composite suspicion score (originally 0–100, 5-indicator) to incorporate I-6/I-7/I-8 while preserving the same 0–100 range and grade buckets (critical / high / moderate / normal)
- **FR-009**: System MUST classify each surviving comparison pair into exactly one of 4 reuse patterns: whole-same-week, scattered-same-week, whole-different-week, scattered-different-week — using thresholds derived from I-6 (whole vs scattered ratio against the shorter video duration), I-7 (distribution dispersion as a tie-break for boundary cases), and the week-equality flag from FR-003

**4계층 방어 (Layer A / B / C / D)**

- **FR-010**: Layer A — System MUST exclude comparison pairs whose I-6 (longest contiguous match) is below a configured length threshold, with the threshold value loaded from project policy configuration (default value documented in Assumptions)
- **FR-011**: Layer B — System MUST maintain a per-professor baseline corpus of recurring stylistic phrases (e.g., habitual analogies, opening/closing remarks) and subtract their contribution from I-2 / I-6 / I-7 before composite scoring. Phrase-to-caption matching for baseline subtraction uses the same normalized-exact comparison defined in FR-015 (whitespace collapse, punctuation strip, case folding, full-width/half-width unification)
- **FR-012**: Layer B — System MUST allow the baseline corpus to be (a) bootstrapped from a professor's earliest N videos (admin-configurable) and (b) incrementally updated when admins mark phrases as recurring stylistic
- **FR-013**: Layer C — System MUST apply grade cuts that demote pairs which exceed a similarity threshold but fall within an "expected gradual evolution" range (e.g., 60–75% identical) to the moderate or normal grade rather than critical
- **FR-014**: Layer D — System MUST persist a whitelist with two granularities: (a) per-pair (specific video pair marked FALSE_POSITIVE) and (b) per-phrase (specific phrase string excluded from match counting across all pairs of a single professor — scope is per-professor, mirroring Layer B baseline corpus scope)
- **FR-015**: Layer D — System MUST consult the whitelist before publishing comparison results: pair-level matches are removed from the suspect queue, phrase-level matches are removed from match-span calculations. Phrase-level matching uses normalized-exact comparison: whitespace collapse, punctuation strip, case folding, and full-width/half-width unification are applied to both the registered phrase and the caption text before exact-string equality is evaluated. Fuzzy or edit-distance matching is explicitly out of scope for v0.4
- **FR-016**: System MUST record, for each comparison pair, which Layer (A / B / C / D) — if any — affected the result, and surface this attribution in the report

**리뷰 워크플로**

- **FR-017**: System MUST allow administrators to mark a comparison pair as one of UNREVIEWED (initial state, inherited from spec 007), PENDING (review started but not concluded — new in spec 011), CONFIRMED_DUPLICATE, or FALSE_POSITIVE — extending spec 007's review states with explicit Layer D whitelist propagation
- **FR-018**: System MUST allow administrators to add a matched phrase to the phrase-level whitelist with mandatory metadata: phrase text, registering admin, registration date, free-text reason
- **FR-019**: System MUST provide an export of the current whitelist (both pair-level and phrase-level) in a human-readable format for audit and policy review
- **FR-033**: System MUST serialize concurrent writes to Layer D persistence (review status updates and phrase-whitelist additions) via an advisory write lock. The system assumes a single active administrator per project; if a second concurrent write is attempted, the second writer MUST be rejected with an explicit conflict notification (no silent data loss). Multi-administrator collaborative review is deferred to a follow-on specification

**보고서**

- **FR-020**: HTML reports MUST group suspect pairs into the 4 reuse-pattern sections defined in FR-009
- **FR-021**: Reports MUST include a per-pair time-axis visualization showing match-span positions on each of the two video timelines
- **FR-022**: Reports MUST display, for pairs affected by Layer B, the pre-subtraction and post-subtraction indicator values so administrators can audit baseline behavior
- **FR-023**: Reports MUST surface a header summary line stating the count of pairs excluded by Layer D in the current run, to prevent silent suppression concerns
- **FR-024**: Excel reports MUST include a sheet listing all whitelist entries (pair + phrase) used in the run

**파이프라인 + 호환성**

- **FR-025**: System MUST extend the existing `scan` pipeline (spec 007 FR-018) so that selecting `M-nC2` does not require additional commands beyond the existing scan invocation
- **FR-026**: System MUST preserve all spec 007 outputs (5 indicators, suspicion score, grade, review status) so that existing reports and downstream consumers continue to function
- **FR-027**: System MUST treat policy thresholds (Layer A length, Layer C grade cuts, I-6/I-7/I-8 weights in composite score) as project-level configuration, not hard-coded constants, with default values documented and overridable per project
- **FR-031**: System MUST persist comparison results at per-pair granularity such that an interrupted `M-nC2` run can resume from the next unfinished pair without recomputing pairs whose results were already stored. This applies whether the interruption is operator-triggered, system crash, or mid-pipeline error

**Out of scope (explicit)**

- **FR-028**: System MUST NOT implement cross-professor matching — that capability is reserved for spec 012
- **FR-029**: System MUST NOT implement audio-fingerprint, frame-hash, Whisper-STT, or DTW-based reuse detection — these are reserved for v0.5+ specs (X / Y / Z and a future DTW spec)
- **FR-030**: System MUST NOT implement OCR-based slide reuse detection or speaker diarization — these are permanently out of project scope

### Key Entities *(include if feature involves data)*

- **Caption Pool** — Per-professor collection of all available video captions, used as the input universe for `M-nC2` pair generation. Bounded by professor identity (resolved via the operator-maintained channel-alias + author → professor mapping introduced in FR-032); not bounded by year, course, week, session, or channel.
- **Matching Mode** — A selection of `M-default` (spec 007 backward-compatible) or `M-nC2` that controls how comparison pairs are generated from a Caption Pool.
- **Time-axis Indicator Set** — The triple (I-6, I-7, I-8) computed per Comparison Pair, capturing contiguous span length, span distribution, and span position. Stored alongside the existing 5 indicators.
- **Reuse Pattern Label** — One of (whole-same-week, scattered-same-week, whole-different-week, scattered-different-week), assigned per Comparison Pair, used for report grouping.
- **Stylistic Baseline Corpus** — Per-professor list of recurring phrases (with frequency and source-video evidence) that Layer B subtracts from match calculations. Grows over operating time.
- **Layer Attribution Record** — Per Comparison Pair, a record of which of Layer A / B / C / D acted on the result and what effect it had (excluded, demoted, value-adjusted, no-op).
- **Whitelist Entry** — Either a pair-level (video_id_a, video_id_b) marker or a phrase-level (phrase_text, professor_id, reason, admin, date) marker. Phrase-level entries are scoped per-professor and apply only to comparison pairs within that professor's caption pool. Persisted across analysis runs.
- **Policy Configuration** — Project-level settings for Layer A length threshold, Layer C grade cut bands, and composite-score weights for I-1..I-8. Editable by administrators outside the analysis runtime.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can run a single `M-nC2` analysis on one professor's pool of up to 200 videos and complete within 30 minutes of local processing time, excluding any quota-bound steps
- **SC-002**: For the 4 PS-U-3 patterns (whole-same-week / scattered-same-week / whole-different-week / scattered-different-week), the system assigns each test pair to its correct pattern label in 95% of cases on a labelled fixture set
- **SC-003**: Operators can identify and act on at least one pattern-pair (e.g., whole-different-week) in under 2 minutes after opening the report, by virtue of pattern-grouped sections (FR-020)
- **SC-004**: After Layer B baseline accumulates from at least the 5 earliest videos of a professor, recurring stylistic matches (PS-U-4 e.g., "대티역" analogy) appear in at most 10% of suspect pairs that they would have appeared in without Layer B
- **SC-005**: After an operator marks a pair FALSE_POSITIVE or adds a phrase to the whitelist, the next analysis run shows zero re-alerts for that pair or phrase
- **SC-006**: The 22-channel × ~4,000-video dataset (operator's full corpus) completes a full nC2 + 4-layer analysis in a single overnight admin run on the operating workstation, without manual intervention between channels
- **SC-007**: Composite suspicion scores correlate with human expert judgment in 90% of cases on a labelled validation set of 100 pairs covering all 4 patterns plus stylistic recurrence and gradual evolution
- **SC-008**: Reports unambiguously distinguish "pair excluded by Layer D" from "no match found" in the run header, so operators never silently lose visibility on previously confirmed positives without explicit numeric attribution
- **SC-009**: Backward compatibility — a project that has previously run spec 007 analysis can run the spec 011 analysis without re-collecting captions, re-deriving fingerprints, or losing any prior review state

## Assumptions

- The default Layer A length threshold is 60 seconds (1 minute) of contiguous match — short enough to capture meaningful substantive reuse, long enough to filter most casual greetings and one-liners. Operators may adjust per project before running analysis.
- The default Layer C grade-cut band for "expected gradual evolution" is 60–75% similarity at the I-2 level, demoting affected pairs to moderate grade — to be calibrated against the policy document referenced in idea/idea-2026-05-09-roadmap.md §7.4 PS-A-13 before production rollout.
- The composite suspicion score continues to use the spec 007 0–100 range with grade buckets (≥80 critical, 60–79 high, 40–59 moderate, <40 normal). I-6/I-7/I-8 are folded in via additional positive-evidence weighting, with default weights tuned so that whole-week reuse on its own can reach the critical bucket, and scattered-different-week reuse exceeds the moderate bucket.
- Layer B baseline corpus bootstraps from the earliest 5 videos per professor by default; phrases occurring in ≥3 of those 5 are seeded as baseline. Operators can adjust this bootstrap parameter and can manually add phrases.
- Whitelist storage reuses the spec 007 review-status persistence layer extended with a phrase table; no separate database technology is introduced.
- Operators run nC2 analysis on a per-professor basis; cross-professor scope is deferred (spec 012). A whole-channel run is the union of per-professor runs. The active administrator count per project is one (consistent with spec 007 SC-014 baseline); multi-admin collaborative review is deferred to a follow-on specification.
- Caption captions used by spec 011 are those already collected by spec 007 + spec 010 pipelines (`tube-scout collect transcripts --prefer-captions-api`); no new caption-collection logic is introduced in this spec.
- Korean-primary captions remain the primary target; multilingual embedding behavior inherited from spec 007 is preserved (PS-A-10 code-switching is unchanged).
- All policy thresholds in FR-027 default to values that are conservative (favoring recall over precision) for v0.4 launch, on the assumption that operators will calibrate during the first 2–4 weeks of operation by reviewing FALSE_POSITIVE patterns.
- SC-007 (90% expert correlation on a 100-pair labelled validation set) is a calibration-phase gate, not a launch-blocking gate. Spec 011 launches with the test scaffold present (`tests/perf/test_expert_correlation.py`) but the labelled fixture (`tests/fixtures/spec011/expert_validation/labelled_100.json`) is built incrementally during the first 2–4 weeks of operator review. Once present, the test transitions from `skip` to `assert correlation >= 0.90` and becomes a hard gate for v0.5 entry.
- Existing project directory layout (`projects/{project}/01_collect`, `02_analyze`, `03_report`) is preserved; spec 011 outputs live alongside spec 007 outputs in `02_analyze` with a versioned subdirectory.
- The web UI changes required to surface 4 reuse-pattern sections, time-axis visualizations, and phrase-whitelist editing belong to the companion spec 014 (UI redesign); spec 011 exposes these as backend data + report content but does not redesign the UI.
