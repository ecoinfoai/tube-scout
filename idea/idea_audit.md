# Tube Scout v0.1.0 — Global Audit Strategy

## 목적

추가 기능 개발 이전에 현 코드베이스(48 모듈, 11.6k LOC, 1,067 테스트)의
**구조적 건전성, 모듈 간 정합성, 운영 견고성**을 포괄적으로 검증한다.
단위 함수 수준이 아닌, 모듈 집단·파이프라인·프로젝트 관례 수준의 감사이다.

## 현황 요약

| 항목 | 수치 |
|------|------|
| 소스 모듈 (non-init) | 48 |
| 소스 LOC | 11,622 |
| 테스트 파일 | 63 (unit 37 + integration 7 + adversary 16 + conftest 등) |
| 테스트 케이스 | 1,067 |
| 테스트 LOC | 17,981 |
| 패키지 레이어 | cli / models / services / storage / reporting / visualization / output |

## 감사 레이어

### Layer 1: Static Analysis (정적 분석)

**목표**: 컴파일 타임에 잡을 수 있는 모든 결함을 기계적으로 소거한다.

| 검사 | 도구 | 기대 결과 |
|------|------|----------|
| 린트 + 포매팅 | `ruff check .` / `ruff format --check .` | 0 violations |
| 타입 안전성 | `mypy --strict src/` | 0 errors (현재 미적용 추정 → 단계적 도입) |
| 데드코드 탐지 | `vulture src/` | unused 함수/변수/import 0건 |
| 순환 import | 커스텀 스크립트 또는 `pydeps` | 순환 의존 0건 |
| import 정합성 | 실제 `import` 그래프 vs `__init__.py` re-export 비교 | 불일치 0건 |
| 보안 패턴 | `bandit -r src/` | High/Medium 0건 |

**산출물**: `_workspace/audit_layer1_static.md` — 위반 항목 목록 + 수정 계획

---

### Layer 2: Module Contract Audit (모듈 계약 감사)

**목표**: 각 모듈의 public API 계약(입출력 타입, 예외, 부작용)이 명확하고 실제 사용과 일치하는지 검증한다.

#### 2.1 API Surface 맵핑

48개 모듈 각각에 대해:

- public 함수/클래스 목록 추출
- 실제 호출자(caller) 역추적 — `grep` 기반 사용처 분석
- 미사용 public API 탐지
- 내부용(`_` prefix)인데 외부에서 호출되는 API 탐지

#### 2.2 입출력 계약 검증

| 검사 항목 | 방법 |
|----------|------|
| 반환 타입 일관성 | 같은 함수가 `None` / `dict` / `Model`을 혼합 반환하지 않는지 |
| 예외 계약 | `raise`하는 예외 타입이 호출자에서 적절히 처리되는지 |
| Pydantic 모델 직렬화 | `model_dump()` / `model_validate()` 왕복 정합성 |
| Optional 필드 전파 | `None`이 체인 아래로 전파될 때 각 단계가 이를 처리하는지 |

#### 2.3 모듈별 점검 대상

| 패키지 | 모듈 수 | 핵심 계약 |
|--------|---------|----------|
| **models/** | 10 | Pydantic 직렬화/역직렬화 왕복, 필드 기본값, validator |
| **services/** | 14 | API 호출 → 모델 변환, 에러 래핑, rate limit 준수 |
| **storage/** | 3 | atomic write, 체크포인트 복구, 파일 포맷 호환 |
| **reporting/** | 6 | 데이터 모델 → HTML/Excel 변환, 빈 데이터 처리 |
| **cli/** | 10 | typer 옵션 파싱, 서비스 호출, exit code |
| **visualization/** | 1 | plotly figure 생성, 빈 데이터 처리 |
| **output/** | 1 | 디렉터리 생성, 심볼릭 링크 관리 |

**산출물**: `_workspace/audit_layer2_contracts.md` — 모듈별 API 계약 명세 + 불일치 목록

---

### Layer 3: Cross-Module Integration (모듈 간 통합 검증)

**목표**: 현재 통합 테스트(7파일)가 커버하지 않는 **모듈 간 경계 조건**을 검증한다.

#### 3.1 데이터 흐름 경로 (Data Flow Paths)

프로젝트의 핵심 데이터 흐름 5개를 식별하고 각 경로의 모든 모듈 경계를 테스트한다:

```
Path A: collect videos → json_store → youtube_data → models/video → storage
Path B: collect retention → youtube_analytics → models/analytics → parquet_store
Path C: collect transcripts → transcript service → json_store
Path D: analyze → forecaster/sentiment/eqs → models → reporting → HTML/Excel
Path E: collect all → [A+B+C+D] 순차 실행 → checkpoint → resume
```

#### 3.2 경계 조건 테스트 매트릭스

| 시나리오 | Path | 검증 내용 |
|---------|------|----------|
| 빈 채널 (영상 0개) | A→D | 전체 파이프라인이 빈 리포트를 정상 생성하는지 |
| 부분 수집 후 재실행 | A,B,C | 체크포인트에서 정확히 이어지는지, 중복 데이터 없는지 |
| API 에러 중간 발생 | A,B | 수집된 데이터까지는 저장되고, 미수집분만 재시도하는지 |
| 모델 스키마 불일치 | A→D | 이전 버전 JSON을 현재 Pydantic 모델로 로드 시 동작 |
| 대용량 입력 | A | 영상 10,000건 페이지네이션 + 메모리 안정성 |
| Analytics 데이터 부재 | B→D | retention 없이 리포트가 해당 섹션만 생략하는지 |
| 자막 일부 실패 | C→D | 일부 영상 자막 없을 때 리포트 정상 생성 |
| collect all 중단 복구 | E | 3단계에서 중단 → 재실행 시 1,2단계 스킵하는지 |
| 멀티채널 토큰 만료 | A (multi) | 하나의 토큰 만료 시 해당 채널만 실패하는지 |
| 동시 실행 | E | 같은 프로젝트에 두 프로세스 동시 실행 시 파일 충돌 |

#### 3.3 모듈 조합 테스트

단위 테스트에서 각각 통과하지만 **조합하면 실패**할 수 있는 패턴:

| 조합 | 위험 |
|------|------|
| title_parser + validator | 파싱 실패(parse_error=True)인 영상에 대해 validator가 V-005 외 다른 규칙을 잘못 적용하지 않는지 |
| search_service + video_filter_service | YAML 검색 결과를 필터 서비스에 전달할 때 타입 호환성 |
| forecaster + 빈 시계열 | 데이터 포인트 < 3일 때 ARIMA/Prophet이 graceful하게 실패하는지 |
| sentiment(LLM) + rate_limiter | LLM API 호출에 rate limiter가 적용되는지 |
| department_report + excel_export | 한국어 데이터 포함 시 Excel 인코딩/컬럼 폭 정상 |
| bundle_report + video_filter | 필터 결과 0건일 때 PDF 번들이 빈 문서를 생성하는지 |
| auth (OAuth) + youtube_data | 토큰 갱신 중 API 호출이 대기하는지 |

**산출물**: `_workspace/audit_layer3_integration.md` — 신규 통합 테스트 목록 + 발견된 결함

---

### Layer 4: Pipeline End-to-End (파이프라인 종단간)

**목표**: CLI 진입점부터 최종 산출물까지 전체 경로를 mock 환경에서 검증한다.

#### 4.1 E2E 시나리오

| 시나리오 | CLI 명령 | 검증 |
|---------|---------|------|
| 신규 프로젝트 전체 수집 | `init → collect all` | projects/ 디렉터리 구조, 모든 JSON/Parquet 파일 생성 |
| 학과 보고서 생성 | `collect → report department --format xlsx` | Excel 시트 구성, 데이터 정합성 |
| 번들 PDF 생성 | `report bundle --filter-professor 홍길동` | PDF 페이지 수, 표지/목차 존재 |
| 제목 검증 | `validate --channel` | V-001~V-009 탐지 결과 vs 기대값 |
| 파이프라인 복구 | `collect all` (중간 중단 후 재실행) | 체크포인트 기반 resume 정상 동작 |
| 멀티채널 순차 수집 | `collect all --channel A` → `collect all --channel B` | 채널 간 데이터 격리 |

#### 4.2 데이터 정합성 검증

- 수집 단계 산출물의 video_id 집합 = 분석 단계 입력 video_id 집합
- JSON 저장 데이터를 Pydantic 모델로 역직렬화 시 100% 성공
- 리포트에 표시된 수치 = 원본 데이터에서 직접 계산한 수치

**산출물**: `_workspace/audit_layer4_e2e.md` — E2E 테스트 시나리오 + 결과

---

### Layer 5: Consistency & Convention (일관성 감사)

**목표**: 프로젝트 전반의 관례가 일관되게 적용되어 향후 개발의 continuity를 보장한다.

| 검사 항목 | 기준 | 방법 |
|----------|------|------|
| 에러 메시지 언어 | 전부 영어 | `grep -r "raise\|typer.echo\|console.print" src/` |
| 로깅 패턴 | `rich.console` 또는 `logging` 중 하나로 통일 | grep |
| CLI 옵션 네이밍 | kebab-case (`--channel-id` vs `--channel_id`) | typer 옵션 추출 |
| Pydantic 모델 | `model_config` 설정 일관성 (frozen, extra 정책) | 모델 파일 전수 검사 |
| import 스타일 | 절대 import (`from tube_scout.x import y`) | grep |
| 함수 네이밍 | snake_case, 동사 시작 (`get_`, `create_`, `collect_`) | AST 파싱 |
| 타입 힌트 | 모든 public 함수에 파라미터/리턴 타입 | mypy 또는 AST |
| 예외 클래스 | 커스텀 예외 vs 내장 예외 사용 패턴 일관성 | grep |
| 매직 넘버 | 하드코딩된 숫자/문자열 → 상수/설정 분리 여부 | 수동 검사 |
| docstring | Google 스타일, 영어 | AST + 수동 |

**산출물**: `_workspace/audit_layer5_consistency.md` — 불일관 항목 목록 + 통일 규칙 제안

---

### Layer 6: Adversary Testing (적대적 파괴 테스트)

**목표**: 15+ 공격 페르소나가 프로젝트의 모든 공격 표면을 파괴적·체계적으로 공격한다. 기존 adversary 테스트(16파일, 399건)는 주로 단일 모듈 수준이며, 이번 감사에서는 **모듈 간 조합, 파이프라인 관통, 환경 조작** 수준의 공격을 추가한다.

#### 6.1 페르소나 설계 원칙

페르소나는 두 축으로 구성한다:

- **Group A — 실제 사용자 (10명)**: 이 프로젝트를 실제로 사용할 사람들이 무지, 실수, 급함, 오해로 시스템을 잘못 사용하는 시나리오. 시스템은 이들을 **보호**해야 한다.
- **Group B — 환경/시스템 적대 조건 (7가지)**: 사용자 잘못이 아닌, 인프라·네트워크·파일시스템 수준의 장애. 시스템은 이 조건에서 **생존**해야 한다.

---

#### 6.2 Group A — 실제 사용자 페르소나 (10명)

| # | 페르소나 | 누구인가 | 전형적 실수 패턴 |
|---|---------|---------|----------------|
| **A-01** | 신입 교무과 직원 (첫 날) | 전임자 인수인계 없이 tube-scout를 처음 실행하는 행정 직원 | OAuth 인증 전에 `collect all` 실행, `--channel` 없이 명령 실행, init 안 하고 바로 report 실행, 에러 메시지를 읽지 않고 같은 명령 반복 실행, client_secret.json 경로를 잘못 지정 |
| **A-02** | 급한 학과장 | 내일 회의에 보고서가 필요한 학과장. CLI를 잘 모르고 누군가 알려준 명령만 복붙 | 수집 완료 전에 보고서 생성 시도, 수집 중 Ctrl+C로 중단 후 재실행, 이전 학기 데이터인데 올해로 착각하고 `--year 2026` 지정, `--format pdf` 인데 weasyprint 미설치 |
| **A-03** | 전체 학과 일괄 처리하는 DX지원센터 운영자 | 15개 학과를 한 번에 돌리는 파워 유저. 효율을 위해 스크립트를 짬 | 셸 스크립트로 15개 채널 동시에 `collect all` 실행(프로세스 경합), 한 채널 실패 시 나머지도 중단해버림, 토큰 만료된 채널을 모르고 포함, 출력 디렉터리를 공유해서 채널 간 데이터 혼합 |
| **A-04** | 제목 규칙을 안 지키는 교수 | 영상 제목을 자유분방하게 작성하는 교수 | "3주차 강의" (교수명/교과목 없음), "정교수 미생물 3" (약어), "2024-2 감미 4주 2차" (초축약), "강의영상_최종_진짜최종(2).mp4" (파일명 그대로), 영어로만 작성 "Microbiology Week 3 Session 1" |
| **A-05** | 채널 권한이 뒤바뀐 조교 | 채널 관리자 권한 없이 Analytics 수집을 시도하거나, 다른 학과 채널에 인증 시도 | 소유자가 아닌 채널에서 retention 수집 → 403, 토큰은 A학과인데 `--channel B학과`로 실행, OAuth 동의 화면에서 일부 scope만 허용, 채널 ID와 alias를 혼동 |
| **A-06** | 과거 데이터를 건드리는 감사관 | 3년치 데이터를 소급 분석하려는 사용자 | `--year 2021` 지정했지만 해당 연도 영상이 2개뿐, 이미 삭제된 영상의 video_id로 개별 리포트 요청, 채널이 2023년에 이름이 바뀌어서 channel_meta 불일치, 비공개 전환된 영상의 자막/retention 재수집 시도 |
| **A-07** | 검색 YAML을 잘못 작성하는 사용자 | search_clips.yaml을 직접 편집하지만 YAML 문법에 익숙하지 않음 | 들여쓰기 탭/스페이스 혼용, 한국어 값에 따옴표 누락, week_range에 문자열 "1-8" 입력(리스트 아님), 존재하지 않는 필터 키 사용, 빈 파일로 검색 실행 |
| **A-08** | 보고서만 원하는 외부 평가위원 | 수집 과정에 관심 없고 최종 보고서만 필요. 누군가 만들어둔 output/ 디렉터리를 받아서 리포트만 재생성 | output/ 디렉터리 경로를 USB로 복사하면서 심볼릭 링크 깨짐, JSON 파일 일부만 복사, projects/ 설정 없이 report 명령 실행, 다른 OS(Windows)에서 경로 문제 |
| **A-09** | 여러 프로젝트를 관리하는 운영자 | tube-scout init을 여러 번 실행하여 여러 프로젝트를 관리 | 프로젝트 A에서 작업 중인데 프로젝트 B의 채널로 collect 실행, projects/ 디렉터리를 수동으로 이름 변경, 같은 채널을 두 프로젝트에 등록, 프로젝트 삭제 후 해당 프로젝트 참조 |
| **A-10** | .envrc를 모르는 신규 머신 사용자 | 새 NixOS 머신에서 `nix develop` 후 바로 실행 | agenix 복호화 전에 실행(client_secret 없음), direnv allow 안 한 상태, TUBE_SCOUT_TOKENS_DIR 미설정, .envrc가 참조하는 시크릿 경로가 이 머신에서 다름, flake.nix devShell 의존성 불완전 |

#### 6.3 Group B — 환경/시스템 적대 조건 (7가지)

| # | 조건 | 원인 | 공격 시나리오 |
|---|------|------|-------------|
| **B-01** | 부패한 파일시스템 | 전원 차단, 디스크 장애 | JSON 반쯤 쓰여진 상태 재시작, Parquet 헤더 깨짐, 심볼릭 링크 끊김, 디스크 공간 0, 읽기 전용 디렉터리 |
| **B-02** | 악의적/비정상 YouTube 응답 | API 장애, 프록시 개입 | 빈 items[], pageToken 무한루프, HTTP 403/429/500 연속, 필드 누락 JSON, 200 OK인데 body가 HTML 에러 페이지 |
| **B-03** | 네트워크 장애 | 캠퍼스 Wi-Fi 불안정 | 연결 타임아웃, 응답 중간 끊김, DNS 실패, SSL 오류, rate limit backoff 중 재연결 |
| **B-04** | 유니코드/인코딩 지뢰 | 다국어 영상 제목 | RTL 문자, 제로폭 문자, 이모지 조합, NULL 바이트, 10KB 제목, 서로게이트 페어 |
| **B-05** | 시간 이상 | 서버 시계 오류, 타임존 | publishedAt 1970-01-01, 타임존 없는 날짜, DST 전환, 체크포인트 타임스탬프 미래 시점 |
| **B-06** | 대용량 스케일 | 대규모 채널 | 영상 100,000건, 자막 50MB, Excel 1048576행 초과, 메모리 한계 |
| **B-07** | 동시성/경합 | 스크립트 병렬 실행 | 동시 collect, 동시 atomic write, 체크포인트 race condition, 토큰 동시 갱신 |

#### 6.4 테스트 설계 원칙

1. **사용자 보호가 목적**: Group A 페르소나의 실수에 대해 시스템이 명확한 에러 메시지와 복구 경로를 제시하는지 검증. 데이터 손실 방지가 최우선.
2. **환경 생존이 목적**: Group B 조건에서 시스템이 crash하지 않고, 부분 결과라도 보존하는지 검증.
3. **파이프라인 관통 테스트**: 단일 모듈이 아닌, 사용자 시나리오 전체 흐름을 따라가며 테스트. 예: A-02(급한 학과장)이 수집 중 Ctrl+C → 재실행 → 보고서 생성까지 전체 경로.
4. **연쇄 실패 제한**: 하나의 채널/영상 실패가 전체 파이프라인을 중단시키지 않는지 (blast radius 제한).
5. **최소 5 test cases/persona, 7 cases/condition**: 전체 최소 100+ 신규 adversary 테스트.

#### 6.5 실제 사용자 시나리오 조합 (Cross-Persona)

실제 운영에서 발생할 수 있는, 사용자 실수 + 환경 조건의 복합 시나리오:

| 조합 | 시나리오 | 이런 일이 일어나는 이유 | 검증 |
|------|---------|---------------------|------|
| A-01 + A-05 | 신입 직원이 다른 학과 토큰으로 collect 실행 | 인수인계 시 채널 alias가 뒤바뀌어 전달됨 | 채널 불일치 시 명확한 에러, 다른 학과 데이터 오염 방지 |
| A-02 + B-03 | 급한 학과장이 Wi-Fi 불안정한 상태에서 수집 실행 | 캠퍼스 무선 환경 + 시간 압박 | 중간 끊김 후 체크포인트 복구, 부분 데이터 보존 |
| A-03 + B-07 | 운영자가 15개 채널을 셸 스크립트로 동시 실행 | 효율을 위한 병렬화 시도 | 프로세스 경합 시 데이터 무결성, 파일 잠금 |
| A-04 + B-04 | 교수가 이모지+영어 혼합 제목 작성 | "🧬 Microbiology W3-1 감염미생물학" | 파싱→저장→리포트 전체 관통 정상 동작 |
| A-06 + B-02 | 감사관이 삭제된 영상 데이터를 재수집 시도 | 3년 전 영상이 삭제/비공개 전환됨 | API 404 응답 처리, 기존 캐시 데이터 보존 |
| A-07 + A-08 | 외부 평가위원이 전달받은 YAML로 검색 시도 | YAML 파일이 이메일 전달 중 인코딩 깨짐 | YAML 파싱 에러 시 명확한 위치 안내 |
| A-09 + A-03 | 여러 프로젝트 운영 중 채널이 교차됨 | 프로젝트 A의 채널을 프로젝트 B에서 수집 | 프로젝트 간 데이터 격리 검증 |
| A-10 + B-01 | 새 머신에서 .envrc 없이 실행 후 디스크 에러 | NixOS 설정 불완전 + 외장 디스크 문제 | 설정 누락 에러 메시지 명확성, 부분 쓰기 방어 |

#### 6.6 기존 adversary 테스트와의 관계

현재 16파일 399건의 adversary 테스트는 주로 **단일 모듈 단위**의 에지 케이스. 이번 감사의 adversary 테스트는:

- 기존 테스트와 **중복 없이** 사용자 시나리오/모듈 간 조합/파이프라인 관통에 집중
- 기존 테스트 중 커버리지가 약한 영역(특히 storage, output, cli)을 보강
- 기존 테스트의 실패 패턴을 분석하여 **동일 유형의 취약점이 다른 모듈에도 존재하는지** 교차 검증
- **실제 사용자가 겪을 상황**을 우선순위로 배치 (기술적 공격은 후순위)

**산출물**: `_workspace/audit_layer6_adversary.md` — 페르소나별 테스트 결과 + 발견된 취약점

---

### Layer 7: Security & Robustness (보안 및 견고성)

**목표**: 운영 환경에서 발생할 수 있는 보안 위험과 비정상 입력 처리를 검증한다.

| 검사 항목 | 위험 | 검증 |
|----------|------|------|
| OAuth 토큰 파일 권한 | 토큰 파일이 0644로 저장되면 타 사용자 접근 가능 | 파일 생성 시 0600 확인 |
| 시크릿 로깅 | 토큰/API 키가 에러 메시지/로그에 노출 | grep + 코드 리뷰 |
| Path traversal | `--channel` 이름에 `../` 포함 시 디렉터리 탈출 | 테스트 |
| JSON injection | 영상 제목에 악의적 JSON/HTML 포함 시 | 저장/리포트 생성 테스트 |
| XSS in HTML reports | plotly/Jinja2 렌더링에 스크립트 주입 | 리포트 생성 후 HTML 파싱 |
| Excel formula injection | 셀 값이 `=`, `+`, `-`, `@`로 시작 시 수식 실행 | Excel 출력 검사 |
| 네트워크 타임아웃 | API 무응답 시 무한 대기 | 타임아웃 설정 확인 |
| 환경변수 미설정 | 필수 환경변수 누락 시 명확한 에러 메시지 | 테스트 |

**산출물**: `_workspace/audit_layer7_security.md` — 취약점 목록 + 수정 우선순위

---

## 실행 계획

### 감사 절차 원칙: 발견 → 계획 → 수정

**절대 규칙: 테스트 결과에 따라 바로 코드를 수정하지 않는다.**

모든 감사 Phase는 다음 3단계를 엄격히 따른다:

```
┌─────────────────────────────────────────────────────────┐
│  Stage 1: 발견 (Discovery)                               │
│  - 테스트/분석 실행 → 결함 목록 작성                        │
│  - 각 결함에 심각도(Critical/High/Medium/Low) 부여          │
│  - 영향 범위(어떤 모듈, 어떤 사용자 시나리오) 명시            │
│  - 산출물: _workspace/audit_layerN_*.md                   │
├─────────────────────────────────────────────────────────┤
│  Stage 2: 수정 계획 (Remediation Plan)                    │
│  - 전체 발견사항을 종합하여 우선순위 결정                     │
│  - 결함 간 의존관계 파악 (A를 고치면 B도 해결되는지)          │
│  - 수정 순서, 수정 방법, 영향받는 테스트 명시                 │
│  - 산출물: _workspace/audit_remediation_plan.md           │
│  - ⚠️ 사용자 검토 및 승인 후에만 Stage 3 진입               │
├─────────────────────────────────────────────────────────┤
│  Stage 3: 수정 (Fix)                                     │
│  - 승인된 계획에 따라 코드 수정                              │
│  - 수정마다 리그레션 테스트 실행                              │
│  - 기존 1,067 테스트 + 신규 테스트 전체 pass 확인            │
│  - 산출물: 커밋 + _workspace/audit_fix_log.md             │
└─────────────────────────────────────────────────────────┘
```

### Phase 구성

| Phase | Layer | 방법 | 에이전트 | Stage |
|-------|-------|------|---------|-------|
| **Phase 1** | L1 정적 분석 | 자동화 도구 실행 | auditor | Discovery |
| **Phase 2** | L5 일관성 | grep/AST 기반 전수 검사 | auditor | Discovery |
| **Phase 3** | L2 모듈 계약 | 패키지별 API surface 분석 | auditor | Discovery |
| **Phase 4** | L7 보안 | 코드 리뷰 + bandit + 수동 검사 | auditor | Discovery |
| **Phase 5** | L6 Adversary | 17 페르소나 + 8 조합 시나리오 테스트 작성/실행 | adversary | Discovery |
| **Phase 6** | L3 통합 검증 | 신규 통합 테스트 작성/실행 | developer + adversary | Discovery |
| **Phase 7** | L4 E2E | 파이프라인 E2E 테스트 작성/실행 | developer + pair-programmer | Discovery |
| **Phase 8** | 수정 계획 | 전체 발견사항 종합 → 우선순위 → 수정 계획 | auditor | Plan |
| **Phase 9** | 수정 실행 | 승인된 계획에 따른 코드 수정 + 리그레션 | developer | Fix |

### Phase 간 의존

```
Phase 1 (정적 분석) ──┐
Phase 2 (일관성)  ────┤── 병렬 실행 가능
Phase 3 (모듈 계약) ──┘
         │
         ▼
Phase 4 (보안)     ────┐
Phase 5 (Adversary) ───┤── Phase 1~3 결과 참조, 병렬 가능
Phase 6 (통합)     ────┘
         │
         ▼
Phase 7 (E2E) ── Phase 5~6 완료 후
         │
         ▼
Phase 8 (수정 계획) ── 전체 발견사항 종합
         │
         ▼
    ⏸️ 사용자 검토/승인
         │
         ▼
Phase 9 (수정 실행) ── 승인된 계획에 따라 수정
```

## 감사 완료 기준

| 기준 | 목표 |
|------|------|
| ruff violations | 0 |
| mypy errors (strict) | 0 (또는 단계적 도입 계획 수립) |
| 데드코드 | 0 |
| 순환 import | 0 |
| bandit High/Medium | 0 |
| 모듈 계약 불일치 | 0 |
| 일관성 위반 | 0 (또는 허용 예외 목록 문서화) |
| 신규 통합 테스트 | Layer 3 매트릭스 100% 커버 |
| 신규 adversary 테스트 | 100+ 케이스 (기존 399 + 신규 100+) |
| E2E 시나리오 | Layer 4 전체 통과 |
| 테스트 전체 통과 | 기존 1,067 + 신규 전부 pass |
| 수정 계획 승인 | 사용자 리뷰 완료 |

## 산출물 요약

모든 산출물은 `_workspace/` 아래에 생성한다:

```
_workspace/
├── audit_layer1_static.md          ← 정적 분석 결과
├── audit_layer2_contracts.md       ← 모듈 계약 감사
├── audit_layer3_integration.md     ← 통합 검증 계획 + 결과
├── audit_layer4_e2e.md             ← E2E 테스트 결과
├── audit_layer5_consistency.md     ← 일관성 감사
├── audit_layer6_adversary.md       ← 적대적 테스트 결과
├── audit_layer7_security.md        ← 보안 감사
├── audit_remediation_plan.md       ← 🔑 수정 계획 (사용자 승인 대상)
├── audit_fix_log.md                ← 수정 실행 기록
└── audit_summary.md                ← 종합 보고서
```
