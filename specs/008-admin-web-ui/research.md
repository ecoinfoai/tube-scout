# Phase 0 Research: 008-admin-web-ui

**Branch**: `008-admin-web-ui` | **Date**: 2026-04-28
**Input**: [spec.md](./spec.md), [plan.md](./plan.md), [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md)

본 문서는 `/speckit.plan` Phase 0 단계의 연구 결과를 기록한다. 모든 NEEDS CLARIFICATION이 해결되었으며 Phase 1(데이터 모델·계약·퀵스타트) 진입 가능 상태다.

## 1. ASGI 웹 프레임워크 선택

### Decision: Starlette (uvicorn 서버)

### Rationale
- **Constitution IV(CLI-First, thin layer)** 원칙에 가장 부합 — 라우팅·세션·정적 파일·템플릿만 필요하며, ORM·자동 OpenAPI·DI 컨테이너 같은 풀스택 기능은 오히려 부담이다.
- **표준 ASGI** — `pytest` + `httpx.AsyncClient`로 라우트 테스트가 즉시 가능, Constitution I(Test-First) 흐름과 자연스럽게 결합.
- **Jinja2** 템플릿이 기본 통합되어 있어 추가 의존성 없이 서버 사이드 렌더링 가능.
- **소스 크기** ≈ 6 MB(Starlette+uvicorn+itsdangerous+python-multipart 합산), Constitution V/VI 준수에 유리.

### Alternatives considered
- **FastAPI** — Pydantic 자동 검증·OpenAPI는 매력적이나 Starlette 위 wrapper로 동일 기능을 직접 구현 가능하고, 자동 OpenAPI는 본 idea의 단일 사용자 사내망 환경에서 가치가 낮다. 의존 트리가 더 크다.
- **Flask + flask-asgi** — 동기 기반이라 백그라운드 asyncio Task와 패러다임 충돌, 실시간 진행률 폴링 응답 시 워커 점유 우려.
- **Django** — ORM·Admin·인증 풀스택은 명백한 과잉(Constitution V — 외부 DB 가정). 본 idea의 "얇은 레이어" 원칙 위배.
- **htmx 풀 SPA(JS 프레임워크)** — vanilla JS + 폴링이면 충분한 UX 요구, 빌드 도구 도입은 Constitution IV·V와 충돌.

## 2. 백그라운드 작업 실행 모델

### Decision: asyncio Task + per-department 파일 락 + checkpoint 재개

### Rationale
- **Constitution V(External-DB-Free)** — Celery/RQ는 Redis/RabbitMQ 등 외부 브로커가 필수라 명백히 위배.
- **단일 사용자, 동시 작업 ≤ 5** — 부하가 작아 단일 프로세스 asyncio loop로 충분.
- **per-department 파일 락**(`fcntl.flock(LOCK_EX | LOCK_NB)` on `~/.local/share/tube-scout/locks/{alias}.lock`) — spec FR-028(동일 학과 거부) 구현에 자연스럽게 부합. 프로세스 비정상 종료 시 OS가 자동 해제.
- **checkpoint 재개** — spec 007 FR-004의 per-video processing status를 활용. 실패/중단 작업 [재실행] 시 마지막 성공 단계 다음부터 이어 실행(spec FR-022a, Q5 결정).
- **GPU 사용 단계(재사용 탐지)** — `asyncio.to_thread()`로 CPU/GPU 바운드 코드를 스레드 풀에 디스패치하여 이벤트 루프 점유를 막는다.

### Alternatives considered
- **Celery + Redis** — Constitution V 위배.
- **APScheduler** — 정기 스케줄러가 본 idea의 unscheduled, on-demand 작업 패턴과 맞지 않음.
- **multiprocessing.Process** — 작업 상태(progress) 공유에 IPC 오버헤드, asyncio Task 대비 이득 없음.
- **systemd unit per job** — 운영 복잡도 높음, 단일 프로세스 asyncio가 더 단순.

## 3. 인증·세션 관리

### Decision: bcrypt 해시 + itsdangerous 서명 쿠키 세션 + 인메모리 로그인 시도 추적

### Rationale
- **Q2 결정(표준 보호)** — 8시간 세션, HTTPS 필수, 5회/5분 잠금.
- **bcrypt** — Python 생태계 표준, 메모리 하드 비밀번호 해시. agenix가 주입한 평문 비밀번호를 부팅 시 1회 해시하여 메모리에 보관(또는 사전 해시된 형태로 환경변수 주입 — 운영자 선호에 맡김).
- **itsdangerous** — Starlette의 `SessionMiddleware`가 itsdangerous 서명을 사용. 서버 측 세션 저장소 없이 서명·만료 시간을 쿠키 자체에 포함, Constitution V(외부 DB 없음)와 정합.
- **세션 서명 키** — `TUBE_SCOUT_SESSION_SECRET` 환경변수(agenix 주입).
- **로그인 시도 추적** — 사용자 1명·아이디 1개라 인메모리 dict(`{username: (fail_count, locked_until)}`) + 프로세스 재시작 시 reset 허용. 외부 DB 없이도 충분.
- **쿠키 속성** — `Secure`, `HttpOnly`, `SameSite=Lax`(spec FR-004d).

### Alternatives considered
- **JWT** — stateful 단일 사용자에 과잉. 만료/회수 정책 단순화 면에서 itsdangerous 서명 세션이 유리.
- **서버 측 세션(SQLite/Redis)** — 외부 저장소 없이 쿠키 자체로 충분. Constitution V·운영 단순화.
- **passlib** — bcrypt 단독 호출이 더 가볍다. passlib은 다중 알고리즘 마이그레이션이 필요할 때 유용한데 본 idea엔 불필요.
- **argon2** — 더 현대적이지만 의존성 추가. 본 idea의 위협 모델(사내망·1명·평문 시크릿 없음)에서 bcrypt(cost=12)로 충분.

## 4. 이력·작업 메타데이터 영속화

### Decision: SQLite 단일 파일(WAL 모드) at `~/.local/share/tube-scout/admin.db`

### Rationale
- **Constitution V** — SQLite는 명시적으로 허용된 로컬 파일 기반 저장소.
- **JSON Lines 단일 파일 vs SQLite** — 이력 누적 ~2,000건/년 + 필터·정렬 쿼리(최신순, 학과별, 상태별)가 필요하므로 SQL이 자연스럽다. 매번 전체 JSON 로드는 비효율.
- **WAL 모드** — 백그라운드 작업이 INSERT/UPDATE 하는 동안 라우트가 SELECT 가능, 동시성 문제 회피.
- **마이그레이션** — 단일 사용자 환경에 alembic은 과잉. 부팅 시 `CREATE TABLE IF NOT EXISTS` + 버전 테이블로 충분.
- **드라이버** — Python 내장 `sqlite3` 모듈. 추가 ORM(SQLAlchemy/SQLModel)은 본 idea에 과잉.

### Alternatives considered
- **JSON Lines** — 필터·정렬·페이징 시 비효율.
- **TinyDB** — 의존성 추가 + 인덱스 부재로 SQLite 대비 이점 없음.
- **Polars 직접 사용** — 분석용 라이브러리이지 트랜잭션 저장소가 아님. 부적합.

## 5. 학과 매핑 저장 형식

### Decision: `~/.config/tube-scout/departments.json` (운영자 CLI가 갱신)

### Rationale
- 학과 alias·표시명·환경변수명만 저장 — **시크릿 아님**, 평문 JSON 무방.
- Constitution VI 위배 없음(시크릿은 환경변수 참조).
- 운영자 CLI(`tube-scout admin add-department`)가 atomic write로 갱신 → 웹 앱은 재시작 없이 다음 요청에서 새 목록을 로드(spec FR-025).
- mtime 기반 캐시 무효화로 부담 없음.

### Schema (research-only, 실제 정의는 data-model.md)
```json
{
  "version": 1,
  "departments": [
    {
      "alias": "physiology",
      "display_name": "물리치료과",
      "channel_id_env": "TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY",
      "client_secret_env": "TUBE_SCOUT_CLIENT_SECRET_PHYSIOLOGY",
      "api_key_env": "TUBE_SCOUT_API_KEY_PHYSIOLOGY",
      "registered_at": "2026-04-28T15:30:00+09:00"
    }
  ]
}
```

### Alternatives considered
- **YAML** — JSON이 atomic write·검증·Pydantic 결합 면에서 더 단순. YAML 파서 추가 의존성 불필요.
- **SQLite 테이블** — 학과 수 10–20개에 SQL은 과잉. JSON 파일이 운영자 수동 수정에도 친화적.

## 6. 진행률 표시 메커니즘

### Decision: 클라이언트 폴링(GET /jobs/{id}/progress, 3초 간격) + 인메모리 + checkpoint 동기화

### Rationale
- 단일 사용자 환경에서 **WebSocket/SSE**의 이점이 작다(연결 1개). 폴링이 운영·디버깅·테스트 모두 단순.
- 진행 상태는 워커 프로세스의 in-memory dict + 단계 전환 시 checkpoint(spec 007 FR-004)에 stage 이름 sync. 서버 재시작 시 checkpoint에서 복원.
- 3초 간격 폴링은 spec FR-013(5초 이내 갱신) + 사용자 체감 응답성을 모두 충족.
- 응답 페이로드는 `{job_id, status, stage, processed, total, started_at, error?}` JSON.

### Alternatives considered
- **Server-Sent Events(SSE)** — 양방향 불필요·폴링 대비 운영 복잡도 가중. 대안으로 보존하되 현 설계에서는 미채택.
- **WebSocket** — 양방향 통신 필요 없음. 과잉 설계.
- **Long polling** — 폴링과 효과 동일하지만 워커 점유. 짧은 폴링이 단순.

## 7. 보고서 다운로드 응답

### Decision: `FileResponse` + 학과·교수·과목 기반 파일명 슬러그

### Rationale
- Starlette `FileResponse`는 streaming + Content-Disposition 헤더를 자동 처리.
- 파일명 슬러그(예: `물리치료과_홍길동_생리학_2024-2025_report.pdf`)로 사용자가 받은 파일을 식별 가능.
- HTML 보고서는 새 탭에서 열기, PDF/Excel은 다운로드 — `Content-Disposition: inline` vs `attachment`로 분기.
- 보안: 절대 경로 traversal 방지 — `projects/{job-id}/...` prefix 강제 검증.

### Alternatives considered
- **Zip 번들 다운로드** — 기존 spec 006의 PDF 번들과 충돌 우려. 개별 다운로드가 명확.
- **사전 생성된 다운로드 링크 토큰** — 단일 사용자 인증 후 직접 접근으로 충분.

## 8. 한국어 오류 메시지 매핑

### Decision: `web/errors.py` 단일 모듈 — 내부 예외 코드 → 한국어 사용자 메시지 매핑 테이블

### Rationale
- spec FR-010·FR-015는 모든 사용자 메시지를 한국어로, 내부 식별자(env var, 경로, 스택)를 비노출하라고 요구.
- Constitution II — 내부 로그·예외는 영문 유지. 사용자 메시지만 매핑.
- 단일 모듈에 dict로 정리하여 테스트(`tests/unit/test_error_mapping.py`)에서 누락 검증.
- 알려지지 않은 예외는 "내부 오류 — 운영자에게 문의하세요" 기본값 + 영문 상세는 로그에만.

### Alternatives considered
- **i18n 풀스택 도구(gettext, babel)** — 한국어 전용 + 메시지 ~30개 수준. 과잉.
- **예외 클래스 자체에 한국어 속성** — 내부 코드와 사용자 메시지가 한 위치에 섞여 Constitution III 위배 가능.

## 9. CLI Admin 명령 (`tube-scout admin ...`)

### Decision: 신규 `cli/admin.py` Typer subcommand 그룹 — `add-department`, `list`, `status`, `refresh`, `verify`

### Rationale
- Q1 결정(운영자=CLI). 기존 `cli/main.py`에 `admin` 그룹으로 등록.
- 명령 5종:
  - `add-department --alias <영문> --display <한국어> --secret-env <환경변수명>` — `departments.json` 추가 + agenix 등록 안내 메시지 출력
  - `list` — 등록된 학과 목록 + 마지막 사용 시각
  - `status` — OAuth 토큰 만료 임박/만료 학과 목록(Q3 결정 — 만료 알림 채널)
  - `refresh <alias>` — refresh token 흐름 강제 트리거
  - `verify <alias>` — 환경변수 + 토큰 + API 호출 1회로 셋업 검증
- 모든 명령은 기존 `services/auth.py` 함수를 재사용 — 중복 구현 없음(Constitution IV).

### Alternatives considered
- **별도 운영자 GUI** — Q1에서 거부됨.
- **명령 한 개에 subcommand 없이 플래그로 분기** — 가독성·확장성 모두 열위.

## 10. NixOS 통합 / 시크릿 주입 / systemd

### Decision: `flake.nix` devShell + 운영용 systemd unit + agenix module

### Rationale
- Constitution Technology Stack — NixOS devShell이 표준. `flake.nix`에 agenix module을 추가하고, devShell 진입 시 환경변수가 자동 export.
- 운영 환경에서는 systemd `tube-scout-admin-web.service` unit으로 uvicorn 실행. `EnvironmentFile=/run/agenix/tube-scout-secrets`로 시크릿 주입.
- HTTPS 종단은 nginx/Caddy 리버스 프록시 사용 권장(self-signed 사내 CA 가능). 본 idea는 ASGI 앱만 책임.

### Alternatives considered
- **Docker 컨테이너** — 단일 머신·NixOS 환경에 추가 추상화 부담. 향후 외부 노출 시 검토.
- **uvicorn TLS 직접 종단** — Let's Encrypt 갱신 등 운영 부담을 ASGI 앱이 떠안게 됨. 리버스 프록시가 더 단순.

## NEEDS CLARIFICATION 해결 상태

| Source | Item | Status |
|--------|------|:------:|
| spec.md (Q1) | 운영자 인터페이스 | ✅ Resolved (CLI 명령) |
| spec.md (Q2) | 세션·로그인 보호 | ✅ Resolved (8h 세션 + 5회 잠금 + HTTPS) |
| spec.md (Q3) | 토큰 만료 알림 | ✅ Resolved (CLI status + 구조화 로그) |
| spec.md (Q4) | Job ID 형식 | ✅ Resolved (`YYYYMMDD-HHMMSS[-N]`) |
| spec.md (Q5) | 부분 결과 노출 | ✅ Resolved (비노출 + checkpoint 재개) |
| plan.md | 웹 프레임워크 | ✅ Resolved (§1 Starlette) |
| plan.md | 백그라운드 작업 모델 | ✅ Resolved (§2 asyncio + 파일 락) |
| plan.md | 인증·세션 라이브러리 | ✅ Resolved (§3 bcrypt + itsdangerous) |
| plan.md | 이력 저장 형식 | ✅ Resolved (§4 SQLite WAL) |
| plan.md | 학과 매핑 저장 | ✅ Resolved (§5 departments.json) |
| plan.md | 진행률 메커니즘 | ✅ Resolved (§6 polling 3s) |

모든 항목 해결 — Phase 1(데이터 모델·계약·퀵스타트) 진입 가능.
