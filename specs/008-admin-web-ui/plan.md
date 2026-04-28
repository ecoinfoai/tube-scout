# Implementation Plan: 교무과 담당자용 간편 웹 UI (Admin Web UI)

**Branch**: `008-admin-web-ui` | **Date**: 2026-04-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-admin-web-ui/spec.md`

## Summary

부산보건대 교무과 단일 담당자가 사내망 웹 주소에 접속해 단일 계정으로 로그인하고, 학과(드롭다운) · 교수명 · 과목명 · 기간 4개 필드를 입력하면 학과별 본 채널 OAuth 자격으로 v1~v4 풀 파이프라인(영상 목록 → 메타데이터 → 자막(공개·비공개 force-ssl) → retention → analytics → 재사용 탐지(spec 007) → 보고서)이 백그라운드 비동기로 실행되고, 진행률(5초 이내 갱신)과 결과(HTML/PDF/Excel)를 같은 화면에서 확인 · 다운로드한다. 과거 분석 이력 재열람과 재사용 탐지 영상 쌍 리뷰(중복 확정/오탐) 기능을 포함한다. 운영자(DX지원센터장)는 CLI 명령(`tube-scout admin add-department/status/refresh`)으로만 신규 학과 등록 · 토큰 갱신 · 상태 조회를 수행하며, 모든 시크릿은 agenix 중앙 저장소를 통해 환경변수로 주입된다.

기술 접근(Phase 0 결과 요약): 백엔드는 기존 Typer CLI 서비스 계층 위에 Starlette + uvicorn 기반의 ASGI 앱을 얇게 얹는다. 백그라운드 작업은 asyncio Task + 파일 락(같은 학과 동시성 거부)으로 처리하고, 별도 Celery/Redis는 도입하지 않는다(Constitution V — 외부 DB 없음). 인증은 itsdangerous로 서명된 세션 쿠키 + bcrypt 비밀번호 해시. 이력 메타데이터는 SQLite 단일 파일(append-only WAL)로 저장하고, 결과 산출물은 기존 `projects/{job-id}/` 디렉터리를 그대로 사용한다. 프론트엔드는 Jinja2 템플릿 + 최소 vanilla JS(폴링 fetch); 빌드 도구 없이 정적 자원만 제공한다.

## Technical Context

**Language/Version**: Python 3.11 (`pyproject.toml` `requires-python = ">=3.11"`)
**Primary Dependencies**:
- 신규: `starlette` (ASGI), `uvicorn[standard]` (ASGI 서버), `jinja2` (이미 종속), `itsdangerous` (서명 세션), `bcrypt` (비밀번호 해시), `python-multipart` (폼 파싱)
- 기존 재사용: `typer`, `rich`, `pydantic v2`, `polars`, `plotly`, `weasyprint`, `google-api-python-client`, `google-auth-oauthlib`, `youtube-transcript-api`, `transformers`, `torch`, `openpyxl`
- 서비스 계층 함수 호출: `services/youtube_data.py`, `services/youtube_analytics.py`, `services/transcript.py`, `services/video_filter_service.py`, `services/auth.py`, `cli/collect.py` 진입점, spec 007 재사용 탐지 모듈

**Storage**:
- 이력 메타데이터: SQLite `~/.local/share/tube-scout/admin.db` (single file, WAL mode)
- 분석 결과: 기존 `projects/{job-id}/...` 디렉터리 (`{job-id}` = `YYYYMMDD-HHMMSS[-N]`)
- 학과 매핑: `~/.config/tube-scout/departments.json` (운영자 CLI가 갱신, 평문 — 시크릿 아님; alias·표시명·환경변수명만)
- OAuth 토큰: `~/.config/tube-scout/tokens/{alias}_token.json` (기존, 변경 없음)
- 시크릿(클라이언트 시크릿·API 키·로그인 자격 증명): agenix → 환경변수
- 로그: `~/.local/share/tube-scout/logs/admin-web.log` + journald (systemd 단위로 운영)

**Testing**: `pytest` + `pytest-asyncio` (ASGI 비동기 테스트), `httpx.AsyncClient` (route 통합 테스트), `pytest-cov` (커버리지). 외부 API는 응답 픽스처로 모킹; OAuth/agenix는 환경변수 주입 픽스처로 격리.

**Target Platform**: Linux 서버 (NixOS, 사내망 단일 머신), 클라이언트는 데스크톱 브라우저(Chromium/Firefox 최신 1년).

**Project Type**: Web service (얇은 ASGI 레이어) + 기존 CLI 도구 — 단일 패키지(`tube_scout`) 내 확장.

**Performance Goals**:
- 진행률 갱신 요청(GET /jobs/{id}/progress) p95 < 200 ms
- 폼 제출 → 작업 큐 등록(POST /jobs) p95 < 500 ms
- 분석 자체 소요는 영상 수와 OAuth/GPU 환경에 의존 — 본 idea의 SLO 대상 아님(SC-010 95% 성공률만 검증)

**Constraints**:
- 동시 활성 사용자 ≤ 1, 동시 실행 작업 ≤ 5(서로 다른 학과)
- 외부 DB 서버 금지(Constitution V)
- 모든 시크릿 agenix 경유(Constitution VI)
- HTTPS 필수(spec FR-004b — 리버스 프록시 종단 또는 직접 TLS)
- CLI 동작 변경 금지(spec FR-030 / Constitution IV)

**Scale/Scope**:
- 학과 수: 10–20개 추정(부산보건대 기준)
- 1회 분석당 영상 수: 50–500개(학과·과목·기간에 따라)
- 이력 누적: 연간 500–2000건 추정 → SQLite 단일 파일에 충분
- 동시 사용자 1명, 다중 사용자는 범위 외(Out of Scope)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

원칙 I–VI(`.specify/memory/constitution.md` v1.0.0) 게이트 평가:

| # | Principle | Pre-research | Post-design | Notes |
|---|-----------|:---:|:---:|-------|
| I | Test-First (NON-NEGOTIABLE) | ✅ | ✅ | 모든 신규 라우트·서비스에 대해 `tests/contract/`(route 계약), `tests/integration/`(작업 흐름), `tests/unit/`(보조 함수) 3계층 테스트가 RED→GREEN→REFACTOR로 진행되도록 tasks.md에서 강제. spec 007 의존 부분은 fixture로 격리. |
| II | Fail-Fast & Anti-Hallucination | ✅ | ✅ | Pydantic v2 모델로 폼·요청 페이로드 입구 검증, agenix 환경변수 미주입 시 부팅 단계 즉시 실패. 모든 외부 API는 기존 검증된 서비스 계층 호출만 — 새 API 호출 없음. `# [VERIFY]` 마커 미사용(신규 외부 API 0건). |
| III | Type Safety & Single Responsibility | ✅ | ✅ | 모든 신규 함수에 Python 3.11 타입 힌트 + Google 영문 docstring. 라우트(routing) / 세션(auth) / 작업 큐(jobs) / 이력 저장(repo) / 보고서 응답(report-routes) 모듈 분리. |
| IV | CLI-First Architecture | ✅ | ✅ | 신규 분석 로직 0건 — 모두 기존 CLI 서비스(`collect all`/`analyze all`/`report bundle`/spec 007) 함수 호출로 위임. 운영자 인터페이스는 CLI 명령(`tube-scout admin ...`)으로 추가. 웹 UI는 thin layer 원칙 준수. |
| V | Local-First, External-DB-Free Persistence | ✅ | ✅ | 이력 = SQLite 단일 파일, 결과 = `projects/{job-id}/` 디렉터리, 매핑 = `departments.json`. PostgreSQL/MongoDB/Redis 미사용. Celery 등 외부 브로커 미도입(asyncio + 파일 락). |
| VI | Secrets via agenix Only (NON-NEGOTIABLE) | ✅ | ✅ | 모든 시크릿(OAuth 클라이언트 시크릿, refresh token, API 키, 로그인 자격 증명, 세션 서명 키, bcrypt 페퍼)을 환경변수로 주입. 코드·yaml·JSON 파일에 평문 시크릿 0건. `departments.json`에는 alias·표시명·환경변수명만(시크릿 아님). |

**Spec-Driven Workflow** (Governance §): 본 plan.md → tasks.md → 구현 순으로 진행. 브랜치 `008-admin-web-ui`, Conventional Commits 적용.

**Constitution Check 결과**: ✅ 모든 게이트 통과, Complexity Tracking 필요 없음.

## Project Structure

### Documentation (this feature)

```text
specs/008-admin-web-ui/
├── plan.md              # This file (/speckit.plan output)
├── spec.md              # /speckit.specify + /speckit.clarify output
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (HTTP routes + admin CLI)
│   ├── http-routes.md
│   └── admin-cli.md
├── checklists/
│   └── requirements.md  # /speckit.specify 검증 체크리스트
└── tasks.md             # /speckit.tasks 출력 (이 명령에서는 생성 안 함)
```

### Source Code (repository root)

기존 단일 패키지(`src/tube_scout/`) 내에 `web/` 서브패키지를 추가한다. 분리된 backend/frontend 트리는 만들지 않는다(Constitution IV — thin layer).

```text
src/tube_scout/
├── cli/                  # 기존
│   ├── main.py
│   ├── collect.py
│   ├── analyze.py
│   ├── report.py
│   ├── auth_cli.py
│   ├── status.py
│   └── admin.py          # 신규: tube-scout admin {add-department,status,refresh}
├── services/             # 기존 — 변경 없음 (CLI/web 공유)
├── storage/              # 기존
├── reporting/            # 기존
├── models/               # 기존
├── visualization/        # 기존
└── web/                  # 신규
    ├── __init__.py
    ├── app.py            # Starlette 앱 팩토리, lifespan(secrets 검증)
    ├── routes/
    │   ├── auth.py       # GET/POST /login, POST /logout
    │   ├── jobs.py       # POST /jobs, GET /jobs/{id}, GET /jobs/{id}/progress
    │   ├── history.py    # GET /history (목록 + 필터)
    │   ├── results.py    # GET /jobs/{id}/results, GET /jobs/{id}/files/{kind}
    │   └── reviews.py    # POST /jobs/{id}/reviews/{pair_id} (재사용 탐지)
    ├── middleware/
    │   ├── session.py    # itsdangerous 서명 세션, 8h 만료
    │   ├── auth_required.py
    │   └── rate_limit.py # 로그인 5회/5분 잠금
    ├── jobs/
    │   ├── runner.py     # asyncio Task + per-department lock
    │   ├── progress.py   # 단계·카운트 in-memory + checkpoint hook
    │   └── pipeline.py   # 7단계 순차 실행(기존 서비스 호출)
    ├── repo/
    │   ├── jobs_repo.py  # SQLite jobs/results 테이블
    │   ├── reviews_repo.py # 영상 쌍 리뷰 상태(spec 007 통합)
    │   └── departments_repo.py # departments.json 읽기
    ├── templates/        # Jinja2
    │   ├── base.html
    │   ├── login.html
    │   ├── form.html
    │   ├── progress.html
    │   ├── result.html
    │   ├── history.html
    │   └── error.html
    ├── static/           # css, js (vanilla — 빌드 도구 없음)
    └── errors.py         # 한국어 사용자 메시지 + 영문 로그 매핑

tests/
├── contract/             # HTTP 라우트 계약 (httpx.AsyncClient)
│   ├── test_auth_routes.py
│   ├── test_jobs_routes.py
│   ├── test_history_routes.py
│   ├── test_results_routes.py
│   └── test_reviews_routes.py
├── integration/          # 풀 작업 흐름 (서비스 모킹)
│   ├── test_login_flow.py
│   ├── test_job_lifecycle.py
│   ├── test_concurrent_departments.py
│   ├── test_checkpoint_resume.py
│   └── test_admin_cli.py
└── unit/                 # 보조 함수
    ├── test_session.py
    ├── test_rate_limit.py
    ├── test_progress_serializer.py
    ├── test_jobs_repo.py
    └── test_departments_repo.py
```

**Structure Decision**: 단일 패키지(`src/tube_scout/`) 내에 `web/` 서브패키지를 신설한다. 이유:

1. **Constitution IV(CLI-First)** — 웹은 thin layer이므로 별도 트리는 과잉. 기존 services/storage/reporting을 직접 import.
2. **Constitution III(Single Responsibility)** — `web/`는 라우팅·세션·작업 러너에만 책임. 분석 로직은 services/에 머묾.
3. **Test 분류** — `tests/contract|integration|unit/` 표준 트리 그대로 사용.
4. **Frontend** — Jinja2 + 정적 자원만이라 별도 frontend/ 트리 불필요(빌드 도구 없음).

## Complexity Tracking

> Constitution Check 모든 게이트 통과 — 본 섹션은 비워둔다.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| (해당 없음) | (해당 없음) | (해당 없음) |
