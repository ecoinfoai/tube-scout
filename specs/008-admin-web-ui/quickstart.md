# Quickstart: 008-admin-web-ui

**Branch**: `008-admin-web-ui` | **Date**: 2026-04-28
**Audience**: 운영자(DX지원센터장) — 1회 셋업 + 사용자 검증 시나리오

본 문서는 학과 신규 등록 → 웹 UI 부팅 → 사용자 분석 실행 → 결과 다운로드까지의 통합 스모크 테스트 절차를 기술한다. 모든 명령은 NixOS devShell(`nix develop`) 안에서 실행한다.

## 사전 준비 (1회)

### 1. agenix 시크릿 등록 (학과별)

학과 1개당 환경변수 3종 + 1개 공유 환경변수 2종이 필요하다.

```nix
# secrets.nix (agenix 중앙 저장소)
{
  "tube-scout-physiology.age".publicKeys = [ keys.serverHost keys.operator ];
  "tube-scout-nursing.age".publicKeys = [ keys.serverHost keys.operator ];
  "tube-scout-shared.age".publicKeys = [ keys.serverHost keys.operator ];
}
```

각 `*.age` 파일은 다음 형식의 환경변수 export 스크립트를 암호화한다:

```bash
# tube-scout-physiology
export TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY="UCxxxxxxxxxxxxxxxx"
export TUBE_SCOUT_CLIENT_SECRET_PHYSIOLOGY='{"web":{"client_id":"...","client_secret":"...","redirect_uris":["http://localhost:8000/oauth/callback"]}}'
export TUBE_SCOUT_API_KEY_PHYSIOLOGY="AIzaSy..."

# tube-scout-shared
export TUBE_SCOUT_ADMIN_USERNAME="moogwa"
export TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT="$2b$12$..."  # 사전 해시
export TUBE_SCOUT_SESSION_SECRET="$(openssl rand -hex 32)"
```

agenix module을 NixOS 또는 home-manager에 등록 후 시스템 reactivate.

### 2. devShell 진입 + 시크릿 검증

```bash
cd /home/kjeong/localgit/tube-scout
nix develop
echo $TUBE_SCOUT_ADMIN_USERNAME           # → moogwa
echo $TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY    # → UCxxxx... (있으면 성공)
```

환경변수가 보이지 않으면 agenix `system.activationScripts.agenix.text`가 디렉터리/권한을 생성했는지 확인.

### 3. 학과 등록

```bash
tube-scout admin add-department \
  --alias physiology \
  --display "물리치료과" \
  --channel-id-env TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY \
  --client-secret-env TUBE_SCOUT_CLIENT_SECRET_PHYSIOLOGY \
  --api-key-env TUBE_SCOUT_API_KEY_PHYSIOLOGY
```

브라우저가 열리며 OAuth 동의 화면이 표시된다. 학과 본 채널 소유 계정으로 로그인 → 동의 → 콘솔로 돌아오면 토큰이 저장된다.

```bash
tube-scout admin verify physiology
# [✓] 6단계 모두 성공 메시지 확인
```

### 4. 웹 UI 기동

```bash
# 개발 모드
uvicorn tube_scout.web.app:create_app --host 127.0.0.1 --port 8000 --reload

# 운영 모드 (systemd)
sudo systemctl start tube-scout-admin-web.service
journalctl -u tube-scout-admin-web -f  # 로그 실시간 확인
```

리버스 프록시(nginx/Caddy)가 HTTPS 종단을 처리하도록 구성한다(예: `https://tube-scout.bhug.local/`).

## 사용자 검증 시나리오

### Scenario A: 정상 분석 흐름 (User Story 1)

1. 브라우저로 `https://tube-scout.bhug.local/` 접속 → 로그인 화면 자동 이동
2. 아이디 `moogwa` + 비밀번호 입력 → `/jobs/new`로 리다이렉트
3. 폼 입력:
   - 학과: `물리치료과` (드롭다운)
   - 교수명: `홍길동`
   - 과목명: `생리학`
   - 기간: `2024-03-01` ~ `2025-02-28`
   - [분석 시작]
4. 진행률 화면(`/jobs/{job_id}`)으로 이동 → 7단계 라벨 + 처리 카운트 갱신 관찰(3–5초 간격)
5. 완료 시 결과 화면 자동 표시 → HTML/PDF/Excel 5개 다운로드 링크 노출
6. PDF 클릭 → `물리치료과_홍길동_생리학_2024-03-01_2025-02-28_v1v3.pdf` 다운로드
7. 재사용 탐지 보고서에서 의심 영상 쌍에 [중복 확정] 클릭 → 상태 저장 확인

**기대 시간**: 영상 50개 학과 기준 5–15분 (영상 수에 비례).

### Scenario B: 동시 학과 거부 (FR-028)

1. Scenario A 진행 중인 상태에서, 같은 학과로 다시 [분석 시작] 클릭
2. 폼 다시 제출 → "동일 학과 분석이 이미 진행 중입니다 — 잠시 후 다시 시도하세요." 한국어 안내 (409)
3. 다른 학과(`간호학과`)로는 동일 시점에 시작 가능 — 동시 5건까지 허용

### Scenario C: 토큰 만료 (FR-026)

1. 운영자가 임의로 `tokens/physiology_token.json`의 `expiry`를 과거로 수정(테스트 환경)
2. 사용자가 `물리치료과`로 분석 시작 → 진행률 화면이 즉시 실패 상태로 전환
3. 사용자 화면: "OAuth 토큰 갱신이 필요합니다 — 운영자에게 문의하세요." (env 변수명·경로 비노출)
4. 운영자 셸:
   ```bash
   tube-scout admin status
   # ✗ physiology 만료됨 — refresh 필요
   tube-scout admin refresh physiology
   # ✓ 토큰 갱신 완료
   ```
5. 사용자가 [재실행] 클릭 → 새 job_id 발급, checkpoint 재개로 빠른 회복

### Scenario D: 이력 재열람 (User Story 2)

1. 사용자가 `/history` 진입
2. 최신순 이력 목록 확인 → 학과·교수명·과목명·기간·상태 컬럼 보임
3. 상태 필터 드롭다운에서 `완료` 선택 → 완료 작업만 표시
4. 임의 행 클릭 → `/jobs/{job_id}/results`로 이동, PDF 다시 다운로드 가능

### Scenario E: 보호 동작 (FR-004a~d)

1. 잘못된 비밀번호로 5회 연속 시도 → 6번째 시도 시 403 + "5분 후 다시 시도" 안내
2. `https://...` 대신 `http://...`로 접속 → 308 → HTTPS로 리다이렉트
3. 8시간 미활동 후 페이지 접근 → 로그인 화면 강제 이동(세션 만료)
4. DevTools에서 세션 쿠키 확인 → `Secure`, `HttpOnly`, `SameSite=Lax` 모두 설정됨

## 자동화된 검증

```bash
# 1. 단위 테스트
pytest tests/unit/ -v

# 2. 계약 테스트(라우트)
pytest tests/contract/ -v

# 3. 통합 테스트(작업 흐름)
pytest tests/integration/ -v

# 4. 커버리지
pytest --cov=tube_scout.web --cov-report=term-missing

# 5. 린트
ruff check src/tube_scout/web/ tests/
ruff format --check src/tube_scout/web/ tests/
```

## 트러블슈팅

| 증상 | 원인 후보 | 해결 |
|------|----------|------|
| 로그인 화면이 한국어가 깨짐 | UTF-8 인코딩 누락 | nginx `charset utf-8;` 또는 ASGI middleware 헤더 |
| OAuth 동의 후 토큰 미저장 | 리다이렉트 URI 불일치 | Google Cloud Console에서 redirect URI 등록 |
| `tube-scout admin status`가 0건 표시 | `departments.json` 권한 또는 위치 | `~/.config/tube-scout/departments.json` 0600 + 존재 확인 |
| 진행률이 멈춤 | spec 007 GPU 추론 단계 | `nvidia-smi`로 GPU 점유 확인, fallback CPU 모드 활성 |
| 분석 결과 디스크에 없음 | `result_dir` 권한 | `projects/` 디렉터리 0755 + 운영 사용자 소유 확인 |
| 사용자 화면에 영문 스택 트레이스 노출 | `web/errors.py` 매핑 누락 | 신규 예외 추가 시 매핑 dict + unit test 보강 |

## 다음 단계

- 본 quickstart 통과 후 `/speckit.tasks`로 진입 → TDD 순서로 tasks.md 생성
- 구현은 `code-team` 또는 `dev-squad` 멀티에이전트 워크플로우로 진행 권장
- 첫 인수 테스트는 Scenario A를 자동화 시나리오로 작성 (헤드리스 브라우저 또는 httpx 시퀀스)
