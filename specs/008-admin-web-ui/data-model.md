# Phase 1 Data Model: 008-admin-web-ui

**Branch**: `008-admin-web-ui` | **Date**: 2026-04-28
**Sources**: [spec.md](./spec.md) Key Entities, [research.md](./research.md) §4–§5

## Storage Map

| Entity | Backing Store | Path | Format |
|--------|---------------|------|--------|
| Department | File (운영자 CLI 갱신) | `~/.config/tube-scout/departments.json` | JSON, atomic write |
| AnalysisJob | SQLite | `~/.local/share/tube-scout/admin.db` | Table `analysis_jobs` |
| AnalysisResult | SQLite + Filesystem | `admin.db` 테이블 + `projects/{job-id}/...` | Metadata in SQLite, artifacts in directory |
| ReviewStatus | SQLite (spec 007 통합) | `admin.db` `reuse_review_status` | Table |
| OperatorAction | SQLite | `admin.db` `operator_actions` | Append-only table |
| Session | Cookie | (서버 측 저장 없음) | itsdangerous-signed payload |
| LoginAttempt | In-memory dict | (영속 안 함) | `{username: (fail_count, locked_until)}` |

## Entities

### 1. Department

학과별 분석 자격 매핑. 운영자만 추가/수정.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `alias` | `str` | 영문 소문자·하이픈, 1–32자, 고유키 | 예: `physiology` |
| `display_name` | `str` | 한국어 1–32자, 고유 | 예: `물리치료과` |
| `channel_id_env` | `str` | `^TUBE_SCOUT_CHANNEL_ID_[A-Z0-9_]+$` | YouTube 채널 ID가 담긴 env 변수명 |
| `client_secret_env` | `str` | 동일 패턴 | OAuth 클라이언트 시크릿 env 변수명 |
| `api_key_env` | `str` | 동일 패턴 | YouTube Data API 키 env 변수명 |
| `registered_at` | `datetime` | ISO 8601 KST | 운영자 등록 시각 |
| `last_used_at` | `datetime \| None` | ISO 8601 KST or null | 마지막 분석 작업 사용 시각 |

**Validation rules**:
- `alias`는 `[a-z][a-z0-9-]{0,31}` 정규식 매칭(spec FR-005·FR-024).
- 환경변수 3종 모두 부팅 시 존재 검증 — 누락 시 해당 학과는 드롭다운에서 비활성 + 로그 경고(Constitution II Fail-Fast).
- `display_name`은 사용자에게 노출되는 유일한 식별자. alias·env 변수명은 UI에 절대 노출 금지(spec FR-004 / SC-006).

**Pydantic v2 모델 (web/repo/departments_repo.py에서 정의)**:
```python
class Department(BaseModel):
    alias: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    channel_id_env: Annotated[str, StringConstraints(pattern=r"^TUBE_SCOUT_CHANNEL_ID_[A-Z0-9_]+$")]
    client_secret_env: Annotated[str, StringConstraints(pattern=r"^TUBE_SCOUT_CLIENT_SECRET_[A-Z0-9_]+$")]
    api_key_env: Annotated[str, StringConstraints(pattern=r"^TUBE_SCOUT_API_KEY_[A-Z0-9_]+$")]
    registered_at: AwareDatetime
    last_used_at: AwareDatetime | None = None
```

---

### 2. AnalysisJob

한 번의 분석 실행 단위. 폼 제출로 생성, 백그라운드 워커가 갱신.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `job_id` | `str` | `^\d{8}-\d{6}(-\d+)?$`, PK | spec Q4: `YYYYMMDD-HHMMSS` + sub-second 충돌 시 `-2/-3` |
| `department_alias` | `str` | FK → Department.alias | |
| `professor_name` | `str` | 1–32자, NOT NULL | spec FR-005 |
| `course_name` | `str` | 1–64자, NOT NULL | spec FR-005 |
| `period_start` | `date` | NOT NULL, ≤ today | spec FR-007 |
| `period_end` | `date` | NOT NULL, ≥ period_start | spec FR-007 |
| `status` | `enum` | `pending \| running \| completed \| failed \| interrupted` | spec FR-021 |
| `current_stage` | `enum \| None` | `listing \| metadata \| transcripts \| retention \| analytics \| reuse_detection \| reporting \| done` | 7단계 + done |
| `processed_count` | `int` | ≥ 0 | 단계별 처리 영상 수 |
| `total_count` | `int` | ≥ 0 | 단계별 전체 영상 수 |
| `result_dir` | `str \| None` | 절대 경로 | `projects/{job_id}/` |
| `started_at` | `datetime` | NOT NULL | 큐 등록 시각 |
| `completed_at` | `datetime \| None` | ≥ started_at if set | |
| `error_code` | `str \| None` | enum(`oauth_expired`, `quota_exceeded`, `no_videos`, `internal`, ...) | 한국어 메시지 매핑 키 |
| `error_detail` | `str \| None` | (영문 로그 전용) | UI 비노출 |
| `created_by` | `str` | 단일 사용자 ID | `created_by` 항상 동일하지만 미래 확장 대비 |

**State Transitions** (spec FR-022, FR-022a):

```
        ┌──────────┐  start work
[ POST ]│ pending  │ ───────────► running
   │    └──────────┘
   ▼
running ─── stage progresses ───► running (current_stage 갱신)
running ─── all 7 stages done ───► completed
running ─── exception ───────────► failed (error_code/detail 기록)
running ─── server restart ─────► interrupted (lifespan 종료 시 일괄 표시)
{failed,interrupted} ── retry ──► running (checkpoint resume; 새 job_id 발급)
```

**검증 규칙**:
- `period_start ≤ period_end` 필수(spec FR-007c).
- `period_start ≤ today`(spec FR-007d).
- 동일 `department_alias`로 `status in (pending, running)`인 다른 job 존재 시 신규 POST 거부(spec FR-028).
- `current_stage` 전이는 단조 증가(listing → metadata → transcripts → retention → analytics → reuse_detection → reporting → done). 후퇴 금지.
- `processed_count ≤ total_count` 항상 유지.

**SQLite 스키마**:
```sql
CREATE TABLE analysis_jobs (
    job_id TEXT PRIMARY KEY CHECK (job_id GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]*'),
    department_alias TEXT NOT NULL,
    professor_name TEXT NOT NULL,
    course_name TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','running','completed','failed','interrupted')),
    current_stage TEXT CHECK (current_stage IN ('listing','metadata','transcripts','retention','analytics','reuse_detection','reporting','done') OR current_stage IS NULL),
    processed_count INTEGER NOT NULL DEFAULT 0 CHECK (processed_count >= 0),
    total_count INTEGER NOT NULL DEFAULT 0 CHECK (total_count >= 0 AND total_count >= processed_count),
    result_dir TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    error_detail TEXT,
    created_by TEXT NOT NULL,
    CHECK (period_start <= period_end)
);
CREATE INDEX idx_jobs_started_at_desc ON analysis_jobs (started_at DESC);
CREATE INDEX idx_jobs_status_dept ON analysis_jobs (status, department_alias);
```

---

### 3. AnalysisResult

완료된 작업의 산출물 메타데이터. 실제 파일은 `projects/{job-id}/`에 저장.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `job_id` | `str` | PK, FK → AnalysisJob.job_id | |
| `report_v1v3_html` | `str \| None` | 상대 경로 | `projects/{job-id}/03_report/v1v3.html` |
| `report_v1v3_pdf` | `str \| None` | 상대 경로 | spec FR-016 |
| `report_v1v3_excel` | `str \| None` | 상대 경로 | |
| `report_reuse_html` | `str \| None` | 상대 경로 | spec 007 산출물 |
| `report_reuse_excel` | `str \| None` | 상대 경로 | |
| `matched_video_count` | `int` | ≥ 0 | 키워드 매칭 영상 수 |
| `suspicious_pair_count` | `int` | ≥ 0 | 재사용 탐지 의심 쌍 수 |
| `priority_summary` | `JSON` | `{critical:int, high:int, moderate:int, normal:int}` | spec 007 priority grade 카운트 |
| `generated_at` | `datetime` | NOT NULL | 보고서 생성 완료 시각 |

**검증 규칙**:
- 완료(`status=completed`) 작업만 본 레코드를 가짐. 실패/중단은 미생성.
- 파일 경로는 `result_dir` 하위 상대 경로로만 기록(절대 경로 traversal 차단).
- 다운로드 요청 시 실제 파일 존재 확인 + 없으면 spec FR-018 메시지(`projects/...` 직접 노출 금지).

**SQLite 스키마**:
```sql
CREATE TABLE analysis_results (
    job_id TEXT PRIMARY KEY REFERENCES analysis_jobs(job_id) ON DELETE CASCADE,
    report_v1v3_html TEXT,
    report_v1v3_pdf TEXT,
    report_v1v3_excel TEXT,
    report_reuse_html TEXT,
    report_reuse_excel TEXT,
    matched_video_count INTEGER NOT NULL DEFAULT 0 CHECK (matched_video_count >= 0),
    suspicious_pair_count INTEGER NOT NULL DEFAULT 0 CHECK (suspicious_pair_count >= 0),
    priority_summary TEXT NOT NULL,  -- JSON
    generated_at TEXT NOT NULL
);
```

---

### 4. ReviewStatus

재사용 탐지 영상 쌍의 사용자 검토 상태(spec 007 FR-011~013과 동일 모델, 본 idea의 웹 UI에서 변경).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `pair_id` | `str` | PK, spec 007 정의 따름 | 영상 쌍 고유 식별자(예: `vidA__vidB`) |
| `job_id` | `str` | FK → AnalysisJob.job_id | 최초 검출 작업 |
| `status` | `enum` | `unreviewed \| confirmed_duplicate \| false_positive` | spec 007 정의 |
| `updated_at` | `datetime \| None` | ISO 8601 KST | |
| `updated_by` | `str \| None` | 사용자 ID | 단일 사용자 ID(미래 확장 대비) |
| `note` | `str \| None` | 0–512자, 선택 | 사용자 메모 |

**상태 전이**:
```
unreviewed ──► confirmed_duplicate
unreviewed ──► false_positive
confirmed_duplicate ──► unreviewed (실수 정정)
false_positive ──► unreviewed
{confirmed_duplicate, false_positive} ──► 다음 분석에서 재경고 안 됨 (spec FR-020)
```

**SQLite 스키마**:
```sql
CREATE TABLE reuse_review_status (
    pair_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES analysis_jobs(job_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('unreviewed','confirmed_duplicate','false_positive')) DEFAULT 'unreviewed',
    updated_at TEXT,
    updated_by TEXT,
    note TEXT CHECK (note IS NULL OR length(note) <= 512)
);
CREATE INDEX idx_review_status ON reuse_review_status (status);
```

---

### 5. OperatorAction

운영자 동작 감사 로그(append-only).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | `int` | PK, autoincrement | |
| `action` | `enum` | `add_department \| oauth_consent \| token_refresh \| status_check \| verify` | |
| `target_alias` | `str \| None` | FK-soft → Department.alias | 일부 동작은 alias 무관 |
| `actor` | `str` | 운영자 식별자(시스템 사용자명 또는 환경변수) | |
| `at` | `datetime` | NOT NULL | |
| `result` | `enum` | `success \| failure` | |
| `detail` | `str \| None` | 영문 상세(로그 전용) | |

**SQLite 스키마**:
```sql
CREATE TABLE operator_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL CHECK (action IN ('add_department','oauth_consent','token_refresh','status_check','verify')),
    target_alias TEXT,
    actor TEXT NOT NULL,
    at TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('success','failure')),
    detail TEXT
);
CREATE INDEX idx_op_at_desc ON operator_actions (at DESC);
```

---

### 6. Session (쿠키 페이로드)

서버 측 저장 없음 — itsdangerous 서명 후 쿠키에 보관.

```python
class SessionPayload(BaseModel):
    username: str          # agenix 주입 아이디와 일치
    issued_at: int         # Unix epoch (seconds)
    last_active: int       # Unix epoch (seconds)
    csrf_token: str        # 16바이트 랜덤 hex
```

**검증 규칙**:
- 서명 검증 실패 → 401 + 로그인 화면.
- `now - last_active > 8h` → 만료(spec FR-004a). 매 요청마다 `last_active` 갱신 + 쿠키 재서명.
- POST 요청은 `csrf_token` 폼 필드 일치 검증.

---

### 7. LoginAttempt (인메모리)

단일 사용자 환경에서 5회 잠금 추적.

```python
class LoginAttempt:
    fail_count: int        # 0 ~ 5
    locked_until: datetime | None  # None or future timestamp
    last_failure_at: datetime | None
```

**규칙**:
- 5회 연속 실패 시 `locked_until = now + 5min`(spec FR-004c).
- 잠금 기간 내 시도는 즉시 거부(403) + 잔여 시간 한국어 안내.
- 성공 시 `fail_count = 0`, `locked_until = None`.
- 프로세스 재시작 시 reset 허용(외부 DB 없음 정책 + 단일 사용자 위협 모델 수용).

---

## Relationships

```text
Department (1) ──── (∞) AnalysisJob (1) ──── (0..1) AnalysisResult
                            │
                            └── (∞) ReviewStatus

Department (1) ──── (∞) OperatorAction
```

- 카디널리티 / FK는 SQLite CHECK + REFERENCES로 강제.
- `Department` 삭제는 본 idea 범위 외(운영자가 수동으로 `departments.json` 편집 가능하지만 작업·결과·리뷰는 보존).

## Indexes Summary

| Table | Index | Purpose |
|-------|-------|---------|
| `analysis_jobs` | `idx_jobs_started_at_desc` | 이력 화면 최신순 정렬(spec FR-021) |
| `analysis_jobs` | `idx_jobs_status_dept` | 동일 학과 in-progress 조회(spec FR-028) |
| `reuse_review_status` | `idx_review_status` | 재사용 탐지 우선순위 필터 |
| `operator_actions` | `idx_op_at_desc` | CLI status 명령 — 최근 운영 동작 조회(spec FR-026) |

## Data Volume Estimates

| Entity | Rate | Year-1 Volume | 5-Year Volume |
|--------|------|---------------|---------------|
| Department | +1–2 / 년 | 10–20 행 | 20–30 행 |
| AnalysisJob | ~10–40 / 주 | 500–2,000 행 | 2,500–10,000 행 |
| AnalysisResult | ≤ AnalysisJob | 500–2,000 행 | 2,500–10,000 행 |
| ReviewStatus | ~20–100 / 주 | 1,000–5,000 행 | 5,000–25,000 행 |
| OperatorAction | ~5–20 / 월 | 100–250 행 | 500–1,250 행 |

→ SQLite 단일 파일이 5년 운영에도 충분(<100 MB metadata). 분석 산출물 디스크는 별도 운영자 관리.

## Security & Privacy

- **PII 저장 없음** — 교수명·과목명은 학과 내부 식별자(공개 강의 영상 메타데이터)이므로 별도 암호화 불필요.
- **시크릿 0건** — 본 데이터 모델의 어떤 테이블·파일에도 평문 시크릿 없음(Constitution VI).
- **SQLite 파일 권한** — 0600(소유자만 읽기/쓰기), systemd unit 또는 운영자 셋업 시 enforce.
- **로그 분리** — 영문 운영 로그(stdout + journald) vs 한국어 사용자 메시지(UI). 두 흐름이 절대 교차하지 않도록 `web/errors.py` 단일 매퍼 강제.
