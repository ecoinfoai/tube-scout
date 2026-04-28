# Contract: HTTP Routes (008-admin-web-ui)

**Branch**: `008-admin-web-ui` | **Date**: 2026-04-28
**Sources**: [spec.md](../spec.md) FR-001~031, [data-model.md](../data-model.md), [research.md](../research.md)

본 문서는 ASGI 앱이 노출하는 HTTP 라우트 계약을 정의한다. 각 계약은 `tests/contract/test_*_routes.py`에 RED 테스트로 먼저 작성되어야 한다(Constitution I).

## 공통 규약

- **Base URL**: 운영 환경에서는 리버스 프록시가 `https://<host>/`로 노출, ASGI 앱은 `http://127.0.0.1:8000/`(또는 unix socket).
- **요청 본문**: 폼은 `application/x-www-form-urlencoded`, 일부 GET은 query string. JSON API는 진행률·리뷰 변경 등 일부 엔드포인트만.
- **응답**:
  - HTML: Jinja2 렌더링(라우트 표에서 `text/html`로 표시)
  - JSON: `application/json; charset=utf-8`
  - 파일: `FileResponse` + `Content-Disposition`
- **인증**: `/login` 경로 외 모든 라우트는 미인증 시 302 → `/login?next=<path>`(spec FR-002)
- **CSRF**: 모든 POST/PUT/PATCH/DELETE는 폼 필드 또는 헤더 `X-CSRF-Token` 필수
- **세션**: 서명 쿠키(itsdangerous), 8h 만료(spec FR-004a)
- **에러 표준**: 4xx는 한국어 메시지(폼 또는 JSON `error_message_kr`), 5xx는 "내부 오류" + 영문 상세 로그

## Route Inventory

| Method | Path | Auth | Body | Response | Spec |
|--------|------|:----:|------|----------|------|
| GET | `/` | ✅ | — | 302 → `/jobs/new` 또는 `/login` | FR-002 |
| GET | `/login` | ❌ | — | 200 `text/html` 로그인 폼 | FR-001 |
| POST | `/login` | ❌ | form | 302 또는 200 with error | FR-001, FR-004c |
| POST | `/logout` | ✅ | csrf | 302 → `/login` | — |
| GET | `/jobs/new` | ✅ | — | 200 `text/html` 분석 폼 | FR-005~006 |
| POST | `/jobs` | ✅ | form | 302 → `/jobs/{job_id}` 또는 200 with errors | FR-006~011, FR-028 |
| GET | `/jobs/{job_id}` | ✅ | — | 200 `text/html` 진행률 또는 결과 화면 | FR-008~014, FR-022 |
| GET | `/jobs/{job_id}/progress` | ✅ | — | 200 JSON 진행률 | FR-013 |
| GET | `/jobs/{job_id}/results` | ✅ | — | 200 `text/html` 결과 화면 | FR-016, SC-004 |
| GET | `/jobs/{job_id}/files/{kind}` | ✅ | — | 200 file or 404 | FR-016, FR-018 |
| POST | `/jobs/{job_id}/retry` | ✅ | csrf | 302 → 새 `job_id` | FR-022a |
| GET | `/history` | ✅ | query | 200 `text/html` 이력 목록 | FR-021 |
| POST | `/jobs/{job_id}/reviews/{pair_id}` | ✅ | form | 302 또는 200 | FR-019, FR-020 |
| GET | `/healthz` | ❌ | — | 200 `text/plain` `ok` | (운영) |

---

## Detailed Contracts

### POST /login

**요청** (form-urlencoded):
```
username=<str>&password=<str>&csrf_token=<str>
```

**검증**:
- `username`, `password` 1–128자.
- 잠금 상태(`LoginAttempt.locked_until > now`) → 403 + `잔여 잠금 시간: NN초`.
- bcrypt 검증 실패 → `fail_count += 1`. 5회 도달 시 `locked_until = now + 5min`.

**응답**:
- 성공: 302 → `next` (없으면 `/jobs/new`), `Set-Cookie: session=<signed>; HttpOnly; Secure; SameSite=Lax; Max-Age=28800`
- 실패: 200 `text/html` 로그인 폼 + 한국어 오류
- 잠금: 403 `text/html` + 잔여 시간 안내

**한국어 메시지 매핑**:
| 코드 | 메시지 |
|------|--------|
| `auth.bad_credentials` | "아이디 또는 비밀번호가 올바르지 않습니다." |
| `auth.locked` | "로그인이 잠겼습니다. {seconds}초 후 다시 시도하세요." |
| `auth.csrf` | "보안 토큰이 만료되었습니다. 새로고침 후 다시 시도하세요." |

**Contract test 의무** (`tests/contract/test_auth_routes.py`):
- `test_post_login_success_sets_session_cookie`
- `test_post_login_invalid_credentials_shows_kr_message`
- `test_post_login_locks_after_5_failures`
- `test_post_login_locked_returns_403_with_remaining_seconds`
- `test_post_login_missing_csrf_returns_400`

---

### POST /jobs

**요청** (form-urlencoded):
```
department_alias=<str>&professor_name=<str>&course_name=<str>
&period_start=<YYYY-MM-DD>&period_end=<YYYY-MM-DD>&csrf_token=<str>
```

**검증**(spec FR-007):
| 검증 | 실패 시 한국어 메시지 |
|------|---------------------|
| `department_alias` ∈ 등록된 학과 alias 집합 | "선택한 학과를 찾을 수 없습니다." |
| `professor_name` strip 후 1–32자, 공백/특수문자만 거부 | "교수명을 올바르게 입력하세요." |
| `course_name` strip 후 1–64자, 동일 규칙 | "과목명을 올바르게 입력하세요." |
| `period_start ≤ period_end` | "시작일은 종료일 이전이어야 합니다." |
| `period_start ≤ today` | "시작일은 미래일 수 없습니다." |
| 동일 학과 in-progress job 없음 | "동일 학과 분석이 이미 진행 중입니다 — 잠시 후 다시 시도하세요." |

**응답**:
- 성공: 302 → `/jobs/{job_id}` (job_id는 `YYYYMMDD-HHMMSS[-N]` per spec Q4)
- 검증 실패: 200 `text/html` 폼 + 오류 메시지
- 학과 락 중복: 409 `text/html` + 오류 메시지

**부작용**:
- SQLite `analysis_jobs` INSERT (status=`pending`)
- 파일 락 획득 시도 → 실패 시 409
- asyncio Task 스폰(`runner.run_job(job_id)`)
- `Department.last_used_at` 갱신

**Contract test 의무**:
- `test_post_jobs_creates_job_and_redirects`
- `test_post_jobs_validation_blank_fields`
- `test_post_jobs_validation_period_end_before_start`
- `test_post_jobs_validation_future_period_start`
- `test_post_jobs_unknown_department_alias`
- `test_post_jobs_rejects_when_same_department_running`
- `test_post_jobs_job_id_matches_yyyymmdd_hhmmss_pattern`

---

### GET /jobs/{job_id}/progress

**응답** (200 `application/json`):
```json
{
  "job_id": "20260428-153022",
  "status": "running",
  "current_stage": "transcripts",
  "stage_label_kr": "자막 수집 중",
  "processed": 12,
  "total": 47,
  "started_at": "2026-04-28T15:30:22+09:00",
  "completed_at": null,
  "error_code": null,
  "error_message_kr": null
}
```

**스테이지 라벨 매핑**(한국어):
| stage | label_kr |
|-------|----------|
| `listing` | "영상 목록 수집 중" |
| `metadata` | "메타데이터 수집 중" |
| `transcripts` | "자막 수집 중" |
| `retention` | "Retention 데이터 수집 중" |
| `analytics` | "Analytics 데이터 수집 중" |
| `reuse_detection` | "재사용 탐지 분석 중" |
| `reporting` | "보고서 생성 중" |
| `done` | "완료" |

**Contract test 의무**:
- `test_progress_running_returns_processed_total`
- `test_progress_completed_returns_done_stage`
- `test_progress_failed_returns_kr_error_message`
- `test_progress_404_for_unknown_job`
- `test_progress_no_internal_paths_in_response`(spec FR-015)

---

### GET /jobs/{job_id}/files/{kind}

**경로 파라미터** `kind`:
- `v1v3-html`, `v1v3-pdf`, `v1v3-excel`, `reuse-html`, `reuse-excel`

**응답**:
- 200 `application/pdf|text/html|application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` + `Content-Disposition: attachment; filename="{slug}_{kind}.{ext}"`
  - `slug` = `{display_name}_{professor_name}_{course_name}_{period_start}_{period_end}` (한국어 그대로, RFC 5987 인코딩)
  - HTML은 `inline`, PDF/Excel은 `attachment`
- 404 + 한국어: "파일을 찾을 수 없습니다 — 재실행이 필요합니다." + `Retry-After`-like 안내

**보안**:
- `kind` 화이트리스트 외 거부.
- 절대 경로 traversal 방지 — `result_dir`(절대 경로) prefix 강제 검증, `..` 거부.

**Contract test 의무**:
- `test_files_v1v3_html_inline_disposition`
- `test_files_pdf_attachment_with_korean_filename`
- `test_files_unknown_kind_returns_404`
- `test_files_missing_disk_returns_kr_message`
- `test_files_traversal_rejected`

---

### POST /jobs/{job_id}/retry

**요청** (form):
```
csrf_token=<str>
```

**동작**:
- 원본 job의 `status` ∈ {`failed`, `interrupted`}만 허용 (그 외 409 "재실행할 수 없는 상태입니다.")
- 새 `job_id` 발급, `analysis_jobs` INSERT(`status=pending`)
- `runner.run_job(new_job_id, resume_from=original_job_id)` 호출 — checkpoint 재개(spec FR-022a)
- 응답: 302 → `/jobs/{new_job_id}`

**Contract test 의무**:
- `test_retry_failed_job_creates_new_job_id`
- `test_retry_completed_job_rejected_409`
- `test_retry_resumes_from_checkpoint`(integration overlap)

---

### GET /history

**Query params**:
- `status` (optional, comma-separated)
- `department` (optional)
- `limit` (default 50, max 200)
- `offset` (default 0)

**응답** (200 `text/html`): 이력 테이블 + 페이지네이션. 각 행 클릭 시 `/jobs/{job_id}` 라우팅(spec FR-022).

**Contract test 의무**:
- `test_history_lists_jobs_newest_first`
- `test_history_filters_by_status`
- `test_history_filters_by_department`
- `test_history_pagination_limit_offset`
- `test_history_links_each_row_to_job_view`

---

### POST /jobs/{job_id}/reviews/{pair_id}

**요청** (form):
```
status=<confirmed_duplicate|false_positive|unreviewed>&note=<str>&csrf_token=<str>
```

**동작**:
- `pair_id` 존재 검증(spec 007 출력의 키와 일치).
- `reuse_review_status` UPSERT.
- `note`는 0–512자 선택.

**응답**: 302 → 호출자 referer (없으면 `/jobs/{job_id}/results`)

**Contract test 의무**:
- `test_review_marks_pair_as_confirmed_duplicate`
- `test_review_unknown_pair_returns_404`
- `test_review_invalid_status_rejected`
- `test_review_persists_across_next_analysis`(integration with spec 007 fixture)

---

### GET /healthz

**응답**: 200 `text/plain` `ok`. 인증 불필요. 리버스 프록시 헬스체크 용도.

**Contract test**: `test_healthz_returns_ok_without_auth`.

---

## Cross-cutting Contract Requirements

- 모든 라우트의 응답에 **시크릿 정보 포함 금지** — 환경변수명, 토큰 경로, 채널 ID, agenix 키 등 0건. JSON 응답 구조에서도 위 필드 부재가 contract test로 검증된다(spec SC-006).
- 모든 4xx 응답은 한국어 사용자 메시지 + `error_code` 키만 포함하며, 영문 상세는 로그에만(spec FR-015).
- 모든 라우트는 `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` 헤더를 추가한다(미들웨어 일괄).
- 라우트 핸들러는 서비스 계층 함수만 호출하며 직접 google-api/transformer 호출 금지(Constitution IV — thin layer).
