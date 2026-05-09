# Data Model: Subtitle Full-Stack Reuse Detection

**Feature**: 011-reuse-fullstack-subtitle
**Storage**: 기존 `02_analyze/content/content_reuse.db` (SQLite, spec 007 인계) + 기존 `02_analyze/content/embeddings.parquet` (polars). 신규 storage 엔진 0개.

본 문서는 spec 007 data-model의 점진적 확장을 정의한다. 모든 변경은 idempotent migration 으로 적용되며 spec 007 데이터는 그대로 보존된다 (FR-026, SC-009).

---

## 1. 변경 요약

| 종류 | 대상 | 변경 |
|---|---|---|
| ALTER | `comparison_results` | i6/i7/i8 + reuse_pattern + layer_attribution + baseline_subtraction + matching_mode 컬럼 추가 |
| ENUM 확장 | `comparison_results.review_status` | UNREVIEWED → 유지, CONFIRMED_DUPLICATE → 유지, FALSE_POSITIVE → 유지, **PENDING** 신규 |
| NEW TABLE | `professor_pool` | 채널-별칭/저자 → professor_id 매핑 |
| NEW TABLE | `baseline_corpus` | 교수별 stylistic 반복 어구 |
| NEW TABLE | `phrase_whitelist` | 교수별 phrase-level 화이트리스트 |
| NEW TABLE | `pair_checkpoint` | nC2 분석 진행률 메타 |
| NEW TABLE | `match_spans` | 비교 쌍의 일치 구간 시간축 evidence |
| NEW TABLE | `policy_config` | 프로젝트별 정책 임계값 (또는 YAML 파일 — R-4 결정 따라) |

---

## 2. ALTER: `comparison_results`

기존 spec 007 컬럼 그대로 + 다음 추가:

| 신규 컬럼 | Type | Description | Nullable |
|---|---|---|---|
| matching_mode | TEXT | `'M-default'` 또는 `'M-nC2'`. 기존 row는 `'M-default'`로 backfill | NOT NULL DEFAULT `'M-default'` |
| professor_id | TEXT | spec 011 professor pool 참조. 기존 row는 NULL 허용 | nullable |
| i6_longest_contiguous_seconds | REAL | I-6: 가장 긴 연속 일치 구간 길이 (초) | nullable |
| i7_distribution_dispersion | REAL | I-7: 일치 구간 길이 분포의 dispersion measure (stdev / cluster count 기반) | nullable |
| i8_position_diversity | REAL | I-8: 영상 timeline의 early/middle/late 분산 (0~1 범위) | nullable |
| reuse_pattern | TEXT | `'whole-same-week'` / `'scattered-same-week'` / `'whole-different-week'` / `'scattered-different-week'` / `NULL` (M-default) | nullable |
| layer_attribution | TEXT | JSON-encoded list: 어느 Layer가 어떻게 작용했는지 (`[{"layer":"A","action":"excluded","reason":"contiguous<60s"},...]`) | nullable |
| baseline_subtracted_length_seconds | REAL | Layer B가 빼낸 일치 분량 (초). 0이면 baseline 미작동 | nullable |
| pre_subtraction_i2 | REAL | Layer B 차감 전의 I-2 값 (보고서 audit용) | nullable |
| pre_subtraction_i6 | REAL | Layer B 차감 전의 I-6 값 | nullable |

**review_status enum 확장**: `'PENDING'` 추가. 의미: "운영자가 검토를 시작했으나 결정 보류". CHECK constraint를 새 값까지 포함하도록 갱신.

**Migration 방법**: `storage/content_db.py::migrate_to_v2(db_path)` 가 sqlite_master + PRAGMA table_info로 컬럼 존재 여부 확인 후 누락분만 ALTER 실행. CLI 시작 시 1회 호출, idempotent.

---

## 3. NEW TABLE: `professor_pool`

| Field | Type | Description |
|---|---|---|
| professor_id | TEXT (PK) | 운영자가 부여하는 식별자 (예: `"prof-park-jc"`) |
| display_name | TEXT NOT NULL | 표시명 |
| created_at | TEXT NOT NULL (ISO8601) | 등록 시각 |
| created_by | TEXT NOT NULL | 등록한 admin 식별자 |
| notes | TEXT | 자유 메모 |

**`professor_pool_membership` 보조 테이블**: (professor_id, channel_alias, author_marker) 매핑.

| Field | Type | Description |
|---|---|---|
| professor_id | TEXT (FK → professor_pool) | |
| channel_alias | TEXT | spec 003 별칭 |
| author_marker | TEXT | (a) `parsed_titles.professor` 값 또는 (b) `'__channel_owner__'` (별칭 = 단일 교수 의미) |
| registered_at | TEXT NOT NULL | |
| registered_by | TEXT NOT NULL | |
| PRIMARY KEY (professor_id, channel_alias, author_marker) | | |

**의미**: `(channel_alias, author_marker)` 조합으로 매핑되지 않은 영상은 어느 professor_pool에도 속하지 않음 → fallback (FR-032 후반): 해당 영상은 채널 단위 풀로 분석.

---

## 4. NEW TABLE: `baseline_corpus`

| Field | Type | Description |
|---|---|---|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | |
| professor_id | TEXT NOT NULL (FK) | |
| phrase_normalized | TEXT NOT NULL | R-7 normalize 결과 |
| phrase_raw | TEXT NOT NULL | 운영자 등록 원문 (audit/display) |
| occurrences | INTEGER NOT NULL DEFAULT 1 | bootstrap 시 발견 횟수 또는 admin 마킹 횟수 |
| source_video_ids | TEXT | JSON 배열. 어느 영상에서 학습됐는지 |
| seeded | INTEGER NOT NULL DEFAULT 0 | 1 = bootstrap 자동 시드, 0 = admin 수동 등록 |
| registered_at | TEXT NOT NULL | |
| registered_by | TEXT NOT NULL | |

**Unique constraint**: `(professor_id, phrase_normalized)` — 같은 정규화 어구 중복 등록 방지.

**Bootstrap 규칙** (R-3): 한 교수의 시기 가장 이른 N=5 영상에서 normalize 후 등장 빈도 ≥3 영상의 phrase가 시드로 자동 등록 (`seeded=1`).

---

## 5. NEW TABLE: `phrase_whitelist`

| Field | Type | Description |
|---|---|---|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | |
| professor_id | TEXT NOT NULL (FK) | per-professor scope (Q1 결정) |
| phrase_normalized | TEXT NOT NULL | R-7 normalize 결과 |
| phrase_raw | TEXT NOT NULL | 운영자 등록 원문 |
| reason | TEXT NOT NULL | 운영자 자유 텍스트 (audit) |
| registered_at | TEXT NOT NULL | |
| registered_by | TEXT NOT NULL | |

**Unique constraint**: `(professor_id, phrase_normalized)`.

**baseline_corpus 와의 차이**: `baseline_corpus`는 자동/반자동 학습된 stylistic recurrence (Layer B가 일치 분량을 차감); `phrase_whitelist`는 운영자가 명시적으로 "이 어구 일치는 무시" 라고 선언한 항목 (Layer D phrase-level 적용 — 일치 계산 자체에서 제외). 운영 단계의 의미가 다르므로 별도 테이블.

---

## 6. NEW TABLE: `pair_checkpoint`

| Field | Type | Description |
|---|---|---|
| run_id | TEXT (PK) | 분석 run 식별자 (예: `"nc2-prof-park-jc-20260601-2300"`) |
| professor_id | TEXT NOT NULL | |
| matching_mode | TEXT NOT NULL | `'M-default'` 또는 `'M-nC2'` |
| pair_count_total | INTEGER NOT NULL | 산출 대상 쌍 총수 |
| pair_count_done | INTEGER NOT NULL DEFAULT 0 | 완료된 쌍 수 |
| started_at | TEXT NOT NULL | |
| last_pair_at | TEXT | 마지막 쌍 처리 시각 |
| status | TEXT NOT NULL | `'in_progress'` / `'completed'` / `'aborted'` |

**진행률 표시 + 재개 단서**: 재시작 시 `comparison_results`에서 `(source_video_id, target_video_id, matching_mode='M-nC2', professor_id=...)` 존재 여부로 미완료 쌍 결정 (R-5).

---

## 7. NEW TABLE: `match_spans`

비교 쌍의 시간축 evidence 영속. 보고서 시각화 + audit 용도.

| Field | Type | Description |
|---|---|---|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | |
| comparison_id | INTEGER NOT NULL (FK → comparison_results.id) | |
| span_index | INTEGER NOT NULL | 한 쌍 내 span 순번 (0부터) |
| start_a_seconds | REAL NOT NULL | 영상 A에서 일치 시작 |
| end_a_seconds | REAL NOT NULL | 영상 A에서 일치 종료 |
| start_b_seconds | REAL NOT NULL | 영상 B에서 일치 시작 |
| end_b_seconds | REAL NOT NULL | 영상 B에서 일치 종료 |
| length_seconds | REAL NOT NULL | end - start (영상 A 기준) |
| matched_text_sample | TEXT | 일치 어구의 짧은 샘플 (보고서 표시용 50–100자) |
| baseline_subtracted | INTEGER NOT NULL DEFAULT 0 | 1 = Layer B가 이 span을 차감 |
| whitelisted | INTEGER NOT NULL DEFAULT 0 | 1 = Layer D phrase whitelist가 이 span을 제거 |

**Unique constraint**: `(comparison_id, span_index)`.

**저장 정책**: layer-defense 적용 후 최종 span만 저장 (Layer B/D 적용 전 raw span은 audit 컬럼으로만 길이 합계를 별도 보관 — `comparison_results.pre_subtraction_i6` 등). 영상 풀이 큰 경우 storage 폭증 방지 목적.

---

## 8. NEW TABLE: `policy_config` (또는 YAML 파일)

선택지 두 가지 — Phase 1 contract 단계에서 결정 후 일관 사용:

**Option A — SQLite 테이블**:

| Field | Type | Description |
|---|---|---|
| key | TEXT PK | 정책 키 (예: `"layer_a_min_seconds"`) |
| value | TEXT | JSON-encoded 값 |
| updated_at | TEXT | |
| updated_by | TEXT | |

**Option B — YAML 파일** (`02_analyze/content/policy.yaml`):

```yaml
layer_a_min_seconds: 60
layer_c_evolution_band: [0.60, 0.75]
matching_cosine_cull: 0.55
pattern_whole_threshold_ratio: 0.50
composite_weights:
  i1: 0.20
  i2: 0.20
  i3: 0.10
  i4: 0.05
  i5: 0.05
  i6: 0.20
  i7: 0.10
  i8: 0.10
```

**Decision (this plan)**: Option B (YAML) — Constitution V는 SQLite도 허용하나 운영자가 외부 정책 문서와 동기화하는 시점에 손으로 수정하기 쉬운 YAML이 R-4 운영 시나리오에 맞다. CLI는 YAML을 읽기만 하고, 변경은 admin이 텍스트 에디터로.

---

## 9. Pydantic 모델 (in-memory)

`src/tube_scout/models/content.py` (확장) + `src/tube_scout/models/reuse_v2.py` (신규):

```python
# models/content.py 확장 (스케치)
class ComparisonResult(BaseModel):
    # 기존 spec 007 필드 ...
    matching_mode: Literal["M-default", "M-nC2"]
    professor_id: str | None = None
    i6_longest_contiguous_seconds: float | None = None
    i7_distribution_dispersion: float | None = None
    i8_position_diversity: float | None = None
    reuse_pattern: ReusePatternLabel | None = None
    layer_attribution: list[LayerAttribution] = Field(default_factory=list)
    baseline_subtracted_length_seconds: float | None = None
    pre_subtraction_i2: float | None = None
    pre_subtraction_i6: float | None = None

# models/reuse_v2.py
class ReusePatternLabel(str, Enum):
    WHOLE_SAME_WEEK = "whole-same-week"
    SCATTERED_SAME_WEEK = "scattered-same-week"
    WHOLE_DIFF_WEEK = "whole-different-week"
    SCATTERED_DIFF_WEEK = "scattered-different-week"

class LayerAttribution(BaseModel):
    layer: Literal["A", "B", "C", "D"]
    action: Literal["excluded", "demoted", "subtracted", "no-op"]
    reason: str  # English, actionable

class MatchSpan(BaseModel):
    start_a_seconds: float
    end_a_seconds: float
    start_b_seconds: float
    end_b_seconds: float
    length_seconds: float
    matched_text_sample: str
    baseline_subtracted: bool = False
    whitelisted: bool = False

class CaptionPool(BaseModel):
    professor_id: str
    video_refs: list[VideoRef]  # (channel_alias, video_id, author_marker)

class BaselinePhrase(BaseModel):
    professor_id: str
    phrase_normalized: str
    phrase_raw: str
    occurrences: int
    source_video_ids: list[str]
    seeded: bool

class WhitelistPairEntry(BaseModel):
    source_video_id: str
    target_video_id: str
    professor_id: str | None
    reason: str
    admin: str
    registered_at: datetime

class WhitelistPhraseEntry(BaseModel):
    professor_id: str
    phrase_normalized: str
    phrase_raw: str
    reason: str
    admin: str
    registered_at: datetime

class PairCheckpoint(BaseModel):
    run_id: str
    professor_id: str
    matching_mode: Literal["M-default", "M-nC2"]
    pair_count_total: int
    pair_count_done: int
    started_at: datetime
    last_pair_at: datetime | None
    status: Literal["in_progress", "completed", "aborted"]

class PolicyConfig(BaseModel):
    layer_a_min_seconds: float = 60.0
    layer_c_evolution_band: tuple[float, float] = (0.60, 0.75)
    matching_cosine_cull: float = 0.55
    pattern_whole_threshold_ratio: float = 0.50
    composite_weights: dict[str, float]
```

---

## 10. Relationships

```
professor_pool (professor_id)
    ├── 1:N → professor_pool_membership (professor_id, channel_alias, author_marker)
    ├── 1:N → baseline_corpus (professor_id)
    ├── 1:N → phrase_whitelist (professor_id)
    └── 1:N → comparison_results (professor_id, when matching_mode='M-nC2')

comparison_results (id)
    └── 1:N → match_spans (comparison_id)

pair_checkpoint (run_id) → comparison_results (matching_mode + professor_id 필터)
```

---

## 11. State Transitions

### 11.1 Comparison Pipeline State (per pair)

```
[ NEW pair generated ]
   ↓ services/nc2_matcher.py 가 1차 cosine cull
[ cull-filtered ]   →  버려짐 (저장 안 함)
   ↓
[ candidate ]
   ↓ services/time_axis_indicators.py 가 alignment + I-6/I-7/I-8 산출
[ measured ]
   ↓ services/layer_defense.py
   ├─ Layer A 길이 컷 fail → comparison_results.layer_attribution=A:excluded, suspicion_score=NULL → match_spans 미저장
   ├─ Layer B baseline 차감 → pre_subtraction_* 컬럼 채움, 본 컬럼은 차감 후
   ├─ Layer D phrase whitelist 차감 → match_spans.whitelisted=1
   ├─ Layer C 진화 demote → grade='moderate' 또는 'normal'
   └─ Layer D pair whitelist hit → comparison_results 자체 스킵 (저장 안 함)
   ↓
[ scored ]
   ↓ services/pattern_classifier.py
[ classified (reuse_pattern 부여) ]
   ↓
[ stored ]   ← UPSERT into comparison_results, INSERT into match_spans
```

### 11.2 Review State (per comparison row)

```
UNREVIEWED  ──(admin marks)──→  PENDING
UNREVIEWED  ──(admin marks)──→  CONFIRMED_DUPLICATE  ──(reanalysis)──→  CONFIRMED_DUPLICATE (재알림 안 함)
UNREVIEWED  ──(admin marks)──→  FALSE_POSITIVE       ──(reanalysis)──→  FALSE_POSITIVE (재알림 안 함, Layer D 작동)
PENDING     ──(admin마무리)──→  CONFIRMED_DUPLICATE 또는 FALSE_POSITIVE
```

모든 review state 변경은 `services/advisory_lock.py::layer_d_write_lock(db)` 컨텍스트 안에서 SQLite `BEGIN IMMEDIATE` 트랜잭션으로 수행 (R-6).

---

## 12. SQLite DDL (요약)

```sql
-- ALTER comparison_results (idempotent)
ALTER TABLE comparison_results ADD COLUMN matching_mode TEXT NOT NULL DEFAULT 'M-default';
ALTER TABLE comparison_results ADD COLUMN professor_id TEXT;
ALTER TABLE comparison_results ADD COLUMN i6_longest_contiguous_seconds REAL;
ALTER TABLE comparison_results ADD COLUMN i7_distribution_dispersion REAL;
ALTER TABLE comparison_results ADD COLUMN i8_position_diversity REAL;
ALTER TABLE comparison_results ADD COLUMN reuse_pattern TEXT;
ALTER TABLE comparison_results ADD COLUMN layer_attribution TEXT;
ALTER TABLE comparison_results ADD COLUMN baseline_subtracted_length_seconds REAL;
ALTER TABLE comparison_results ADD COLUMN pre_subtraction_i2 REAL;
ALTER TABLE comparison_results ADD COLUMN pre_subtraction_i6 REAL;
CREATE INDEX IF NOT EXISTS idx_cr_mode ON comparison_results(matching_mode);
CREATE INDEX IF NOT EXISTS idx_cr_prof ON comparison_results(professor_id);
CREATE INDEX IF NOT EXISTS idx_cr_pattern ON comparison_results(reuse_pattern);

-- 신규 테이블
CREATE TABLE IF NOT EXISTS professor_pool (
    professor_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS professor_pool_membership (
    professor_id TEXT NOT NULL,
    channel_alias TEXT NOT NULL,
    author_marker TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    PRIMARY KEY (professor_id, channel_alias, author_marker),
    FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
);

CREATE TABLE IF NOT EXISTS baseline_corpus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    professor_id TEXT NOT NULL,
    phrase_normalized TEXT NOT NULL,
    phrase_raw TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    source_video_ids TEXT,
    seeded INTEGER NOT NULL DEFAULT 0,
    registered_at TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    UNIQUE(professor_id, phrase_normalized),
    FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
);

CREATE TABLE IF NOT EXISTS phrase_whitelist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    professor_id TEXT NOT NULL,
    phrase_normalized TEXT NOT NULL,
    phrase_raw TEXT NOT NULL,
    reason TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    UNIQUE(professor_id, phrase_normalized),
    FOREIGN KEY (professor_id) REFERENCES professor_pool(professor_id)
);

CREATE TABLE IF NOT EXISTS pair_checkpoint (
    run_id TEXT PRIMARY KEY,
    professor_id TEXT NOT NULL,
    matching_mode TEXT NOT NULL,
    pair_count_total INTEGER NOT NULL,
    pair_count_done INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    last_pair_at TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id INTEGER NOT NULL,
    span_index INTEGER NOT NULL,
    start_a_seconds REAL NOT NULL,
    end_a_seconds REAL NOT NULL,
    start_b_seconds REAL NOT NULL,
    end_b_seconds REAL NOT NULL,
    length_seconds REAL NOT NULL,
    matched_text_sample TEXT,
    baseline_subtracted INTEGER NOT NULL DEFAULT 0,
    whitelisted INTEGER NOT NULL DEFAULT 0,
    UNIQUE (comparison_id, span_index),
    FOREIGN KEY (comparison_id) REFERENCES comparison_results(id)
);
CREATE INDEX IF NOT EXISTS idx_span_cmp ON match_spans(comparison_id);
```

`policy.yaml` 은 별도 파일이므로 DDL 없음.

---

## 13. Validation Rules

- `matching_mode` ∈ {`M-default`, `M-nC2`}; 다른 값 INSERT 시도는 fail-fast (CHECK constraint).
- `reuse_pattern` ∈ enum 4값 또는 NULL.
- `review_status` ∈ {UNREVIEWED, PENDING, CONFIRMED_DUPLICATE, FALSE_POSITIVE}.
- Layer A 적용 시 `i6_longest_contiguous_seconds < policy.layer_a_min_seconds` → 해당 row는 영속하지 않거나 영속하되 grade=NULL + layer_attribution=A:excluded.
- baseline_corpus / phrase_whitelist 의 `phrase_normalized`는 `services/phrase_whitelist.py::normalize_phrase()` 결과여야 함 (서비스 계층에서 강제, DB는 raw enforcement 못 함).
- `match_spans.start_x_seconds < end_x_seconds` 모든 row.
- `professor_pool_membership.author_marker = '__channel_owner__'` 인 row가 한 alias에 둘 이상 존재하면 fail-fast (한 채널 = 한 교수 가정 위반).

모든 validation은 service 계층의 Pydantic + 명시적 ValueError로 일차 차단; SQLite CHECK constraint는 보조 방어선.
