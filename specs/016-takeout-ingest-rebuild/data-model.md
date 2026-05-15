# Phase 1 — Data Model: Takeout 적재 모듈 재작성

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-05-15

## Scope

본 spec 은 PATCH 범위라 **SQLite v4 스키마 자체에 변경이 없다** (Cross-Spec Boundary B-4 보장 유지). 본 문서는 (a) spec 013 의 기존 entity 7 개를 본 spec 의 결정사항에 비추어 보강, (b) privacy_status 의 영어 표준값 enum 제약 명시, (c) 적재 흐름의 상태 전이를 정의한다.

## Entity Overview

| Entity | Persistence | Owner spec | 본 spec 의 변경 |
|---|---|---|---|
| TakeoutArchive | 파일시스템 (디렉토리) | spec 013 | (변경 없음) |
| ChannelMetadata | SQLite `channel_metadata` + JSON `channel_meta.json` | spec 013 | privacy_status validator 추가 |
| VideoMetadata | SQLite `video_metadata` + JSON `videos_meta.json` | spec 013 | privacy_status validator 추가, title 출처 컬럼 변경 |
| IngestAuditEntry | CSV `audit.csv` (append-only) | spec 013 | reason 어휘 확장, elapsed_ms 컬럼 추가 |
| ChannelRegistration | JSON `channels.json` | spec 003 | (변경 없음) |
| Department | JSON `departments.json` | spec 008 | OAuth env 3 필드 nullable |
| RegistryUnionRow | (메모리 only — `admin list` 출력) | **spec 016 신규** | 신설 — channels.json + departments.json union 표시 |

---

## TakeoutArchive

**Persistence**: 파일시스템 디렉토리 (DB 행 없음).

**Schema (디렉토리 구조)**:

```
<takeout-root>/
└── Takeout/
    └── YouTube 및 YouTube Music/
        ├── 동영상/                          # mp4 본체 (한 archive part 에 9개 ~ 수십 개)
        ├── 동영상 메타데이터/
        │   ├── 동영상.csv                   # 본 파일 (200 영상)
        │   ├── 동영상(1).csv ~ 동영상(N).csv # 분할 파일 (각 200 영상, 마지막 chunk 만 짧음)
        │   ├── 동영상 녹화*.csv             # 무시 대상 (_IGNORED_PATTERNS)
        │   └── 동영상 텍스트*.csv           # 무시 대상 (_IGNORED_PATTERNS)
        ├── 채널/
        │   ├── 채널.csv                     # ★ 적재 입력
        │   ├── 채널 URL 구성.csv             # 무시 (분석 활용 없음)
        │   ├── 채널 기능 데이터.csv          # 무시
        │   ├── 채널 커뮤니티 운영 설정.csv   # 무시
        │   └── 채널 페이지 설정.csv          # 무시
        ├── 댓글/, 재생목록/, 구독정보/, 시청 기록/  # 모두 _IGNORED_PATTERNS 로 무시
```

**Identity**: `takeout-YYYYMMDDTHHMMSSZ-<group>-<part>` 형식의 archive 이름 (Google Takeout 명명 규칙).

**Validation rules**:
- `Takeout/YouTube 및 YouTube Music/` 폴더 부재 시 `FileNotFoundError` 즉시 발생.
- `채널.csv` 부재 시 `FileNotFoundError` 즉시 발생.
- `동영상.csv` 또는 `동영상(N).csv` 가 한 개도 없으면 `FileNotFoundError` 즉시 발생 (FR-007).

**State transitions**: 없음 (정적 파일시스템).

---

## ChannelMetadata

**Persistence**: SQLite `channel_metadata` 테이블 + 동시에 `data/{alias}/channel_meta.json` atomic write.

**Schema (Pydantic v2 + SQLite)**:

```python
class ChannelMetadata(BaseModel):
    channel_id: str          # PK, 'UC' 로 시작 (validator)
    channel_alias: str       # 운영자 입력 alias (예: 'nursing')
    title: str | None        # '채널 제목(원본)' 컬럼
    country: str | None      # '채널 국가' 컬럼 (예: 'KR')
    privacy_status: Literal['public', 'unlisted', 'private'] | None  # 한글 → 영어 매핑
    source: Literal['takeout', 'youtube'] = 'takeout'
    takeout_root_hint: str | None = None  # 마지막 적재된 takeout_dir 절대 경로 (재현용)
    ingested_at: str         # ISO 8601 UTC
```

**Validation rules**:
- `channel_id` 가 `UC` 로 시작하지 않으면 `ValidationError` (spec 003 의 기존 validator 보존, B-1).
- `title` 이 `None` 또는 빈 문자열이면 `ValueError("channel title missing — '채널 제목(원본)' column may be absent")` 즉시 발생 (FR-006, silent fail 금지).
- `privacy_status` 가 enum 외 값이면 `ValidationError` 즉시 발생 (한글값은 매핑 단계에서 영어로 변환되거나 row 자체 skip).

**State transitions**:
- `(없음) → ingested` — 첫 적재 시 INSERT.
- `ingested → ingested` — UPSERT (`ON CONFLICT(channel_id) DO UPDATE SET takeout_root_hint = excluded.takeout_root_hint, ingested_at = excluded.ingested_at`). title/country 등 핵심 필드는 갱신하지 않음 (first-write-wins).

---

## VideoMetadata

**Persistence**: SQLite `video_metadata` 테이블 + 동시에 `data/{alias}/videos_meta.json` atomic write (list 직렬화).

**Schema (Pydantic v2 + SQLite)**:

```python
class VideoMetadata(BaseModel):
    video_id: str            # PK
    channel_id: str          # FK → ChannelMetadata.channel_id
    title: str               # '동영상 제목(원본)' 컬럼 (필수)
    duration_seconds: float  # '근사치 길이(밀리초)' / 1000.0
    language: str | None     # '동영상 오디오 언어'
    category: str | None     # '동영상 카테고리'
    privacy_status: Literal['public', 'unlisted', 'private'] | None  # 한글 → 영어 매핑
    created_at: datetime | None  # '동영상 생성 타임스탬프'
    source: Literal['takeout', 'youtube'] = 'takeout'
    match_confidence: Literal['high', 'medium', 'ambiguous', 'unmapped'] | None
    mp4_relative_path: str | None  # 'data/{alias}/동영상/<filename>.mp4' or None (mp4 부재)
    ingested_at: str         # ISO 8601 UTC
```

**Validation rules**:
- `video_id` 빈 문자열 → row skip (메타 csv 의 빈 행 보호).
- `title` 빈 문자열 또는 None → `ValueError` (silent fail 금지, FR-006).
- `privacy_status` 한글 매핑:
  - `공개` → `public`
  - `일부 공개` → `unlisted`
  - `비공개` → `private`
  - 위 매핑 표에 없는 값 → row 자체 skip + audit `result=skip, reason=unknown_privacy_value, raw_value=<원본 한글>` 기록 (FR-005, R-4).
- `duration_seconds` 음수 → `ValidationError`.
- URL 이 필요한 호출부 (예: 보고서 링크) 는 `video_id` 로부터 `https://youtu.be/<video_id>` 도출 — Pydantic 필드로 저장하지 않음 (R-2).

**State transitions**:
- `(없음) → ingested (mp4_relative_path=NULL)` — mp4 본체가 본 archive 에 없는 영상의 첫 적재.
- `(없음) → ingested (mp4_relative_path=<path>)` — mp4 본체가 archive 에 동봉되어 evidence-score 매핑 성공한 영상의 첫 적재.
- `ingested → ingested (mp4_relative_path 갱신)` — 다른 archive part 에서 mp4 본체가 처음 발견된 경우 mp4_relative_path 만 UPDATE. title/duration/privacy_status 등 메타 필드는 first-write-wins (R-8) 로 변경하지 않음.

---

## IngestAuditEntry

**Persistence**: CSV `data/{alias}/audit.csv` (append-only).

**Schema**:

| 컬럼 | 타입 | 의미 | 본 spec 의 변경 |
|---|---|---|---|
| stage | string | 적재 단계 식별자 = `takeout_ingest` | (보존, B-5) |
| video_id | string | 영상 ID 또는 `n/a` (csv 무시 audit 의 경우) | (보존) |
| result | enum `success` / `skip` / `failure` | 처리 결과 | (보존) |
| reason | string | 결과 설명. **본 spec 에서 어휘 확장**: `no_mp4_in_archive`, `unknown_privacy_value`, `ignored_by_policy`, `no_match`, `multiple_candidates`, ... | 어휘 확장 (FR-008/019/023) |
| mp4_filename | string | mp4 파일명 또는 `n/a` | (보존) |
| match_confidence | enum `high`/`medium`/`ambiguous`/`unmapped`/`none` | evidence-score 매핑 결과 | (보존) |
| score | float | evidence-score 매핑 점수 (0.0~1.0) | (보존) |
| raw_value | string | unknown_privacy_value 같은 reason 에서 원본 한글값 보존 | **신설** (R-4) |
| elapsed_ms | int | 해당 row 처리 소요 시간 (ms 단위) | **신설** (FR-023, R-10) |
| timestamp | string | ISO 8601 UTC | (보존) |

**Validation rules**:
- `result` 가 enum 외 값이면 audit_writer 가 raise.
- `result=skip` 인 row 는 반드시 `reason` 이 빈 문자열이 아니어야 함 (silent skip 차단).

**State transitions**: append-only — row 가 한 번 기록되면 절대 수정/삭제하지 않음.

---

## ChannelRegistration (spec 003 boundary B-1)

**Persistence**: JSON `~/.config/tube-scout/tokens/channels.json` (atomic write, 0600).

**Schema (Pydantic, spec 003 의 기존 정의 그대로)**:

```python
class ChannelRegistration(BaseModel):
    alias: str               # PK, 영문 + 숫자 + 하이픈
    channel_id: str          # 'UC' 시작
    channel_name: str
    registered_at: str       # ISO 8601 UTC
    last_used_at: str        # ISO 8601 UTC
    token_path: str          # ~/.config/tube-scout/tokens/{alias}.json
```

**본 spec 의 변경**: 없음. read-only 로 소비 (B-1).

---

## Department (spec 008 boundary B-2)

**Persistence**: JSON `${CONFIG_DIR}/departments.json` (atomic write).

**Schema (Pydantic, spec 008 의 기존 정의 + 본 spec 의 nullable 화)**:

```python
class Department(BaseModel):
    alias: str               # PK, 영문 + 숫자 + 하이픈
    display_name: str        # 1~32자
    channel_id_env: str | None       # spec 016 변경: None 허용
    client_secret_env: str | None    # spec 016 변경: None 허용
    api_key_env: str | None          # spec 016 변경: None 허용
    registered_at: str       # ISO 8601 UTC
```

**Validation rules**:
- 3 OAuth env 필드는 **모두 None 이거나 모두 비-None** 이어야 함 (FR-013, R-7). 일부만 명시되면 `ValidationError`.
- env 변수 이름은 `^TUBE_SCOUT_[A-Z0-9_]+$` 정규식 매치 (spec 003 의 기존 `_ENV_NAME_PATTERNS` 보존).

**State transitions**:
- `(없음) → registered (3 env null)` — Takeout 단독 등록 (US 2 Scenario 1).
- `(없음) → registered (3 env 모두 명시)` — spec 003 호환 OAuth 등록 (US 2 Scenario 2).
- `registered → (변경 불가)` — 등록 후 alias / env 변경은 본 spec 범위 밖 (별도 명령 필요).

---

## RegistryUnionRow (spec 016 신규)

**Persistence**: 메모리 only — `admin list` 명령의 출력 row. 디스크에 저장되지 않음.

**Schema**:

```python
class RegistryUnionRow(BaseModel):
    alias: str
    display_name: str | None     # departments.json 우선, 없으면 channels.json 의 channel_name
    channel_id: str | None       # channels.json 의 channel_id, 또는 None (departments-only alias)
    source: Literal['channels', 'departments', 'both']
    consistency: Literal['ok', 'mismatch']
```

**Derivation logic**:
1. `channels.json` 의 alias 집합 = C
2. `departments.json` 의 alias 집합 = D
3. 출력 row 집합 = C ∪ D
4. 각 row 의 source:
   - alias ∈ C ∧ alias ∉ D → `channels`
   - alias ∉ C ∧ alias ∈ D → `departments`
   - alias ∈ C ∧ alias ∈ D → `both`
5. consistency (alias ∈ C ∧ alias ∈ D 인 경우만 검증):
   - C.channel_id == D 의 channel_id_env 가 가리키는 환경변수 값 → `ok`
   - 위가 불일치 → `mismatch`
   - 둘 중 하나라도 빈 값 → `mismatch` (run-time 검증 가능한 한도 안에서)

**Validation rules**: 없음 (read-only view model).

**State transitions**: 없음.

---

## SQLite v4 Schema 보존 확인 (Cross-Spec Boundary B-4)

본 spec 은 SQLite v4 스키마에 다음 변경을 가하지 않음을 명시한다.

- ✅ `channel_metadata` 테이블 — 컬럼 추가/제거 없음.
- ✅ `video_metadata` 테이블 — 컬럼 추가/제거 없음.
- ✅ `processing_status` 테이블 — spec 013 의 4 ALTER 컬럼 (`match_confidence`, `caption_source_detail`, ...) 보존.
- ✅ `quality_results` 테이블 — `asr_quality_flags` JSON 컬럼 보존.
- ✅ `comparison_results` 테이블 — `audio_fp_*`, `source_type_pair` 컬럼 보존.

본 spec 의 변경은 모두 (1) 기존 컬럼에 들어가는 값의 의미 강화 (privacy_status 영어 표준값 보장), (2) `INSERT OR IGNORE` 의 멱등성 유지, (3) 적재 audit CSV 의 row 어휘 확장 — 세 갈래로 한정된다.

migration 코드도 추가 없음 — `_ensure_v4()` 의 기존 흐름 (`migrate_to_v2 → migrate_to_v3 → migrate_to_v4`) 보존.

---

## 적재 흐름의 상태 전이 (state machine)

한 archive part 의 적재 흐름:

```
[archive root 발견]
       │
       ▼
  parse_takeout_csv_metadata()  ── csv 파싱 실패 ──▶ [fail, error message]
       │
       ▼
  ChannelMetadata 생성 + dedup
       │
       ▼
  VideoMetadata 생성 (2554 row) ─ unknown privacy ──▶ [row skip + audit]
       │
       ▼
  evidence-score 매핑 (mp4 ↔ video_id)
       │
       ├─ high/medium ──▶ mp4_relative_path 채워짐
       ├─ ambiguous ────▶ audit reason=multiple_candidates
       ├─ unmapped ─────▶ audit reason=no_match
       └─ mp4 부재 ─────▶ audit reason=no_mp4_in_archive
       │
       ▼
  dry_run? ──── True ──▶ [IngestResult 출력만, DB 미변경]
       │
       │ False
       ▼
  _ensure_v4(db_path) ─ 마이그레이션 (멱등)
       │
       ▼
  _persist_metadata() ── INSERT OR IGNORE (first-write-wins)
       │
       ▼
  channel_meta.json + videos_meta.json atomic write
       │
       ▼
  assemble_channel_work_dir() ── mp4 symlink (idempotent)
       │
       ▼
  [IngestResult 출력 + audit CSV 닫기]
```

각 단계의 실패는 Constitution II (Fail-Fast) 에 따라 즉시 raise (silent 무시 금지). row 단위 skip 만 명시적 audit 으로 기록.
