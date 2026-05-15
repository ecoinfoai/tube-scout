# Phase 0 — Research: Takeout 적재 모듈 재작성 및 운영자 등록 흐름 정합화

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-05-15

## Scope

본 spec 은 spec 013 (v0.5.0) 의 적재 모듈 결함 수정 PATCH 다. 신규 의존성 0 건, 신규 모듈 0 건, 신규 schema 0 건. 따라서 외부 기술 조사보다는 (a) 실측 데이터에 기반한 컬럼/구조 결정, (b) /speckit.clarify 단계의 4 개 결정, (c) Assumptions 7 건의 권장 채택이 본 phase 의 핵심이다.

NEEDS CLARIFICATION 마커: **0 개** (모든 ambiguity 가 spec.md Clarifications + Assumptions 절에서 해소됨).

본 문서는 각 결정을 Decision / Rationale / Alternatives considered 형식으로 정리하여 plan/tasks 단계의 의사결정 추적을 보장한다.

---

## R-1 — 채널.csv 컬럼 매핑

**Decision**: 한국어 Takeout export 의 `채널.csv` 헤더 = `채널 ID, 채널 국가, 채널 태그 1, 채널 제목(원본), 채널 공개 상태`. 본 spec 은 `채널 ID` → `channel_id`, `채널 제목(원본)` → `title`, `채널 국가` → `country`, `채널 공개 상태` → privacy_status (한글→영어 매핑) 의 4 컬럼을 사용한다.

**Rationale**: 2026-05-15 archive 정찰 (`idea/idea-spec016-takeout-archive-survey.md` §2.2) 에서 5 컬럼을 모두 실측. 코드의 기존 `_CHANNEL_CSV_REQUIRED = {"채널 ID", "채널 이름"}` 가정은 "채널 이름" 컬럼이 실제로 존재하지 않아 결함 3 으로 차단. `채널 제목(원본)` 이 의미상 채널명에 해당.

**Alternatives considered**:
- ❌ `채널 태그 1` 을 별도 메타로 사용 → 채널 설명에 해당하지만 본 spec 범위 밖 (결함 9 정보 등급). 보류.
- ❌ 영어 export 헤더 매핑 동시 지원 → 사용자가 한국어 Takeout 단일 지원 확정 (Assumption 1).

---

## R-2 — 동영상*.csv 컬럼 매핑

**Decision**: 한국어 Takeout 의 `동영상.csv` / `동영상(N).csv` 헤더 = `동영상 ID, 근사치 길이(밀리초), 동영상 오디오 언어, 동영상 카테고리, 동영상 설명(원본) 언어, 채널 ID, 동영상 제목(원본), 동영상 제목(원본) 언어, 개인 정보 보호, 동영상 상태, 동영상 생성 타임스탬프` (11 컬럼). `동영상 URL` 컬럼은 **존재하지 않으며** video_id 로부터 `https://youtu.be/<video_id>` 로 도출.

**Rationale**: archive 정찰 §2.3 + idea 결함 보고서 §결함 4 의 실측 대조표. 9 개 코드 가정 중 6 개가 이름이 다르고 1 개 (동영상 URL) 는 컬럼 자체 부재.

**Alternatives considered**:
- ❌ 메타 컬럼에서 `동영상 URL` 을 읽으려는 fallback → 해당 컬럼이 영구히 존재하지 않으므로 코드가 불필요한 None-check 를 누적할 위험.
- ❌ video_id 로 YouTube Data API 호출하여 URL 검증 → spec 의 Takeout 단독 흐름과 정면 충돌.

---

## R-3 — 분할 단위 (200 영상/csv × 13 파일)

**Decision**: 한국어 Takeout 의 `동영상.csv` (본 파일) + `동영상(1)~(12).csv` 분할 파일 13 개. 각 파일 = 200 영상 (마지막 chunk 만 154 영상). 13 파일이 모두 disjoint (교집합 video_id = 0). 채널 전체 영상 수 = 200 × 12 + 154 = **2554** (간호학과 기준).

**Rationale**: archive 정찰 §2.4 의 Python csv 모듈 실측. awk/sed 결과는 multi-line quoted 필드로 어그러져 잘못된 값을 줌. 본 spec 의 모든 csv 파싱은 RFC4180 quoting-safe 파서(`csv.DictReader`) 사용 의무 (FR-010).

**Alternatives considered**:
- ❌ glob `동영상*.csv` 광범위 패턴 유지 → `동영상 녹화*.csv`, `동영상 텍스트*.csv` 까지 흡수해 컬럼 검증 단계에서 raise (결함 8).
- ✅ 정확 glob 패턴: `meta_dir.glob("동영상.csv")` + `meta_dir.glob("동영상(*).csv")` 두 패턴 union 또는 정규식 `^동영상(?:\(\d+\))?\.csv$` 매치. spec 의 FR-002 + FR-021 채택.

---

## R-4 — privacy 한글-영어 매핑 정책

**Decision**: 한글 값 (`공개` / `일부 공개` / `비공개`) → 영어 표준값 (`public` / `unlisted` / `private`) 매핑 표를 코드에 박는다. 매핑 표에 없는 새 한글 값(예: 미래의 `예약 공개`) 을 만나면 **해당 row 한 행만 skip** 하고 audit 에 `result=skip, reason=unknown_privacy_value, raw_value=<원본 한글>` 명시 기록. 적재 전체는 계속.

**Rationale**: spec.md Clarifications Q2. 알 수 없는 값을 만나서 적재 전체를 fail-fast 로 막으면 운영자가 매핑 PR 을 만들 때까지 2554 영상 전체 적재가 차단되어 가용성 손실. sentinel `unknown` 매핑은 분석 단계에서 표준값과 의미 혼동 위험. 부분 skip + 명시 audit 이 silent-skip 차단 정책과 양립.

**Alternatives considered**:
- ❌ 적재 전체 fail-fast → 가용성 손실.
- ❌ DB 에 `unknown` sentinel 저장 → 분석 의미 혼동.
- ❌ alias 별 strict/lenient 플래그 → 신규 옵션 추가라 PATCH 범위 벗어남.

---

## R-5 — Takeout 동봉 자막 부재 + ASR 단일 경로

**Decision**: Takeout archive 어느 폴더에도 영상 본문 자막 트랙(.vtt/.srt/.sbv)이 동봉되지 않으며 향후에도 YouTube 자막 다운로드 계획은 없다 (사용자 확정 2026-05-15). 따라서 자막은 항상 faster-whisper ASR 로 생성한다. `--source asr` 가 기본·유일 경로, `--source youtube` 는 exit 2 + 명확 메시지로 deprecate.

**Rationale**: archive 정찰 §3 에서 `동영상 텍스트(N).csv` 가 자막이 아니라 영상 제목 OCR 추정 텍스트임을 실측 확인. spec 013 의 `--source asr` 흐름이 spec 016 에서 단일 경로로 격상.

**Alternatives considered**:
- ❌ `--source youtube` 를 silent fallback 으로 유지 → Constitution II (Fail-Fast) 와 충돌, 사용자가 명시한 deprecation 의도와 불일치.
- ❌ `--source asr` 의 grace period (`--source youtube` 가 한동안 동작 후 폐기) → 이미 2026-05-12 결정으로 영구 폐기. grace 불필요.

---

## R-6 — 두 등록부 (channels.json / departments.json) 공존 + union 표시

**Decision**: 두 등록부 공존을 유지하고, `admin list` 가 union 을 출력한다. 각 row 는 `source` (channels/departments/both) + `consistency` (ok/mismatch) 컬럼을 가진다. 비정합 alias 가 있어도 `admin list` 는 exit 0 으로 종료, stderr 에 WARNING 라인 + `--json` 출력의 `consistency` 필드로 자동화가 감지한다. 분석 명령(`collect`/`analyze`/`report`) 만 비정합 alias 사용 시 명시적 오류로 차단.

**Rationale**: spec.md Clarifications Q3. 두 등록부의 의미 (channels.json = 런타임 등록부, departments.json = 운영자 인터페이스용) 가 다르고 spec 008 웹 UI 가 departments.json 을 직접 사용 중이라 단일화 마이그레이션은 PATCH 범위 밖. union 표시 + 분석 단계 차단으로 결함 1 의 false-negative 만 해소.

**Alternatives considered**:
- ❌ channels.json 단일화 + departments.json 마이그레이션 → spec 008 웹 UI 코드 변경 필요, PATCH 범위 벗어남.
- ❌ `admin list` exit 1 (비정합 시 자체 실패) → 비정합 alias 한 개 때문에 모든 자동화가 stop. 운영자 불편.
- ❌ 신규 `admin verify` 명령 → 신규 명령 추가라 PATCH 범위 벗어남.

---

## R-7 — `add-department` 의 OAuth env 옵션 optional 화

**Decision**: `--channel-id-env`, `--client-secret-env`, `--api-key-env` 3 옵션을 모두 optional 로 변경. 3 개가 모두 명시되면 spec 003 OAuth 흐름 작동(호환). 3 개가 모두 생략되면 OAuth consent 단계 skip (Takeout 단독). 일부만 명시되면 명시적 검증 오류로 종료 (FR-013).

**Rationale**: 2026-05-12 Takeout pivot 으로 신규 학과는 OAuth 자격 없이 등록 가능해야 함. 그러나 spec 003 시절 등록한 운영자가 여전히 OAuth 자격을 명시하는 흐름도 유지해야 호환성 깨지지 않음. 3 가지 명령 후보(A: --takeout-only 플래그 / B: 별도 명령 신설 / C: 3 옵션 optional) 중 C 가 명령 수 증가 없이 양쪽 흐름 지원.

**Alternatives considered**:
- ❌ A: `--takeout-only` 플래그 → 옵션 추가가 호환성 break 는 아니지만, 운영자가 의도를 명시적으로 전달해야 하는 추가 부담.
- ❌ B: `admin add-department-takeout` 별도 명령 → 명령 수 증가, 운영자 학습 부담.
- ✅ C: 3 옵션 모두 optional + 일부 명시 시 명시적 오류. 호환성 100% + 자연스러운 추론.

---

## R-8 — 같은 video_id 의 메타가 다른 part 에서 변경된 경우

**Decision**: `INSERT OR IGNORE` 의 first-write-wins 정책 유지. 첫 적재 시점의 메타가 영구히 진실. 후속 part 가 다른 값 (예: YouTube Studio 에서 제목 수정 후 새 export) 을 들고 와도 DB 행은 변경하지 않으며 별도의 conflict audit 행도 남기지 않는다.

**Rationale**: spec.md Clarifications Q1. UPSERT (최신 part 우선) 정책은 데이터 정확성 ↑이지만 코드 복잡도 ↑ + 본 spec 의 PATCH 범위 벗어남. Takeout export 가 본질적으로 시점 스냅샷이므로 운영자가 part 적재 순서를 통제하면 첫 적재가 진실이라는 가정도 합리적.

**Alternatives considered**:
- ❌ UPSERT + audit `metadata_updated` 기록 → 정확성 ↑이지만 PATCH 범위 벗어남.
- ❌ 변경 감지 + audit conflict 기록 (DB 는 기존 유지) → 운영자가 수동 결정해야 함, 추가 명령 필요.
- ❌ 변경 감지 + 운영자 결정 대기 (`admin metadata-resolve`) → 신규 명령, PATCH 범위 벗어남.

---

## R-9 — 다중 archive part 의 메타 동봉 위치

**Decision**: 작성 시점에는 본 archive (3-001) 한 part 만 검증 가능했고 사용자도 미확인. **"모든 part 에 메타 중복 동봉" 으로 가정**. 잘못 가정해도 멱등 적재(FR-009) 로 안전 — 같은 video_id 를 두 번째로 만나면 무시.

**Rationale**: 다음 archive part 를 풀어 `동영상 메타데이터/` 폴더가 부재한 게 확인되면 quickstart 문서 (FR-021) 를 보강하면 된다. 본 spec 의 코드 흐름은 양쪽 가정 (part 별 메타 동봉 / 첫 part 에만 동봉) 모두에서 작동.

**Alternatives considered**:
- ❌ "첫 part 에만 메타 동봉" 가정 → 잘못된 가정이면 두 번째 part 이후 적재가 빈 메타로 실패할 수 있음.
- ❌ 사용자에게 추가 archive 를 풀어 확인 후 spec 작성 → 일정 지연. spec 016 작성 자체가 운영 차단 결함 해소가 우선.

---

## R-10 — 적재 성능 측정 의무화 + 정량 임계는 plan/tasks 위임

**Decision**: IngestResult 에 `elapsed_seconds` 필드, audit row 에 `elapsed_ms` 필드를 추가. 측정/기록 의무는 spec 의 FR-022/023 + SC-009 로 박힘. 정량 임계 (예: "10,000 영상 메타 적재가 N분 이내") 은 plan 첫 task 에서 baseline 측정 후 plan/tasks 안에 추가.

**Rationale**: spec.md Clarifications Q4. baseline 측정 없는 추정 기준을 spec SC 에 박는 것은 회귀 테스트가 추정 위에 놓이는 위험. 측정 의무 + 측정값 기록은 trend 기반 회귀 검증이 가능하게 함.

**Alternatives considered**:
- ❌ 검증 환경 한정 sanity check SLA 한 줄 spec 추가 → 본 작업 머신 의존성. CI 환경/타 운영자 머신과 시간차 발생 가능.
- ❌ 운영 환경 SLA 까지 명시 (22학과 × 수만 영상) → 추정 기준, 회귀 검증 어려움.
- ❌ 측정 자체 의무화 없이 plan 단계 자유 → 회귀 검증 기준 부재.

---

## R-11 — `동영상 텍스트(N).csv` 의 OCR 텍스트 활용 제외

**Decision**: spec 016 본 범위에서 제외. `_IGNORED_PATTERNS` 에 `^동영상 텍스트` 가 이미 포함되어 있어 무시 정책 유지. 분석 활용은 추후 separate spec.

**Rationale**: archive 정찰 §3 에서 자막이 아닌 영상 제목 OCR 추정 텍스트로 확인. 본 spec 의 자막 단일 경로 결정과 결을 같이 한다 (자막은 ASR, OCR 은 별도 분석 트랙).

**Alternatives considered**:
- ❌ `동영상 제목 텍스트 세그먼트 1` 컬럼을 보조 인덱싱에 사용 → PATCH 범위 벗어남, 신규 분석 흐름 도입.

---

## R-12 — 의존성 변경 0건 확인

**Decision**: 본 spec 은 `pyproject.toml` 의 `[project]` / `[project.optional-dependencies]` 어느 곳에도 의존성 추가 / 제거 / 버전 변경을 일으키지 않는다. 변경 표면은 `cli/admin.py`, `cli/collect.py`, `services/takeout_ingest.py`, `services/audit_writer.py`, `models/content.py` 5 파일.

**Rationale**: 결함 11 개 모두 기존 코드의 파싱·매핑·검증 로직 결함이므로 외부 라이브러리 추가/제거가 필요하지 않다. faster-whisper, CTranslate2, ffmpeg, chromaprint 모두 spec 013 시점에 도입 완료 + `[asr]` extra 가 이미 정상 작동 확인됨 (idea-spec016-takeout-ingest-defects §5).

**Alternatives considered**:
- ❌ csv 파싱 라이브러리 교체 (pandas / polars) → 기존 `csv.DictReader` 가 RFC4180 quoting-safe + 멀티-라인 quoted 필드를 정상 처리. 라이브러리 교체 불필요.

---

## Phase 0 종료

NEEDS CLARIFICATION 마커 0 개로 Phase 1 진입. Phase 1 산출물은 data-model.md / contracts/ / quickstart.md 이며, 본 research 의 결정들이 그 세 문서의 각 단락에서 인용된다.
