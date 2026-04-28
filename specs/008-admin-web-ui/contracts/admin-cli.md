# Contract: Admin CLI (`tube-scout admin ...`)

**Branch**: `008-admin-web-ui` | **Date**: 2026-04-28
**Sources**: [spec.md](../spec.md) FR-024~027, [research.md](../research.md) §9, Q1·Q3 결정

본 문서는 운영자(DX지원센터장) 전용 CLI 명령 계약을 정의한다. 모든 명령은 기존 `cli/main.py`의 `app` Typer 인스턴스에 `admin` subcommand 그룹으로 등록된다. 운영자 GUI는 본 idea에서 제공하지 않는다(Q1).

## 공통 규약

- **Module**: `src/tube_scout/cli/admin.py`
- **Entry**: `app.add_typer(admin_app, name="admin", help="운영자 전용 명령")`
- **Help text**: 한국어(운영자가 한국 사용자) + 옵션은 영문 식별자.
- **종료 코드**: `0`(성공), `1`(검증 실패/비즈니스 거부), `2`(시스템 오류).
- **출력**: 정상 결과는 stdout(rich Table), 오류는 stderr(rich Markup).
- **로그**: 모든 명령은 `OperatorAction` 테이블에 결과 기록(append-only).

## Commands

### 1. `tube-scout admin add-department`

**Synopsis**:
```bash
tube-scout admin add-department \
  --alias <영문alias> \
  --display "<한국어 표시명>" \
  --channel-id-env <ENV_NAME> \
  --client-secret-env <ENV_NAME> \
  --api-key-env <ENV_NAME>
```

**옵션**:
| 옵션 | 타입 | 필수 | 설명 |
|------|------|:----:|------|
| `--alias` | str | ✅ | `^[a-z][a-z0-9-]{0,31}$` |
| `--display` | str | ✅ | 한국어 표시명, 1–32자 |
| `--channel-id-env` | str | ✅ | `^TUBE_SCOUT_CHANNEL_ID_[A-Z0-9_]+$` |
| `--client-secret-env` | str | ✅ | `^TUBE_SCOUT_CLIENT_SECRET_[A-Z0-9_]+$` |
| `--api-key-env` | str | ✅ | `^TUBE_SCOUT_API_KEY_[A-Z0-9_]+$` |
| `--no-oauth-consent` | flag | ❌ | OAuth 동의 흐름 건너뛰기(이미 토큰 존재) |

**검증**:
- alias 중복(이미 존재) → exit 1, 한국어 메시지.
- 환경변수 3종 중 하나라도 부재 → exit 1, "환경변수 X가 정의되어 있지 않습니다. agenix 시크릿 등록을 먼저 완료하세요."
- 표시명 중복 → exit 1.

**부작용**:
- `~/.config/tube-scout/departments.json`에 atomic write로 신규 항목 추가
- `--no-oauth-consent` 미지정 시 `services/auth.py`의 OAuth 동의 흐름 자동 트리거(브라우저 열림 — 운영자 환경 필요)
- 토큰 저장: `~/.config/tube-scout/tokens/{alias}_token.json`(기존 spec 003 위치 유지)
- `OperatorAction` INSERT(action=`add_department`, result=`success|failure`)

**출력 (성공)**:
```
✓ 학과 등록 완료: physiology (물리치료과)
  channel_id_env: TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY
  토큰 저장 위치: ~/.config/tube-scout/tokens/physiology_token.json
  agenix 시크릿 매핑이 .config/tube-scout/departments.json에 반영되었습니다.
  웹 UI에서는 다음 새로고침 시 드롭다운에 노출됩니다.
```

**Contract test** (`tests/integration/test_admin_cli.py`):
- `test_add_department_writes_departments_json`
- `test_add_department_rejects_duplicate_alias`
- `test_add_department_validates_alias_pattern`
- `test_add_department_fails_when_env_missing`
- `test_add_department_records_operator_action`

---

### 2. `tube-scout admin list`

**Synopsis**:
```bash
tube-scout admin list [--json]
```

**출력 (rich Table 또는 JSON)**:
| alias | display_name | last_used_at | token_status |
|-------|--------------|--------------|--------------|
| physiology | 물리치료과 | 2026-04-27 14:22 KST | valid |
| nursing | 간호학과 | (사용 이력 없음) | needs_refresh |

**Contract test**:
- `test_list_outputs_registered_departments`
- `test_list_json_flag_returns_machine_readable`

---

### 3. `tube-scout admin status`

**Synopsis**:
```bash
tube-scout admin status [--alias <alias>] [--json]
```

**동작**:
- 등록된 모든 학과(또는 특정 alias)의 OAuth 토큰 상태 조회.
- 토큰 만료/만료 임박(7일 이내) 학과를 빨간/노랑 강조.
- 최근 7일간 `OperatorAction` 요약(refresh 횟수, 실패 건수).
- 진행 중 작업 수 표시(SQLite 조회).

**출력 예시**:
```
OAuth 토큰 상태
  ✓ physiology   유효 (만료까지 23일)
  ⚠ nursing      만료 임박 (3일 남음) — `tube-scout admin refresh nursing` 권장
  ✗ anatomy      만료됨 — refresh 필요

진행 중 작업: 1건 (physiology, job_id=20260428-153022)

최근 7일 운영 동작:
  add_department: 1, oauth_consent: 1, token_refresh: 0, status_check: 4
```

**부작용**: `OperatorAction` INSERT(action=`status_check`).

**Contract test**:
- `test_status_flags_expired_tokens_red`
- `test_status_flags_near_expiry_yellow`
- `test_status_shows_running_jobs_count`
- `test_status_alias_filter_returns_single`
- `test_status_json_output_contract`

---

### 4. `tube-scout admin refresh`

**Synopsis**:
```bash
tube-scout admin refresh <alias> [--force]
```

**동작**:
- 지정 학과의 refresh token 흐름 강제 트리거(`services/auth.py`).
- `--force` 미지정 시 만료/임박 토큰만 갱신, 그 외는 skip.
- 갱신 성공/실패를 `OperatorAction`(action=`token_refresh`)에 기록.

**검증**:
- 알 수 없는 alias → exit 1, "등록되지 않은 학과 alias입니다: <alias>".
- refresh token 부재 → exit 1, "재인증이 필요합니다 — `add-department --no-oauth-consent` 후 재시도하세요".

**Contract test**:
- `test_refresh_unknown_alias_rejected`
- `test_refresh_skips_valid_token_without_force`
- `test_refresh_force_renews_anyway`
- `test_refresh_records_failure_on_invalid_grant`

---

### 5. `tube-scout admin verify`

**Synopsis**:
```bash
tube-scout admin verify <alias>
```

**동작**:
- 환경변수 3종(channel_id, client_secret, api_key) 존재 확인.
- 토큰 파일 로드 → access token 유효성 검증.
- YouTube Data API에 채널 메타데이터 1회 호출(`channels.list?id=<ch_id>`).
- 모두 성공 시 exit 0, 한 단계라도 실패 시 stderr에 단계별 결과 + exit 1.

**출력 예시**:
```
verify: physiology (물리치료과)
  [✓] 환경변수 채널 ID
  [✓] 환경변수 클라이언트 시크릿
  [✓] 환경변수 API 키
  [✓] 토큰 파일 존재
  [✓] access token 유효
  [✓] YouTube API 호출 성공 (응답 200, 채널명: ...)
완료. 이 학과는 분석에 사용할 준비가 되었습니다.
```

**Contract test**:
- `test_verify_all_steps_pass_returns_zero`
- `test_verify_missing_env_var_fails_with_kr_message`
- `test_verify_invalid_token_fails_at_step_5`
- `test_verify_api_quota_exceeded_reports_kr_message`

---

## Output Format Standards

- **rich Table** 컬럼명은 한국어 헤더 + 데이터 셀.
- **JSON 출력**(`--json` 플래그)은 ASCII-safe(ensure_ascii=False, 줄바꿈은 LF).
- **시크릿 비노출**: 어떤 명령도 시크릿 자체 또는 토큰 raw bytes를 출력하지 않는다(노출은 환경변수명·만료일·상태 enum까지). Constitution VI.

## Error Code Conventions (CLI exit + 한국어 메시지)

| exit | 의미 | 예시 메시지 |
|:----:|------|------------|
| 0 | 성공 | (없음) |
| 1 | 사용자 입력/비즈니스 거부 | "등록되지 않은 학과 alias입니다: foo" |
| 2 | 시스템 오류 | "departments.json 파일을 쓸 수 없습니다 — 권한을 확인하세요." |

## Backward Compatibility

- 기존 `cli/auth_cli.py`, `cli/status.py`는 그대로 둔다(spec FR-030).
- `admin` subcommand 그룹은 새 진입점이며 기존 진입점과 충돌하지 않는다.
- 기존 토큰 저장 경로(`~/.config/tube-scout/tokens/`)는 변경 없음(spec FR-031, FR-023).
